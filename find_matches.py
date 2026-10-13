#!/usr/bin/env python3
"""find_matches.py - find images that exist in two folders and list them in a CSV.

Settings are read from config.ini (see README.md).
Usage: python find_matches.py [--help]

Copyright (c) 2026 MauPoLom - MIT License (see LICENSE).
"""
from __future__ import annotations

import argparse
import configparser
import csv
import hashlib
import os
import sys
from pathlib import Path

__version__ = "1.2.0"
__author__ = "MauPoLom"

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.ini"

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jfif", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".avif", ".heic", ".heif", ".svg", ".ico",
    ".raw", ".cr2", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf", ".pef", ".srw",
}

PLACEHOLDER_PATHS = {"/path/to/folder_base", "/path/to/folder_copy"}
MATCH_MODES = ("name_and_checksum", "checksum")
NOT_SELECTED_SCOPES = ("folder_copy", "both")
CSV_FIELDS = ["path", "filename", "path_filename", "checksum", "other_copy", "root", "other_root"]
NOT_SELECTED_FIELDS = ["folder", "path", "filename", "path_filename", "size_bytes", "checksum", "reason"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def warn(message: str) -> None:
    """Print a warning to stderr (starts on a fresh line if a progress line is active)."""
    prefix = "\n" if sys.stderr.isatty() else ""
    print(prefix + message, file=sys.stderr)


class Progress:
    """Small progress indicator on stderr (live line on a terminal, sparse lines when redirected)."""

    def __init__(self, label: str, total: int | None = None):
        self.label, self.total, self.n = label, total, 0
        self.tty = sys.stderr.isatty()

    def _text(self) -> str:
        count = f"{self.n}/{self.total}" if self.total is not None else f"{self.n}"
        return f"{self.label}: {count} files"

    def update(self) -> None:
        self.n += 1
        if self.tty and self.n % 25 == 0:
            sys.stderr.write("\r" + self._text())
            sys.stderr.flush()
        elif not self.tty and self.n % 5000 == 0:
            print(self._text(), file=sys.stderr)

    def done(self) -> None:
        if self.tty:
            sys.stderr.write("\r" + self._text() + "\n")
            sys.stderr.flush()
        else:
            print(self._text(), file=sys.stderr)


def sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def same_file(a: Path, b: Path) -> bool:
    """True if both paths are the same physical file (same path, symlink or hard link)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def is_inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def clean_entry(value: str) -> str:
    return value.strip().strip('"').strip("'").strip()


class Excluder:
    """Folders that are skipped while scanning, in BOTH scanned folders.

    An entry is either a plain folder name (matches a folder with that name at any depth)
    or an absolute path (matches exactly that folder). Everything below a skipped folder is skipped too.
    """

    def __init__(self, entries, case_insensitive: bool, roots):
        self.ci = case_insensitive
        self.entries: list[str] = []
        self.hits: dict[str, int] = {}
        self._names: dict[str, str] = {}
        self._paths: dict[str, str] = {}
        for raw in entries:
            entry = clean_entry(raw)
            if not entry or entry in self.hits:
                continue
            if "/" in entry or "\\" in entry:
                path = Path(entry).expanduser()
                if not path.is_absolute():
                    sys.exit(f"Exclude entry '{entry}' is not valid: use a plain folder name "
                             f"(for example @eaDir) or an absolute path.")
                path = path.resolve()
                if any(is_inside(root, path) for root in roots):
                    sys.exit(f"Exclude entry '{entry}' covers a whole scanned folder; "
                             f"that would leave nothing to compare.")
                if not any(is_inside(path, root) for root in roots):
                    warn(f"Exclude entry '{entry}' is not inside folder_base or folder_copy and is ignored.")
                    continue
                self._paths[self._key(str(path))] = entry
            elif entry in (".", ".."):
                sys.exit(f"Exclude entry '{entry}' is not valid.")
            else:
                self._names[self._key(entry)] = entry
            self.entries.append(entry)
            self.hits[entry] = 0

    def _key(self, text: str) -> str:
        return text.casefold() if self.ci else text

    def is_excluded(self, folder: Path) -> bool:
        entry = self._names.get(self._key(folder.name)) or self._paths.get(self._key(str(folder)))
        if entry is None:
            return False
        self.hits[entry] += 1
        return True

    def report(self) -> None:
        for entry in self.entries:
            if self.hits[entry]:
                print(f"excluded    : {entry} ({self.hits[entry]} folder(s) skipped)")
            else:
                warn(f"Exclude entry '{entry}' matched no folder - check the spelling.")


def scan(root: Path, all_files: bool, excluder: Excluder):
    """Yield every (image) file below root, recursively. Excluded and symlinked folders are not entered."""
    for dirpath, dirs, files in os.walk(root):
        here = Path(dirpath)
        dirs[:] = [d for d in dirs if not excluder.is_excluded(here / d)]
        for name in files:
            p = here / name
            if all_files or p.suffix.lower() in IMAGE_EXTS:
                yield p


def collect(root: Path, all_files: bool, label: str, excluder: Excluder):
    """Return ([(path, size), ...], {unreadable_path: error}) for every file below root."""
    prog = Progress(label)
    files, failed = [], {}
    for p in scan(root, all_files, excluder):
        try:
            files.append((p, p.stat().st_size))
        except OSError as e:
            failed[p] = str(e)
            warn(f"Skipping {p}: {e}")
            continue
        prog.update()
    prog.done()
    return files, failed


def human_size(n: float) -> str:
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def load_config(config_path: Path, explicit: bool) -> configparser.ConfigParser:
    """Read the INI file. Inline comments and % interpolation are disabled so
    paths containing '#', ';' or '%' are read exactly as typed."""
    cfg = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None)
    if not config_path.is_file():
        if explicit:
            sys.exit(f"Config file not found: {config_path}")
        return cfg
    try:
        cfg.read(config_path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError) as e:
        sys.exit(f"Could not read config file {config_path}:\n  {e}\n"
                 f"Tip: the lines of a multi-line value (such as the exclude_folders list) must be indented.")
    return cfg


def cfg_get(cfg, section, key, default=None):
    value = cfg.get(section, key, fallback=None)
    if value is None:
        return default
    value = clean_entry(value)
    return value if value else default


def cfg_bool(cfg, section, key, default):
    try:
        return cfg.getboolean(section, key, fallback=default)
    except ValueError:
        sys.exit(f"Config error: [{section}] {key} must be true/false (or yes/no, 1/0, on/off).")


def cfg_list(cfg, section, key) -> list[str]:
    """A setting with one entry per line (multi-line value) or a single entry."""
    raw = cfg.get(section, key, fallback="") or ""
    return [line for line in (clean_entry(x) for x in raw.splitlines()) if line and line[0] not in "#;"]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")  # never crash on odd filenames
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", type=Path, default=None,
                    help=f"path to config file (default: {DEFAULT_CONFIG})")
    ap.add_argument("--folder-base", default=None, help="override folder_base")
    ap.add_argument("--folder-copy", default=None, help="override folder_copy")
    ap.add_argument("--exclude", action="append", default=None, metavar="FOLDER",
                    help="folder name or absolute path to skip in BOTH scanned folders; "
                         "repeatable; replaces exclude_folders from the config file")
    ap.add_argument("-o", "--output", default=None, help="override output CSV")
    ap.add_argument("--not-selected-output", default=None, help="override not_selected_output CSV")
    ap.add_argument("--no-export-not-selected", action="store_true",
                    help="do not write the CSV with files that were not selected")
    ap.add_argument("--not-selected-scope", choices=NOT_SELECTED_SCOPES, default=None,
                    help="whose unselected files are exported: folder_copy (default) or both folders")
    ap.add_argument("--record", choices=["folder_base", "folder_copy"], default=None,
                    help="whose copy of each match is listed in the CSV")
    ap.add_argument("--match-by", choices=MATCH_MODES, default=None)
    ap.add_argument("--case-sensitive", action="store_true", help="force case-sensitive filename matching")
    ap.add_argument("--all-files", action="store_true", help="compare every file type")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args()

    config_path = args.config or DEFAULT_CONFIG
    cfg = load_config(config_path, explicit=args.config is not None)

    # Resolve settings: command line > config file > default
    base = args.folder_base or cfg_get(cfg, "folders", "folder_base")
    copy = args.folder_copy or cfg_get(cfg, "folders", "folder_copy")
    exclude_entries = args.exclude if args.exclude is not None else cfg_list(cfg, "folders", "exclude_folders")
    output = args.output or cfg_get(cfg, "options", "output", "matches.csv")
    record = args.record or cfg_get(cfg, "options", "record", "folder_copy")
    match_by = args.match_by or cfg_get(cfg, "options", "match_by", "name_and_checksum")
    case_insensitive = False if args.case_sensitive else cfg_bool(cfg, "options", "case_insensitive_names", True)
    all_files = True if args.all_files else cfg_bool(cfg, "options", "all_files", False)
    export_not_selected = False if args.no_export_not_selected else cfg_bool(cfg, "options", "export_not_selected", True)
    not_selected_output = args.not_selected_output or cfg_get(cfg, "options", "not_selected_output", "not_selected.csv")
    not_selected_scope = args.not_selected_scope or cfg_get(cfg, "options", "not_selected_scope", "folder_copy")

    if not base or not copy:
        sys.exit(f"folder_base and folder_copy must be set in [folders] of {config_path} "
                 f"(or passed with --folder-base / --folder-copy).\n"
                 f"Tip: copy config.example.ini to config.ini and edit it.")
    if base in PLACEHOLDER_PATHS or copy in PLACEHOLDER_PATHS:
        sys.exit(f"Please edit {config_path} and replace the placeholder folder paths with real ones.")
    if record not in ("folder_base", "folder_copy"):
        sys.exit("Config error: [options] record must be 'folder_base' or 'folder_copy'.")
    if match_by not in MATCH_MODES:
        sys.exit(f"Config error: [options] match_by must be one of: {', '.join(MATCH_MODES)}.")
    if not_selected_scope not in NOT_SELECTED_SCOPES:
        sys.exit(f"Config error: [options] not_selected_scope must be one of: {', '.join(NOT_SELECTED_SCOPES)}.")
    if export_not_selected and Path(output).resolve() == Path(not_selected_output).resolve():
        sys.exit("output and not_selected_output must be two different files.")

    folder_base = Path(base).expanduser().resolve()
    folder_copy = Path(copy).expanduser().resolve()
    for name, f in (("folder_base", folder_base), ("folder_copy", folder_copy)):
        if not f.is_dir():
            sys.exit(f"{name} is not an existing folder: {f}")
    if is_inside(folder_base, folder_copy) or is_inside(folder_copy, folder_base):
        sys.exit("folder_base and folder_copy must be two separate folders; "
                 "they may not be identical or nested inside each other.")

    excluder = Excluder(exclude_entries, case_insensitive, (folder_base, folder_copy))

    name_mode = match_by == "name_and_checksum"
    print(f"folder_base : {folder_base}")
    print(f"folder_copy : {folder_copy}")
    print(f"match_by    : {match_by}"
          + (f" ({'case-insensitive' if case_insensitive else 'case-sensitive'} names)" if name_mode else ""))
    print(f"record      : {record}")

    def name_key(name: str) -> str:
        return name.casefold() if case_insensitive else name

    # 1. Scan both folders (with sizes); excluded folders are skipped in both
    base_files, base_failed = collect(folder_base, all_files, "Scanning folder_base", excluder)
    copy_files, copy_failed = collect(folder_copy, all_files, "Scanning folder_copy", excluder)
    excluder.report()
    unreadable: dict[Path, str] = {**base_failed, **copy_failed}

    # 2. Index folder_base: by name in name mode, by size in checksum mode
    index: dict = {}
    for p, size in base_files:
        key = name_key(p.name) if name_mode else size
        index.setdefault(key, []).append((p, size))

    hash_cache: dict[Path, str] = {}

    def safe_hash(p: Path):
        """SHA-256 of p, or None (reported once) if the file cannot be read."""
        if p in unreadable:
            return None
        try:
            if p not in hash_cache:
                hash_cache[p] = sha256(p)
            return hash_cache[p]
        except OSError as e:
            unreadable[p] = str(e)
            warn(f"Skipping {p}: {e}")
            return None

    # 3. Compare
    rows = []
    recorded: set[Path] = set()      # files listed in matches.csv (selected)
    identical: set[Path] = set()     # files that have an identical counterpart in the other folder
    linked: set[Path] = set()        # files that are a link to their counterpart (same physical file)
    reclaim = 0
    prog = Progress("Comparing", total=len(copy_files))
    for p_copy, size_copy in copy_files:
        prog.update()
        if not name_mode and size_copy == 0:
            continue  # empty files are not meaningful duplicates when names are ignored
        key = name_key(p_copy.name) if name_mode else size_copy
        # Files of different size can never be identical: only same-size candidates are hashed
        candidates = [p for p, s in index.get(key, []) if s == size_copy]
        if not candidates:
            continue
        h_copy = safe_hash(p_copy)
        if h_copy is None:
            continue
        first = True
        for p_base in candidates:
            h_base = safe_hash(p_base)
            if h_base is None or h_base != h_copy:
                continue
            if same_file(p_base, p_copy):
                linked.update((p_base, p_copy))  # symlink / hard link: not a real duplicate
                continue
            identical.update((p_base, p_copy))
            if not first:
                continue  # only the first identical file becomes a row
            first = False
            rec, other, root, other_root = ((p_copy, p_base, folder_copy, folder_base) if record == "folder_copy"
                                            else (p_base, p_copy, folder_base, folder_copy))
            if rec not in recorded:  # a base file can match several copies: list it once
                recorded.add(rec)
                rows.append({
                    "path": str(rec.parent),
                    "filename": rec.name,
                    "path_filename": str(rec),
                    "checksum": h_copy,
                    "other_copy": str(other),
                    "root": str(root),
                    "other_root": str(other_root),
                })
                reclaim += size_copy
    prog.done()

    try:
        with open(output, "w", newline="", encoding="utf-8", errors="surrogateescape") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            w.writerows(rows)
    except OSError as e:
        sys.exit(f"Could not write {output}: {e}")

    print(f"{len(rows)} match(es) written to {output} "
          f"(space that can be freed: {human_size(reclaim)})")

    # 4. Export everything that was NOT selected for deletion
    if export_not_selected:
        base_names = set(index) if name_mode else set()
        copy_names = {name_key(p.name) for p, _ in copy_files} if name_mode else set()

        def reason(p: Path, size: int, other_names: set) -> str:
            if p in unreadable:
                return "unreadable"
            if not name_mode and size == 0:
                return "empty_file_ignored"
            if p in identical:
                return "kept_identical_to_selected"
            if p in linked:
                return "same_physical_file"
            if name_mode and name_key(p.name) in other_names:
                return "same_name_different_content"
            return "no_match"

        def not_selected_rows():
            for label, files, failed, other_names in (
                    ("folder_base", base_files, base_failed, copy_names),
                    ("folder_copy", copy_files, copy_failed, base_names)):
                if label == "folder_base" and not_selected_scope == "folder_copy":
                    continue  # scope: export only the unselected files of folder_copy
                for p, size in sorted(files, key=lambda t: str(t[0])):
                    if p in recorded:
                        continue
                    yield {"folder": label, "path": str(p.parent), "filename": p.name,
                           "path_filename": str(p), "size_bytes": size,
                           "checksum": hash_cache.get(p, ""), "reason": reason(p, size, other_names)}
                for p in sorted(failed, key=str):  # files that could not even be listed
                    yield {"folder": label, "path": str(p.parent), "filename": p.name,
                           "path_filename": str(p), "size_bytes": "", "checksum": "", "reason": "unreadable"}

        count = 0
        try:
            with open(not_selected_output, "w", newline="", encoding="utf-8", errors="surrogateescape") as f:
                w = csv.DictWriter(f, fieldnames=NOT_SELECTED_FIELDS)
                w.writeheader()
                for row in not_selected_rows():
                    w.writerow(row)
                    count += 1
        except OSError as e:
            sys.exit(f"Could not write {not_selected_output}: {e}")
        scope_text = "folder_copy" if not_selected_scope == "folder_copy" else "both folders"
        print(f"{count} file(s) of {scope_text} not selected for deletion written to {not_selected_output}")

    if unreadable:
        print(f"WARNING: {len(unreadable)} file(s) could not be read and were skipped "
              f"(see messages above); the result may be incomplete.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Output files, if any, may be incomplete.", file=sys.stderr)
        sys.exit(130)
