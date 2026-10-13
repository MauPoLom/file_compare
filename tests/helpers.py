"""Shared helpers for the test suite (standard library only).

Every test works in a temporary sandbox that holds its own copy of the two scripts,
so the tests never read your config.ini and never touch your own folders.

Environment switch (only meant for testing the tests themselves):
    DUPFINDER_TEST_NO_LINKS=1   behave as if symbolic links and hard links are not available
"""
import contextlib
import csv
import io
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = ("find_matches.py", "delete_matches.py")
IS_WINDOWS = os.name == "nt"
CAN_RAW_BYTE_NAMES = sys.platform.startswith("linux")
LOG_FIELDS = ["timestamp", "action", "status", "source", "destination", "checksum", "reason"]


def _probe_links():
    """Return (symlinks_possible, hardlinks_possible) for this system."""
    if os.environ.get("DUPFINDER_TEST_NO_LINKS"):
        return False, False
    symlinks = hardlinks = False
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "target"
        target.write_text("x")
        try:
            os.symlink(str(target), str(Path(tmp) / "sym"))
            symlinks = True
        except (OSError, NotImplementedError, AttributeError):
            pass
        try:
            os.link(str(target), str(Path(tmp) / "hard"))
            hardlinks = True
        except (OSError, NotImplementedError, AttributeError):
            pass
    return symlinks, hardlinks


HAVE_SYMLINKS, HAVE_HARDLINKS = _probe_links()


class Result:
    """Outcome of one script run (same attribute names as subprocess.CompletedProcess)."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    @property
    def output(self):
        return self.stdout + self.stderr


def read_csv(path):
    with open(str(path), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Sandbox:
    """A temporary working folder: scripts, config, sample data, outputs."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="dupfinder_test_")
        self.root = Path(self._tmp.name).resolve()
        self.data = self.root / "data"
        self.base = self.data / "base"
        self.copy = self.data / "copy"
        self.base.mkdir(parents=True)
        self.copy.mkdir(parents=True)
        for name in SCRIPTS:
            shutil.copy2(str(REPO / name), str(self.root / name))
        self.config_path = self.root / "config.ini"
        self.matches = self.root / "matches.csv"
        self.not_selected = self.root / "not_selected.csv"
        self.quarantine = self.root / "quarantine"
        self.log = self.root / "deleted_log.csv"
        self.links = {"hard": False, "sym": False, "broken": False}

    def cleanup(self):
        try:
            self._tmp.cleanup()
        except OSError:
            pass  # Windows may keep a handle open for a moment; the temp folder is harmless

    # ----------------------------------------------------------- sample data
    def write(self, rel, content=b""):
        path = self.data / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def build_basic(self):
        """base: 5 images; copy: 6 images (+ a hard link, a symlink and a broken symlink if possible)."""
        w = self.write
        w("base/a.jpg", b"AAA")
        w("base/d.jpg", b"DDDD")
        w("base/only_base.jpg", b"OB")
        w("base/samename.png", b"BBB")
        w("base/empty.jpg", b"")
        w("copy/other/a.jpg", b"AAA")
        w("copy/other/deep/A.JPG", b"AAA")
        w("copy/samename.png", b"XXX")
        w("copy/only_copy.png", b"OC")
        w("copy/empty.jpg", b"")
        w("copy/lnk/d_renamed.jpg", b"DDDD")
        if HAVE_HARDLINKS:
            (self.copy / "hl").mkdir()
            os.link(str(self.base / "a.jpg"), str(self.copy / "hl" / "a.jpg"))
            self.links["hard"] = True
        if HAVE_SYMLINKS:
            os.symlink(str(self.base / "d.jpg"), str(self.copy / "lnk" / "d.jpg"))
            self.links["sym"] = True
            os.symlink(str(self.data / "does_not_exist"), str(self.copy / "broken.jpg"))
            self.links["broken"] = True

    def copy_scanned(self):
        """Number of files of folder_copy that the scan can list and stat."""
        return 6 + int(self.links["hard"]) + int(self.links["sym"])

    base_scanned = 5

    def add_excluded_dirs(self):
        w = self.write
        w("base/@eaDir/a.jpg", b"AAA")
        w("base/Private/secret.jpg", b"SEC")
        w("base/sub/Thumbs/x.jpg", b"X1")
        w("copy/@eaDir/a.jpg", b"AAA")
        w("copy/Private/secret.jpg", b"SEC")
        w("copy/x/thumbs/y.jpg", b"Y1")

    def build_two(self):
        """Two matching files in different sub-folders (used by the delete tests)."""
        w = self.write
        w("base/a.jpg", b"AAA")
        w("base/b.jpg", b"BBB")
        w("copy/sub/a.jpg", b"AAA")
        w("copy/sub/deep/b.jpg", b"BBB")

    def build_single(self):
        self.write("base/a.jpg", b"AAA")
        self.write("copy/sub/a.jpg", b"AAA")

    # ----------------------------------------------------------- config / runs
    def config(self, options=(), exclude=(), delete=()):
        """Write config.ini. exclude=None leaves the exclude_folders key out completely."""
        lines = ["[folders]", "folder_base = %s" % self.base, "folder_copy = %s" % self.copy]
        if exclude is not None:
            lines.append("exclude_folders =")
            lines += ["    %s" % entry for entry in exclude]
        lines += ["[options]", "output = %s" % self.matches,
                  "not_selected_output = %s" % self.not_selected]
        lines += list(options)
        lines += ["[delete]", "quarantine_folder = %s" % self.quarantine, "log_file = %s" % self.log]
        lines += list(delete)
        self.config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run(self, script, *args, input_text=None):
        """Run a script as a separate process inside the sandbox. stdin is empty unless input_text is given."""
        env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        kwargs = {"input": input_text} if input_text is not None else {"stdin": subprocess.DEVNULL}
        proc = subprocess.run([sys.executable, str(self.root / script)] + [str(a) for a in args],
                              cwd=str(self.root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, encoding="utf-8", errors="replace", **kwargs)
        return Result(proc.returncode, proc.stdout, proc.stderr)

    def find(self, *args, **kw):
        return self.run("find_matches.py", *args, **kw)

    def delete(self, *args, **kw):
        return self.run("delete_matches.py", *args, **kw)

    def delete_real(self, *args, **kw):
        return self.run("delete_matches.py", "--delete", "--yes", *args, **kw)

    def run_inprocess(self, script, *args, patches=()):
        """Run a script inside this process (needed to simulate Ctrl+C or a failing move)."""
        out, err = io.StringIO(), io.StringIO()
        saved_argv, saved_cwd = sys.argv, os.getcwd()
        code = 0
        try:
            os.chdir(str(self.root))
            sys.argv = [script] + [str(a) for a in args]
            with contextlib.ExitStack() as stack:
                for patch in patches:
                    stack.enter_context(patch)
                stack.enter_context(contextlib.redirect_stdout(out))
                stack.enter_context(contextlib.redirect_stderr(err))
                try:
                    runpy.run_path(str(self.root / script), run_name="__main__")
                except SystemExit as e:
                    code = e.code if e.code is not None else 0
        finally:
            sys.argv = saved_argv
            os.chdir(saved_cwd)
        return Result(code, out.getvalue(), err.getvalue())

    # ----------------------------------------------------------- inspecting results
    def rel(self, path):
        """Path relative to the data folder, with forward slashes (same on every OS)."""
        return Path(path).relative_to(self.data).as_posix()

    def selected(self):
        return {self.rel(r["path_filename"]) for r in read_csv(self.matches)}

    def not_selected_rows(self):
        return read_csv(self.not_selected)

    def reasons(self):
        return {(r["folder"], self.rel(r["path_filename"])): r["reason"] for r in self.not_selected_rows()}

    def exists(self, rel):
        return os.path.lexists(str(self.data / rel))

    def quarantined(self):
        """Relative paths (posix) of all files below the quarantine folder."""
        if not self.quarantine.exists():
            return set()
        return {p.relative_to(self.quarantine).as_posix() for p in self.quarantine.rglob("*") if p.is_file()}


class SandboxTestCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)


__all__ = ["REPO", "SCRIPTS", "IS_WINDOWS", "CAN_RAW_BYTE_NAMES", "LOG_FIELDS", "HAVE_SYMLINKS",
           "HAVE_HARDLINKS", "Result", "read_csv", "Sandbox", "SandboxTestCase", "mock"]
