"""Tests for the matching behaviour of find_matches.py."""
import hashlib
import os
import re
import unittest

try:
    from helpers import (CAN_RAW_BYTE_NAMES, HAVE_HARDLINKS, HAVE_SYMLINKS, IS_WINDOWS, SandboxTestCase,
                         mock, read_csv)
except ImportError:  # started as a package from the repository root
    from .helpers import (CAN_RAW_BYTE_NAMES, HAVE_HARDLINKS, HAVE_SYMLINKS, IS_WINDOWS, SandboxTestCase,
                          mock, read_csv)


class MatchingTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.sb.build_basic()
        self.sb.config(exclude=None)

    def test_default_mode_selects_identical_copies(self):
        r = self.sb.find()
        self.assertEqual(r.returncode, 0, r.output)
        self.assertEqual(self.sb.selected(), {"copy/other/a.jpg", "copy/other/deep/A.JPG", "copy/empty.jpg"})

    def test_same_name_but_different_content_is_not_selected(self):
        self.sb.find()
        self.assertNotIn("copy/samename.png", self.sb.selected())

    def test_csv_columns_and_checksum(self):
        self.sb.find()
        rows = read_csv(self.sb.matches)
        self.assertEqual(list(rows[0].keys()),
                         ["path", "filename", "path_filename", "checksum", "other_copy", "root", "other_root"])
        row = [r for r in rows if r["filename"] == "a.jpg"][0]
        self.assertEqual(row["checksum"], hashlib.sha256(b"AAA").hexdigest())
        self.assertEqual(self.sb.rel(row["other_copy"]), "base/a.jpg")
        self.assertEqual(self.sb.rel(row["root"]), "copy")
        self.assertEqual(self.sb.rel(row["other_root"]), "base")

    def test_case_sensitive_names_via_cli(self):
        self.sb.find("--case-sensitive")
        self.assertEqual(self.sb.selected(), {"copy/other/a.jpg", "copy/empty.jpg"})

    def test_case_sensitive_names_via_config(self):
        self.sb.config(options=["case_insensitive_names = false"], exclude=None)
        self.sb.find()
        self.assertEqual(self.sb.selected(), {"copy/other/a.jpg", "copy/empty.jpg"})

    def test_checksum_mode_finds_renamed_duplicate_and_ignores_empty_files(self):
        r = self.sb.find("--match-by", "checksum")
        self.assertEqual(r.returncode, 0, r.output)
        self.assertEqual(self.sb.selected(),
                         {"copy/other/a.jpg", "copy/other/deep/A.JPG", "copy/lnk/d_renamed.jpg"})

    def test_record_folder_base_lists_each_base_file_once(self):
        self.sb.find("--record", "folder_base")
        rows = read_csv(self.sb.matches)
        paths = [self.sb.rel(r["path_filename"]) for r in rows]
        self.assertEqual(sorted(paths), ["base/a.jpg", "base/empty.jpg"])  # a.jpg has two copies, listed once
        self.assertTrue(all(self.sb.rel(r["other_copy"]).startswith("copy/") for r in rows))

    def test_all_files_option(self):
        self.sb.write("base/notes.txt", b"N")
        self.sb.write("copy/notes.txt", b"N")
        self.sb.find()
        self.assertNotIn("copy/notes.txt", self.sb.selected())
        self.sb.find("--all-files")
        self.assertIn("copy/notes.txt", self.sb.selected())

    @unittest.skipUnless(HAVE_HARDLINKS or HAVE_SYMLINKS, "links not available on this system")
    def test_links_to_the_same_file_are_never_duplicates(self):
        for extra in ([], ["--match-by", "checksum"]):
            self.sb.find(*extra)
            self.assertFalse(self.sb.selected() & {"copy/hl/a.jpg", "copy/lnk/d.jpg"}, extra)

    @unittest.skipUnless(HAVE_SYMLINKS, "symbolic links not available on this system")
    def test_symlinked_folders_are_not_followed(self):
        elsewhere = self.sb.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "a.jpg").write_bytes(b"AAA")
        os.symlink(str(elsewhere), str(self.sb.copy / "linkdir"), target_is_directory=True)
        self.sb.find()
        self.assertFalse([p for p in self.sb.selected() if "linkdir" in p])

    @unittest.skipUnless(HAVE_SYMLINKS, "symbolic links not available on this system")
    def test_unreadable_file_is_reported_but_run_continues(self):
        r = self.sb.find()
        self.assertEqual(r.returncode, 0, r.output)
        self.assertIn("could not be read", r.stderr)


class AwkwardNameTests(SandboxTestCase):
    def test_awkward_filenames_round_trip(self):
        names = ["we,ird ;#.jpg", "spa ce (1).jpg"]
        if not IS_WINDOWS:  # these characters are not allowed in Windows file names
            names += ['quote"d.jpg', "new\nline.jpg"]
        for n in names:
            self.sb.write("base/" + n, b"W" + n.encode("utf-8"))
            self.sb.write("copy/x_" + n, b"Z" + n.encode("utf-8"))
        self.sb.config(options=["not_selected_scope = both"], exclude=None)
        r = self.sb.find()
        self.assertEqual(r.returncode, 0, r.output)
        listed = {row["filename"] for row in self.sb.not_selected_rows()}
        self.assertTrue(set(names) <= listed)
        self.assertTrue({"x_" + n for n in names} <= listed)

    @unittest.skipUnless(CAN_RAW_BYTE_NAMES, "file names that are not valid UTF-8 only work on Linux")
    def test_undecodable_filename_is_found_and_moved(self):
        self.sb.config(exclude=None)
        name = b"bad\xff\xfename.jpg"
        for side in ("base", "copy"):
            folder = os.path.join(os.fsencode(str(getattr(self.sb, side))), b"odd")
            os.makedirs(folder)
            with open(os.path.join(folder, name), "wb") as f:
                f.write(b"ODD")
        self.assertEqual(self.sb.find().returncode, 0)
        r = self.sb.delete_real()
        self.assertEqual(r.returncode, 0, r.output)
        moved = os.listdir(os.path.join(os.fsencode(str(self.sb.quarantine)), b"odd"))
        self.assertEqual(moved, [name])
        self.assertTrue(os.path.exists(os.path.join(os.fsencode(str(self.sb.base)), b"odd", name)))


class ValidationTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.sb.build_basic()
        self.sb.config(exclude=None)

    def test_nested_and_identical_folders_are_refused(self):
        self.sb.write("base/sub/f.jpg", b"F")
        for value in (self.sb.base / "sub", self.sb.base, self.sb.data):
            r = self.sb.find("--folder-copy", value)
            self.assertEqual(r.returncode, 1, (value, r.output))
            self.assertIn("separate folders", r.stderr)

    def test_placeholder_and_missing_folders_are_refused(self):
        r = self.sb.find("--folder-base", "/path/to/folder_base")
        self.assertEqual(r.returncode, 1)
        self.assertIn("placeholder", r.stderr)
        r = self.sb.find("--folder-base", self.sb.root / "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not an existing folder", r.stderr)

    def test_invalid_option_values_are_refused(self):
        self.sb.config(options=["record = nobody"], exclude=None)
        self.assertIn("record must be", self.sb.find().stderr)
        self.sb.config(options=["match_by = guess"], exclude=None)
        self.assertIn("match_by must be", self.sb.find().stderr)
        self.sb.config(options=["all_files = maybe"], exclude=None)
        self.assertIn("must be true/false", self.sb.find().stderr)

    def test_missing_default_config_gives_a_hint(self):
        self.sb.config_path.unlink()
        r = self.sb.find()
        self.assertEqual(r.returncode, 1)
        self.assertIn("config.example.ini", r.stderr)

    def test_explicit_missing_config_is_an_error(self):
        r = self.sb.find("--config", self.sb.root / "nope.ini")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found", r.stderr)

    def test_command_line_overrides_config(self):
        other = self.sb.root / "other.csv"
        r = self.sb.find("-o", other)
        self.assertEqual(r.returncode, 0, r.output)
        self.assertTrue(other.exists())
        self.assertFalse(self.sb.matches.exists())

    def test_unwritable_output_gives_clear_error(self):
        r = self.sb.find("-o", self.sb.root / "no_such_dir" / "x.csv")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Could not write", r.stderr)

    def test_version_is_reported_by_both_scripts(self):
        for script in ("find_matches.py", "delete_matches.py"):
            r = self.sb.run(script, "--version")
            self.assertEqual(r.returncode, 0)
            self.assertRegex(r.stdout, r"\d+\.\d+\.\d+")

    def test_ctrl_c_exits_cleanly(self):
        patch = mock.patch.object(hashlib, "sha256", side_effect=KeyboardInterrupt)
        r = self.sb.run_inprocess("find_matches.py", patches=[patch])
        self.assertEqual(r.returncode, 130)
        self.assertIn("Interrupted", r.stderr)


if __name__ == "__main__":
    unittest.main()
