"""Tests for the not_selected.csv export of find_matches.py."""
import unittest

try:
    from helpers import HAVE_SYMLINKS, SandboxTestCase, read_csv
except ImportError:  # started as a package from the repository root
    from .helpers import HAVE_SYMLINKS, SandboxTestCase, read_csv


class ReasonTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.sb.build_basic()

    def expected_name_mode(self):
        links = self.sb.links
        expected = {
            ("folder_base", "base/a.jpg"): "kept_identical_to_selected",
            ("folder_base", "base/empty.jpg"): "kept_identical_to_selected",
            ("folder_base", "base/d.jpg"): "same_physical_file" if links["sym"] else "no_match",
            ("folder_base", "base/only_base.jpg"): "no_match",
            ("folder_base", "base/samename.png"): "same_name_different_content",
            ("folder_copy", "copy/lnk/d_renamed.jpg"): "no_match",
            ("folder_copy", "copy/samename.png"): "same_name_different_content",
            ("folder_copy", "copy/only_copy.png"): "no_match",
        }
        if links["hard"]:
            expected[("folder_copy", "copy/hl/a.jpg")] = "same_physical_file"
        if links["sym"]:
            expected[("folder_copy", "copy/lnk/d.jpg")] = "same_physical_file"
        if links["broken"]:
            expected[("folder_copy", "copy/broken.jpg")] = "unreadable"
        return expected

    def test_reasons_in_name_and_checksum_mode(self):
        self.sb.config(options=["not_selected_scope = both"], exclude=None)
        self.assertEqual(self.sb.find().returncode, 0)
        self.assertEqual(self.sb.reasons(), self.expected_name_mode())

    def test_reasons_in_checksum_mode(self):
        self.sb.config(options=["match_by = checksum", "not_selected_scope = both"], exclude=None)
        self.sb.find()
        reasons = self.sb.reasons()
        self.assertEqual(reasons[("folder_base", "base/empty.jpg")], "empty_file_ignored")
        self.assertEqual(reasons[("folder_copy", "copy/empty.jpg")], "empty_file_ignored")
        self.assertEqual(reasons[("folder_base", "base/samename.png")], "no_match")
        self.assertEqual(reasons[("folder_copy", "copy/samename.png")], "no_match")
        self.assertEqual(reasons[("folder_base", "base/d.jpg")], "kept_identical_to_selected")

    def test_reasons_when_the_base_files_are_selected(self):
        self.sb.config(options=["record = folder_base", "not_selected_scope = both"], exclude=None)
        self.sb.find()
        reasons = self.sb.reasons()
        self.assertEqual(reasons[("folder_copy", "copy/other/a.jpg")], "kept_identical_to_selected")
        self.assertEqual(reasons[("folder_copy", "copy/other/deep/A.JPG")], "kept_identical_to_selected")
        self.assertNotIn(("folder_base", "base/a.jpg"), reasons)  # selected, so not in this export

    @unittest.skipUnless(HAVE_SYMLINKS, "symbolic links not available on this system")
    def test_unreadable_file_has_blank_size_and_checksum(self):
        self.sb.config(exclude=None)
        r = self.sb.find()
        self.assertIn("could not be read", r.stderr)
        row = [x for x in self.sb.not_selected_rows() if x["filename"] == "broken.jpg"][0]
        self.assertEqual((row["reason"], row["size_bytes"], row["checksum"]), ("unreadable", "", ""))

    def test_size_is_always_filled_and_checksum_only_when_calculated(self):
        self.sb.config(options=["not_selected_scope = both"], exclude=None)
        self.sb.find()
        rows = {self.sb.rel(r["path_filename"]): r for r in self.sb.not_selected_rows()}
        self.assertEqual(rows["base/only_base.jpg"]["size_bytes"], "2")
        self.assertEqual(rows["base/only_base.jpg"]["checksum"], "")      # never hashed: no candidate
        self.assertEqual(len(rows["base/a.jpg"]["checksum"]), 64)          # hashed during matching

    def test_every_scanned_file_is_in_exactly_one_csv_with_scope_both(self):
        self.sb.config(options=["not_selected_scope = both"], exclude=None)
        self.sb.find()
        listed = [r for r in self.sb.not_selected_rows() if r["size_bytes"] != ""]
        self.assertEqual(len(self.sb.selected()) + len(listed), self.sb.base_scanned + self.sb.copy_scanned())
        self.assertFalse(self.sb.selected() & {self.sb.rel(r["path_filename"]) for r in listed})


class ScopeTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.sb.build_basic()

    def folders(self):
        return {r["folder"] for r in self.sb.not_selected_rows()}

    def signature(self, rows):
        return sorted((r["folder"], r["path_filename"], r["reason"]) for r in rows)

    def test_default_is_folder_copy_only(self):
        self.sb.config(exclude=None)  # setting absent
        r = self.sb.find()
        self.assertIn("file(s) of folder_copy not selected for deletion written to", r.stdout)
        default_rows = self.sb.not_selected_rows()
        self.assertEqual(self.folders(), {"folder_copy"})
        self.assertFalse([x for x in default_rows if self.sb.rel(x["path_filename"]).startswith("base/")])
        self.sb.config(options=["not_selected_scope = both"], exclude=None)
        r = self.sb.find()
        self.assertIn("file(s) of both folders not selected for deletion written to", r.stdout)
        both_rows = self.sb.not_selected_rows()
        self.assertEqual(self.folders(), {"folder_base", "folder_copy"})
        self.assertEqual(self.signature(default_rows),
                         self.signature([x for x in both_rows if x["folder"] == "folder_copy"]))

    def test_default_scope_covers_every_scanned_copy_file(self):
        self.sb.config(exclude=None)
        self.sb.find()
        listed = [r for r in self.sb.not_selected_rows() if r["size_bytes"] != ""]
        self.assertEqual(len(self.sb.selected()) + len(listed), self.sb.copy_scanned())

    def test_kept_identical_does_not_occur_in_the_default_export(self):
        self.sb.config(exclude=None)
        self.sb.find()
        self.assertNotIn("kept_identical_to_selected", {r["reason"] for r in self.sb.not_selected_rows()})

    def test_record_folder_base_with_default_scope_lists_the_copy_files(self):
        self.sb.config(options=["record = folder_base"], exclude=None)
        self.sb.find()
        reasons = self.sb.reasons()
        self.assertEqual(self.folders(), {"folder_copy"})
        self.assertEqual(reasons[("folder_copy", "copy/other/a.jpg")], "kept_identical_to_selected")

    def test_command_line_overrides_the_config_in_both_directions(self):
        self.sb.config(options=["not_selected_scope = both"], exclude=None)
        self.sb.find("--not-selected-scope", "folder_copy")
        self.assertEqual(self.folders(), {"folder_copy"})
        self.sb.config(exclude=None)
        self.sb.find("--not-selected-scope", "both")
        self.assertEqual(self.folders(), {"folder_base", "folder_copy"})

    def test_invalid_scope_is_refused(self):
        self.sb.config(options=["not_selected_scope = folder_base"], exclude=None)
        r = self.sb.find()
        self.assertEqual(r.returncode, 1)
        self.assertIn("folder_copy, both", r.stderr)
        self.sb.config(exclude=None)
        self.assertEqual(self.sb.find("--not-selected-scope", "nope").returncode, 2)

    def test_scope_is_irrelevant_when_the_export_is_off(self):
        self.sb.config(options=["not_selected_scope = both", "export_not_selected = false"], exclude=None)
        self.sb.find()
        self.assertFalse(self.sb.not_selected.exists())


class ExportSwitchTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.sb.build_basic()

    def test_export_can_be_switched_off_in_config_and_on_the_command_line(self):
        self.sb.config(options=["export_not_selected = false"], exclude=None)
        r = self.sb.find()
        self.assertFalse(self.sb.not_selected.exists())
        self.assertNotIn("not selected for deletion", r.stdout)
        self.sb.config(exclude=None)
        self.sb.find("--no-export-not-selected")
        self.assertFalse(self.sb.not_selected.exists())
        self.sb.find()
        self.assertTrue(self.sb.not_selected.exists())

    def test_custom_output_path(self):
        self.sb.config(exclude=None)
        custom = self.sb.root / "custom.csv"
        self.sb.find("--not-selected-output", custom)
        self.assertTrue(custom.exists())
        self.assertFalse(self.sb.not_selected.exists())

    def test_header_of_the_export(self):
        self.sb.config(exclude=None)
        self.sb.find()
        self.assertEqual(list(read_csv(self.sb.not_selected)[0].keys()),
                         ["folder", "path", "filename", "path_filename", "size_bytes", "checksum", "reason"])

    def test_same_file_as_output_is_refused(self):
        self.sb.config(exclude=None)
        r = self.sb.find("--not-selected-output", self.sb.matches)
        self.assertEqual(r.returncode, 1)
        self.assertIn("two different files", r.stderr)

    def test_unwritable_export_path_gives_clear_error_after_matches_were_written(self):
        self.sb.config(exclude=None)
        r = self.sb.find("--not-selected-output", self.sb.root / "no_such_dir" / "x.csv")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Could not write", r.stderr)
        self.assertTrue(self.sb.matches.exists())


if __name__ == "__main__":
    unittest.main()
