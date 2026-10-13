"""Tests for the exclude_folders feature of find_matches.py."""
import unittest

try:
    from helpers import SandboxTestCase
except ImportError:  # started as a package from the repository root
    from .helpers import SandboxTestCase

EXCLUDED_NAMES = {"@eaDir", "Private", "Thumbs", "thumbs"}


class ExclusionTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.sb.build_basic()
        self.sb.add_excluded_dirs()

    def default_entries(self):
        return ["@eaDir", "thumbs", str(self.sb.base / "Private"), str(self.sb.copy / "Private")]

    def test_names_and_absolute_paths_are_skipped_in_both_folders(self):
        self.sb.config(options=["not_selected_scope = both"], exclude=self.default_entries())
        r = self.sb.find()
        self.assertEqual(r.returncode, 0, r.output)
        self.assertEqual(self.sb.selected(), {"copy/other/a.jpg", "copy/other/deep/A.JPG", "copy/empty.jpg"})
        everything = set(self.sb.selected()) | {rel for _, rel in self.sb.reasons()}
        for rel in everything:
            self.assertFalse(EXCLUDED_NAMES & set(rel.split("/")), rel)
        self.assertIn("excluded    : @eaDir (2 folder(s) skipped)", r.stdout)
        self.assertIn("excluded    : thumbs (2 folder(s) skipped)", r.stdout)  # Thumbs and thumbs
        self.assertEqual(r.stdout.count("(1 folder(s) skipped)"), 2)  # the two absolute paths

    def test_without_exclusions_the_same_folders_are_scanned(self):
        self.sb.config(exclude=None)
        self.sb.find()
        self.assertIn("copy/@eaDir/a.jpg", self.sb.selected())
        self.assertIn("copy/Private/secret.jpg", self.sb.selected())

    def test_folder_name_matching_follows_case_insensitive_names_setting(self):
        self.sb.config(options=["case_insensitive_names = false"], exclude=["thumbs"])
        r = self.sb.find()
        self.assertIn("excluded    : thumbs (1 folder(s) skipped)", r.stdout)

    def test_absolute_path_skips_only_that_folder(self):
        self.sb.config(options=["not_selected_scope = both"], exclude=[str(self.sb.copy / "x" / "thumbs")])
        r = self.sb.find()
        self.assertIn("(1 folder(s) skipped)", r.stdout)
        listed = {rel for _, rel in self.sb.reasons()}
        self.assertNotIn("copy/x/thumbs/y.jpg", listed)
        self.assertIn("base/sub/Thumbs/x.jpg", listed)

    def test_everything_below_an_excluded_folder_is_skipped(self):
        self.sb.write("base/Private/inner/z.jpg", b"Z")
        self.sb.write("copy/Private/inner/z.jpg", b"Z")
        self.sb.config(options=["not_selected_scope = both"], exclude=["Private"])
        self.sb.find()
        everything = set(self.sb.selected()) | {rel for _, rel in self.sb.reasons()}
        self.assertFalse([p for p in everything if "Private" in p])

    def test_single_line_value_works(self):
        text = self.sb.config_path
        self.sb.config(exclude=None)
        text.write_text(text.read_text(encoding="utf-8").replace(
            "[folders]\n", "[folders]\nexclude_folders = @eaDir\n", 1), encoding="utf-8")
        r = self.sb.find()
        self.assertIn("excluded    : @eaDir (2 folder(s) skipped)", r.stdout)

    def test_command_line_list_replaces_the_config_list(self):
        self.sb.config(options=["not_selected_scope = both"], exclude=["@eaDir"])
        r = self.sb.find("--exclude", "Private")
        self.assertIn("excluded    : Private (2 folder(s) skipped)", r.stdout)
        self.assertNotIn("@eaDir", r.stdout)
        self.assertIn("copy/@eaDir/a.jpg", self.sb.selected())  # @eaDir is scanned again

    def test_no_list_empty_list_and_comment_only_list(self):
        for exclude in (None, [], ["# only a comment", "; another one"]):
            self.sb.config(exclude=exclude)
            r = self.sb.find()
            self.assertEqual(r.returncode, 0, (exclude, r.output))
            self.assertNotIn("excluded    :", r.stdout)

    def test_invalid_entries_are_refused(self):
        cases = {
            "sub/folder": "not valid",          # relative path with a separator
            "..": "not valid",
            str(self.sb.base): "whole scanned folder",
            str(self.sb.data): "whole scanned folder",  # contains both scanned folders
        }
        for entry, message in cases.items():
            self.sb.config(exclude=[entry])
            r = self.sb.find()
            self.assertEqual(r.returncode, 1, (entry, r.output))
            self.assertIn(message, r.stderr)

    def test_absolute_path_outside_both_folders_warns_and_is_ignored(self):
        self.sb.config(exclude=[str(self.sb.root / "elsewhere")])
        r = self.sb.find()
        self.assertEqual(r.returncode, 0, r.output)
        self.assertIn("is not inside folder_base or folder_copy", r.stderr)

    def test_entry_that_matches_nothing_warns(self):
        self.sb.config(exclude=["@eaDir", "Typo"])
        r = self.sb.find()
        self.assertEqual(r.returncode, 0, r.output)
        self.assertIn("'Typo' matched no folder", r.stderr)

    def test_unindented_list_gives_a_helpful_error(self):
        self.sb.config(exclude=None)
        self.sb.config_path.write_text(self.sb.config_path.read_text(encoding="utf-8").replace(
            "[folders]\n", "[folders]\nexclude_folders =\n@eaDir\nthumbs\n", 1), encoding="utf-8")
        r = self.sb.find()
        self.assertEqual(r.returncode, 1)
        self.assertIn("must be indented", r.stderr)

    def test_delete_never_touches_excluded_folders(self):
        self.sb.config(exclude=self.default_entries())
        self.assertEqual(self.sb.find().returncode, 0)
        r = self.sb.delete_real()
        self.assertEqual(r.returncode, 0, r.output)
        for rel in ("copy/@eaDir/a.jpg", "copy/Private/secret.jpg", "copy/x/thumbs/y.jpg",
                    "base/@eaDir/a.jpg", "base/Private/secret.jpg", "base/sub/Thumbs/x.jpg"):
            self.assertTrue(self.sb.exists(rel), rel)
        self.assertFalse(self.sb.exists("copy/other"))   # emptied by the move, so it is removed
        self.assertTrue(self.sb.exists("copy/@eaDir"))   # holds an excluded folder's files, so it stays
        self.assertTrue(self.sb.exists("copy/samename.png"))


if __name__ == "__main__":
    unittest.main()
