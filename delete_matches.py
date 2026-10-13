#!/usr/bin/env python3
"""delete_matches.py - move (or delete) the files listed in the CSV from find_matches.py.

Dry run by default; add --delete to act. Settings come from config.ini (see README.md).
Usage: python delete_matches.py [--delete] [--help]

Copyright (c) 2026 MauPoLom - MIT License (see LICENSE).
"""
from __future__ import annotations

import argparse
import configparser
import csv
import hashlib
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

__version__ = "1.2.0"
__author__ = "MauPoLom"

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.ini"
LOG_FIELDS = ["timestamp", "action", "status", "source", "destination", "checksum", "reason"]
REQUIRED_COLUMNS = ["path_filename", "checksum", "other_copy", "root", "other_root"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
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
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def load_config(config_path: Path, explicit: bool) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None)
    if not config_path.is_file():
        if explicit:
            sys.exit(f"Config file not found: {config_path}")
        return cfg
    try:
        cfg.read(config_path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError) as e:
        sys.exit(f"Could not read config file {config_path}:\n  {e}")
    return cfg


def cfg_get(cfg, section, key, default=None):
    value = cfg.get(section, key, fallback=None)
    if value is None:
        return default
    value = value.strip().strip('"').strip("'").strip()
    return value if value else default


def cfg_bool(cfg, section, key, default):
    try:
        return cfg.getboolean(section, key, fallback=default)
    except ValueError:
        sys.exit(f"Config error: [{section}] {key} must be true/false (or yes/no, 1/0, on/off).")


def unique_dest(dest: Path) -> Path:
    """If dest already exists, return dest with ' (1)', ' (2)' ... added before the extension."""
    if not dest.exists():
        return dest
    i = 1
    while True:
        cand = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        if not cand.exists():
            return cand
        i += 1


class Logger:
    """Appends rows to the log CSV (header written if the file is new). Local time."""

    def __init__(self, path: Path, enabled: bool):
        self.path, self.enabled = path, enabled
        self._fh = self._writer = None

    def open(self) -> None:
        """Open eagerly so a problem with the log file is found before any file is touched."""
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists() or self.path.stat().st_size == 0
        self._fh = open(self.path, "a", newline="", encoding="utf-8", errors="surrogateescape")
        self._writer = csv.DictWriter(self._fh, fieldnames=LOG_FIELDS)
        if new:
            self._writer.writeheader()
            self._fh.flush()

    def log(self, action, status, source, destination="", checksum="", reason="") -> None:
        if not self._writer:
            return
        self._writer.writerow({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "action": action, "status": status, "source": str(source),
            "destination": str(destination), "checksum": checksum, "reason": reason,
        })
        self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()


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
    ap.add_argument("-c", "--config", type=Path, default=None, help=f"config file (default: {DEFAULT_CONFIG})")
    ap.add_argument("-i", "--input", default=None, help="CSV to read")
    ap.add_argument("--quarantine", default=None, help="quarantine folder")
    ap.add_argument("--log", default=None, help="log file")
    ap.add_argument("--keep-empty-folders", action="store_true", help="do not remove emptied folders")
    ap.add_argument("--permanent", action="store_true", help="delete for good instead of quarantining")
    ap.add_argument("--delete", action="store_true", help="actually do it (default is a dry run)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args()

    config_path = args.config or DEFAULT_CONFIG
    cfg = load_config(config_path, explicit=args.config is not None)

    input_csv = Path(args.input or cfg_get(cfg, "options", "output", "matches.csv")).expanduser()
    quarantine = Path(args.quarantine or cfg_get(cfg, "delete", "quarantine_folder", "quarantine")).expanduser()
    log_path = Path(args.log or cfg_get(cfg, "delete", "log_file", "deleted_log.csv")).expanduser()
    remove_empty = False if args.keep_empty_folders else cfg_bool(cfg, "delete", "remove_empty_folders", True)
    permanent = True if args.permanent else cfg_bool(cfg, "delete", "permanent_delete", False)

    if not input_csv.is_file():
        print(f"CSV not found: {input_csv}", file=sys.stderr)
        return 1
    try:
        with open(input_csv, newline="", encoding="utf-8", errors="surrogateescape") as f:
            reader = csv.DictReader(f)
            missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                print(f"{input_csv} is not a valid matches file (missing column(s): {', '.join(missing)}).\n"
                      f"Create it with this version of find_matches.py.", file=sys.stderr)
                return 1
            rows = list(reader)
    except (OSError, csv.Error) as e:
        print(f"Could not read {input_csv}: {e}", file=sys.stderr)
        return 1
    if not rows:
        print("CSV is empty, nothing to do.")
        return 0

    # The quarantine folder may not overlap with either scanned folder
    if not permanent:
        roots = {Path(r[c]) for r in rows for c in ("root", "other_root") if r.get(c)}
        for root in roots:
            if is_inside(quarantine, root) or is_inside(root, quarantine):
                print(f"The quarantine folder ({quarantine}) overlaps with a scanned folder ({root}).\n"
                      f"Choose a quarantine_folder outside both scanned folders "
                      f"(config.ini [delete] or --quarantine).", file=sys.stderr)
                return 1

    action_word = "DELETE permanently" if permanent else f"MOVE to {quarantine}"
    mode = "REAL RUN" if args.delete else "DRY RUN"
    print(f"{len(rows)} file(s) listed in {input_csv}  [{mode}: {action_word}]")

    if args.delete and not args.yes:
        prompt = ("Permanently delete these files? This cannot be undone. Type 'yes' to continue: " if permanent
                  else f"Move these files to '{quarantine}'? Type 'yes' to continue: ")
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            print("\nNo interactive input available; use --yes to confirm non-interactively.", file=sys.stderr)
            return 1
        if answer != "yes":
            print("Aborted.")
            return 0

    logger = Logger(log_path, enabled=args.delete)
    try:
        logger.open()
    except OSError as e:
        print(f"Cannot write log file {log_path}: {e}\nNothing was changed.", file=sys.stderr)
        return 1

    done = skipped = errors = 0
    interrupted = False
    touched_dirs: set[tuple[Path, Path]] = set()
    hash_cache: dict[Path, str] = {}
    verb = "DELETE" if permanent else "MOVE"

    def get_hash(p: Path) -> str:
        if p not in hash_cache:
            hash_cache[p] = sha256(p)
        return hash_cache[p]

    def skip(target, reason, checksum=""):
        nonlocal skipped
        print(f"SKIP ({reason}): {target}")
        logger.log(verb, "SKIPPED", target, checksum=checksum, reason=reason)
        skipped += 1

    try:
        for row in rows:
            checksum = row.get("checksum") or ""
            if not all(row.get(c) for c in REQUIRED_COLUMNS):
                skip(row.get("path_filename") or "?", "incomplete row in CSV", checksum)
                continue
            target, other = Path(row["path_filename"]), Path(row["other_copy"])
            root = Path(row["root"])

            if root not in target.parents:
                skip(target, "not inside its recorded folder", checksum)
                continue
            if not target.is_file():
                skip(target, "missing", checksum)
                continue
            if not other.is_file():
                skip(target, "other copy missing - would lose last copy", checksum)
                continue
            if same_file(target, other):
                skip(target, "other copy is the same physical file", checksum)
                continue
            try:
                if get_hash(other) != checksum:
                    skip(target, "other copy has changed", checksum)
                    continue
                if get_hash(target) != checksum:
                    skip(target, "checksum changed", checksum)
                    continue
            except OSError as e:
                skip(target, f"unreadable: {e}", checksum)
                continue

            # Destination in quarantine keeps the sub-folder structure
            dest = None if permanent else unique_dest(quarantine / target.relative_to(root))

            if not args.delete:
                print(f"Would {'delete' if permanent else 'move'}: {target}" + (f"  ->  {dest}" if dest else ""))
                done += 1
                touched_dirs.add((target.parent, root))
                continue

            try:
                if permanent:
                    target.unlink()
                    print(f"DELETED: {target}")
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(dest))
                    print(f"MOVED: {target}  ->  {dest}")
                logger.log(verb, "OK", target, destination=dest or "", checksum=checksum)
                done += 1
                touched_dirs.add((target.parent, root))
            except OSError as e:
                if dest is not None and target.exists() and dest.exists():
                    try:
                        dest.unlink()  # remove the partial copy of a failed move; the original is intact
                    except OSError:
                        pass
                print(f"ERROR on {target}: {e}")
                logger.log(verb, "ERROR", target, destination=dest or "", checksum=checksum, reason=str(e))
                errors += 1
    except KeyboardInterrupt:
        interrupted = True
        print("\nInterrupted. Files already processed are listed in the log.", file=sys.stderr)

    # Remove folders that became empty (never the top-level folder itself)
    removed_dirs = 0
    if remove_empty and touched_dirs:
        if not args.delete:
            print("\nWould also remove sub-folders that become empty.")
        else:
            for parent, root in touched_dirs:
                cur = parent
                while cur != root and root in cur.parents:
                    try:
                        cur.rmdir()  # only succeeds if the folder is completely empty
                    except OSError:
                        break
                    print(f"REMOVED empty folder: {cur}")
                    logger.log("RMDIR", "OK", cur)
                    removed_dirs += 1
                    cur = cur.parent

    logger.close()

    past = {(True, True): "Deleted", (True, False): "Moved",
            (False, True): "Would delete", (False, False): "Would move"}[(args.delete, permanent)]
    print(f"\n{past}: {done} | Skipped: {skipped} | Errors: {errors}"
          + (f" | Empty folders removed: {removed_dirs}" if args.delete and remove_empty else ""))
    if args.delete:
        print(f"Log written to {log_path}")
    else:
        print("Dry run only - nothing was changed. Add --delete to do it for real.")
    if interrupted:
        return 130
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
