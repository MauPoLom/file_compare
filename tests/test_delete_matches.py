"""Tests for delete_matches.py."""
import csv
import os
import shutil
import unittest

try:
    from helpers import HAVE_SYMLINKS, LOG_FIELDS, SandboxTestCase, mock, read_csv
except ImportError:  # started as a package from the repository root
    from .helpers import HAVE_SYMLINKS, LOG_FIELDS, SandboxTestCase, mock, read_csv


class TwoFileTests(SandboxTestCase):
    """base: a.jpg, b.jpg   copy: sub/a.jpg, sub/deep/b.jpg (both are matches)."""

    def setUp(self):
        super().setUp()
        self.sb.build_two()
        self.sb.config(exclude=None)
        self.assertEqual(self.sb.find().returncode, 0)

    def log_rows(self):
        return read_csv(self.sb.log)

    def test_dry_run_changes_nothing_and_writes_no_log(self):
        r = self.sb.delete()
        self.assertEqual(r.returncode, 0, r.output)
        self.assertEqual(r.stdout.count("Would move: %s" % self.sb.copy), 2)  # one line per file
        self.assertIn("Would move: 2 | Skipped: 0 | Errors: 0", r.stdout)
        self.assertIn("Dry run only", r.stdout)
        self.assertTrue(self.sb.exists("copy/sub/a.jpg") and self.sb.exists("copy/sub/deep/b.jpg"))
        self.assertFalse(self.sb.log.exists())
        self.assertFalse(self.sb.quarantine.exists())

    def test_real_run_moves_logs_and_removes_emptied_folders(self):
        r = self.sb.delete_real()
        self.assertEqual(r.returncode, 0, r.output)
        self.assertEqual(self.sb.quarantined(), {"sub/a.jpg", "sub/deep/b.jpg"})
        self.assertFalse(self.sb.exists("copy/sub"))            # both files left, folders emptied
        self.assertTrue(self.sb.copy.is_dir())                  # the top-level folder itself stays
        self.assertTrue(self.sb.exists("base/a.jpg") and self.sb.exists("base/b.jpg"))
        with open(str(self.sb.log), newline="", encoding="utf-8") as f:
            self.assertEqual(next(csv.reader(f)), LOG_FIELDS)
        rows = self.log_rows()
        self.assertEqual(sorted((x["action"], x["status"]) for x in rows),
                         [("MOVE", "OK"), ("MOVE", "OK"), ("RMDIR", "OK"), ("RMDIR", "OK")])
        self.assertIn("Moved: 2 | Skipped: 0 | Errors: 0", r.stdout)

    def test_folder_that_still_has_content_is_kept(self):
        self.sb.write("copy/sub/keep.txt", b"K")
        self.sb.delete_real()
        self.assertTrue(self.sb.exists("copy/sub/keep.txt"))
        self.assertFalse(self.sb.exists("copy/sub/deep"))

    def test_keep_empty_folders_option(self):
        self.sb.delete_real("--keep-empty-folders")
        self.assertTrue(self.sb.exists("copy/sub/deep"))
        self.assertEqual(self.sb.quarantined(), {"sub/a.jpg", "sub/deep/b.jpg"})

    def test_remove_empty_folders_can_be_turned_off_in_the_config(self):
        self.sb.config(exclude=None, delete=["remove_empty_folders = false"])
        self.sb.delete_real()
        self.assertTrue(self.sb.exists("copy/sub/deep"))

    def test_permanent_delete(self):
        dry = self.sb.delete("--permanent")
        self.assertIn("Would delete:", dry.stdout)
        r = self.sb.delete_real("--permanent")
        self.assertEqual(r.returncode, 0, r.output)
        self.assertFalse(self.sb.exists("copy/sub/a.jpg"))
        self.assertFalse(self.sb.quarantine.exists())
        self.assertEqual({x["action"] for x in self.log_rows()}, {"DELETE", "RMDIR"})

    def test_confirmation_prompt(self):
        r = self.sb.delete("--delete", input_text="no\n")
        self.assertIn("Aborted", r.stdout)
        self.assertTrue(self.sb.exists("copy/sub/a.jpg"))
        r = self.sb.delete("--delete", input_text="yes\n")
        self.assertEqual(r.returncode, 0, r.output)
        self.assertFalse(self.sb.exists("copy/sub/a.jpg"))

    def test_without_terminal_and_without_yes_nothing_happens(self):
        r = self.sb.delete("--delete")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--yes", r.stderr)
        self.assertTrue(self.sb.exists("copy/sub/a.jpg"))

    def test_quarantine_may_not_overlap_the_scanned_folders(self):
        for place in (self.sb.copy / "q", self.sb.base / "q", self.sb.data):
            r = self.sb.delete_real("--quarantine", place)
            self.assertEqual(r.returncode, 1, (place, r.output))
            self.assertIn("overlaps", r.stderr)
            self.assertTrue(self.sb.exists("copy/sub/a.jpg"))
            self.assertFalse(self.sb.log.exists())

    def test_log_that_cannot_be_written_stops_before_any_change(self):
        folder_as_log = self.sb.root / "logdir"
        folder_as_log.mkdir()
        r = self.sb.delete_real("--log", folder_as_log)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Nothing was changed", r.stderr)
        self.assertTrue(self.sb.exists("copy/sub/a.jpg") and self.sb.exists("copy/sub/deep/b.jpg"))

    def test_quarantine_that_cannot_be_created_reports_errors_and_keeps_originals(self):
        blocker = self.sb.root / "blocker"
        blocker.write_text("i am a file")
        r = self.sb.delete_real("--quarantine", blocker / "q")
        self.assertEqual(r.returncode, 1, r.output)
        self.assertIn("Errors: 2", r.stdout)
        self.assertTrue(self.sb.exists("copy/sub/a.jpg") and self.sb.exists("copy/sub/deep/b.jpg"))
        self.assertEqual({x["status"] for x in self.log_rows()}, {"ERROR"})

    def test_failed_move_leaves_no_partial_file_and_keeps_the_original(self):
        def failing_move(src, dst):
            with open(dst, "wb") as f:
                f.write(b"PARTIAL")
            raise OSError("disk full (simulated)")

        r = self.sb.run_inprocess("delete_matches.py", "--delete", "--yes",
                                  patches=[mock.patch.object(shutil, "move", failing_move)])
        self.assertEqual(r.returncode, 1, r.output)
        self.assertIn("ERROR on", r.stdout)
        self.assertTrue(self.sb.exists("copy/sub/a.jpg") and self.sb.exists("copy/sub/deep/b.jpg"))
        self.assertEqual(self.sb.quarantined(), set())

    def test_ctrl_c_stops_cleanly_and_the_log_keeps_what_was_done(self):
        real_move, calls = shutil.move, {"n": 0}

        def interrupting_move(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt
            return real_move(src, dst)

        r = self.sb.run_inprocess("delete_matches.py", "--delete", "--yes",
                                  patches=[mock.patch.object(shutil, "move", interrupting_move)])
        self.assertEqual(r.returncode, 130, r.output)
        self.assertIn("Interrupted", r.stderr)
        self.assertIn("Moved: 1", r.stdout)
        self.assertEqual(len(self.sb.quarantined()), 1)
        self.assertEqual(sum(1 for p in ("copy/sub/a.jpg", "copy/sub/deep/b.jpg") if self.sb.exists(p)), 1)
        moves = [x for x in self.log_rows() if x["action"] == "MOVE"]
        self.assertEqual([(x["status"]) for x in moves], ["OK"])

    def test_custom_input_file(self):
        custom = self.sb.root / "other_name.csv"
        shutil.copy2(str(self.sb.matches), str(custom))
        self.sb.matches.unlink()
        r = self.sb.delete_real("--input", custom)
        self.assertEqual(r.returncode, 0, r.output)
        self.assertEqual(len(self.sb.quarantined()), 2)


class SafetyChecks(SandboxTestCase):
    """One match (copy/sub/a.jpg <-> base/a.jpg); every test breaks one safety condition."""

    def setUp(self):
        super().setUp()
        self.sb.build_single()
        self.sb.config(exclude=None)
        self.assertEqual(self.sb.find().returncode, 0)
        self.row = read_csv(self.sb.matches)[0]
        self.target = self.sb.copy / "sub" / "a.jpg"
        self.other = self.sb.base / "a.jpg"

    def assert_skipped(self, reason):
        r = self.sb.delete_real()
        self.assertEqual(r.returncode, 0, r.output)
        self.assertIn("SKIP (%s)" % reason, r.stdout)
        self.assertIn("Skipped: 1", r.stdout)
        self.assertEqual(self.sb.quarantined(), set())
        return r

    def rewrite_csv(self, change):
        rows = read_csv(self.sb.matches)
        change(rows[0])
        with open(str(self.sb.matches), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    def test_other_copy_changed(self):
        self.other.write_bytes(b"CHANGED")
        self.assert_skipped("other copy has changed")
        self.assertTrue(self.target.exists())

    def test_file_itself_changed(self):
        self.target.write_bytes(b"CHANGED")
        self.assert_skipped("checksum changed")
        self.assertTrue(self.target.exists())

    def test_other_copy_missing(self):
        self.other.unlink()
        self.assert_skipped("other copy missing - would lose last copy")
        self.assertTrue(self.target.exists())

    def test_file_already_gone(self):
        self.target.unlink()
        self.assert_skipped("missing")

    def test_incomplete_row(self):
        self.rewrite_csv(lambda row: row.update(other_copy=""))
        self.assert_skipped("incomplete row in CSV")
        self.assertTrue(self.target.exists())

    def test_file_outside_its_recorded_folder(self):
        self.rewrite_csv(lambda row: row.update(path_filename=str(self.other), other_copy=str(self.target)))
        self.assert_skipped("not inside its recorded folder")
        self.assertTrue(self.other.exists())

    @unittest.skipUnless(HAVE_SYMLINKS, "symbolic links not available on this system")
    def test_file_replaced_by_a_link_to_the_other_copy(self):
        self.target.unlink()
        os.symlink(str(self.other), str(self.target))
        self.assert_skipped("other copy is the same physical file")
        self.assertTrue(self.other.exists())

    def test_log_records_skipped_rows_with_the_reason(self):
        self.other.write_bytes(b"CHANGED")
        self.sb.delete_real()
        rows = read_csv(self.sb.log)
        self.assertEqual([(x["status"], x["reason"]) for x in rows], [("SKIPPED", "other copy has changed")])


class CsvValidation(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.sb.build_single()
        self.sb.config(exclude=None)

    def test_csv_from_an_older_version_is_rejected(self):
        self.sb.matches.write_text(
            "path,filename,path_filename,checksum,other_copy\n"
            "%s,a.jpg,%s,x,%s\n" % (self.sb.copy / "sub", self.sb.copy / "sub" / "a.jpg", self.sb.base / "a.jpg"),
            encoding="utf-8")
        r = self.sb.delete_real()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a valid matches file", r.stderr)
        self.assertTrue(self.sb.exists("copy/sub/a.jpg"))

    def test_other_files_are_rejected(self):
        self.sb.matches.write_text("hello\n", encoding="utf-8")
        r = self.sb.delete_real()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(self.sb.exists("copy/sub/a.jpg"))

    def test_missing_csv(self):
        r = self.sb.delete()
        self.assertEqual(r.returncode, 1)
        self.assertIn("CSV not found", r.stderr)

    def test_empty_csv_means_nothing_to_do(self):
        self.assertEqual(self.sb.find().returncode, 0)  # a normal run creates the header line
        self.sb.matches.write_text(self.sb.matches.read_text(encoding="utf-8").splitlines()[0] + "\n",
                                   encoding="utf-8")
        r = self.sb.delete_real()
        self.assertEqual(r.returncode, 0)
        self.assertIn("nothing to do", r.stdout)


class NameCollisionTests(SandboxTestCase):
    def test_second_file_with_the_same_name_gets_a_number_and_the_log_header_is_written_once(self):
        self.sb.build_single()
        self.sb.config(exclude=None)
        for _ in range(2):
            self.sb.write("copy/sub/a.jpg", b"AAA")
            self.assertEqual(self.sb.find().returncode, 0)
            self.assertEqual(self.sb.delete_real().returncode, 0)
        self.assertEqual(self.sb.quarantined(), {"sub/a.jpg", "sub/a (1).jpg"})
        text = self.sb.log.read_text(encoding="utf-8")
        self.assertEqual(text.count("timestamp,action"), 1)


if __name__ == "__main__":
    unittest.main()
