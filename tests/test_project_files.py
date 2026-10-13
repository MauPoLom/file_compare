"""Consistency checks for the repository itself (versions, imports, documentation, example config)."""
import ast
import configparser
import re
import unittest

try:
    from helpers import REPO, SCRIPTS, SandboxTestCase
except ImportError:  # started as a package from the repository root
    from .helpers import REPO, SCRIPTS, SandboxTestCase

ALLOWED_IMPORTS = {"__future__", "argparse", "configparser", "csv", "datetime", "hashlib", "os",
                   "pathlib", "shutil", "sys"}

EXPECTED_KEYS = {
    "folders": {"folder_base", "folder_copy", "exclude_folders"},
    "options": {"output", "export_not_selected", "not_selected_output", "not_selected_scope", "record",
                "match_by", "case_insensitive_names", "all_files"},
    "delete": {"quarantine_folder", "log_file", "remove_empty_folders", "permanent_delete"},
}


def read(name):
    return (REPO / name).read_text(encoding="utf-8")


class RepositoryTests(unittest.TestCase):
    def test_both_scripts_have_the_same_version_as_the_readme(self):
        versions = {name: re.search(r'__version__ = "(\d+\.\d+\.\d+)"', read(name)).group(1) for name in SCRIPTS}
        self.assertEqual(len(set(versions.values())), 1, versions)
        readme = re.search(r"\*\*Version:\*\* (\d+\.\d+\.\d+)", read("README.md")).group(1)
        self.assertEqual(readme, next(iter(versions.values())))
        self.assertIn("| %s |" % readme, read("README.md"))  # the changelog has a row for this version

    def test_scripts_and_tests_are_valid_python_3_8_syntax(self):
        files = list(SCRIPTS) + sorted(p.relative_to(REPO).as_posix() for p in (REPO / "tests").glob("*.py"))
        for name in files:
            ast.parse(read(name), filename=name, feature_version=(3, 8))

    def test_scripts_only_use_the_standard_library_modules_they_need(self):
        for name in SCRIPTS:
            imported = set()
            for node in ast.walk(ast.parse(read(name))):
                if isinstance(node, ast.Import):
                    imported |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module.split(".")[0])
            self.assertLessEqual(imported, ALLOWED_IMPORTS, name)

    def test_example_config_has_exactly_the_documented_settings(self):
        cfg = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None)
        cfg.read_string(read("config.example.ini"))
        self.assertEqual({s: set(cfg[s]) for s in cfg.sections()}, EXPECTED_KEYS)
        self.assertEqual(cfg.get("options", "not_selected_scope"), "folder_copy")
        self.assertEqual(cfg.get("folders", "exclude_folders"), "")  # only commented-out examples

    def test_every_setting_is_documented_in_the_readme(self):
        readme = read("README.md")
        for keys in EXPECTED_KEYS.values():
            for key in keys:
                self.assertIn("`%s`" % key, readme, key)

    def test_every_link_inside_the_readme_points_to_a_heading(self):
        readme = read("README.md")

        def slug(heading):  # the way GitHub builds anchors
            heading = re.sub(r"[^\w\- ]", "", heading.strip().lower())
            return heading.replace(" ", "-")

        anchors = {slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", readme, re.M)}
        links = set(re.findall(r"\]\(#([^)]+)\)", readme))
        self.assertTrue(links)
        self.assertEqual(sorted(links - anchors), [])

    def test_gitignore_keeps_personal_and_generated_files_out(self):
        lines = set(read(".gitignore").split())
        for entry in ("config.ini", "matches*.csv", "not_selected*.csv", "deleted_log*.csv", "quarantine/"):
            self.assertIn(entry, lines)

    def test_license_and_readme_have_no_name_placeholder(self):
        self.assertIn("MIT License", read("LICENSE"))
        for name in ("LICENSE", "README.md"):
            self.assertNotIn("[YOUR FULL NAME]", read(name))


class ExampleConfigWorks(SandboxTestCase):
    def test_example_config_runs_end_to_end(self):
        self.sb.build_basic()
        text = read("config.example.ini")
        text = text.replace("/path/to/folder_base", str(self.sb.base)).replace("/path/to/folder_copy", str(self.sb.copy))
        self.sb.config_path.write_text(text, encoding="utf-8")
        r = self.sb.find()
        self.assertEqual(r.returncode, 0, r.output)
        self.assertTrue((self.sb.root / "matches.csv").exists())
        self.assertTrue((self.sb.root / "not_selected.csv").exists())
        self.assertEqual({row["folder"] for row in self.sb.not_selected_rows()}, {"folder_copy"})


if __name__ == "__main__":
    unittest.main()
