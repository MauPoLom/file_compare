# Duplicate Image Finder

Two small Python scripts that find images existing in **both** of two folders and then move (or delete) the duplicates from one of them.

- `find_matches.py` compares two folders recursively and writes the matches to `matches.csv`. It can skip chosen folders in both scanned folders, and it also exports the files of `folder_copy` that were **not** selected for deletion to `not_selected.csv` (optionally the files of both folders).
- `delete_matches.py` reads `matches.csv` and moves the listed files to a quarantine folder (or deletes them permanently, if you explicitly choose so).

**Version:** 1.2.0 | **Author:** MauPoLom | **License:** [MIT](LICENSE) | **Python:** 3.8 or newer, standard library only (no dependencies)

> ## ⚠️ Read this first
> `delete_matches.py` **moves or deletes files on your computer.** Software can contain bugs, and settings can be misconfigured.
> **Make a backup of your data before using this software**, test it on a small copy first, and always do a dry run before a real run.
> **Do not point the scripts at the inside of a managed photo library** (for example an Apple Photos library or the folders of a Lightroom catalog) or at cloud-synced "online-only" files. See [Risks](#risks).
> You use this software **entirely at your own risk**. See [Risks](#risks) and [Disclaimer](#disclaimer-no-warranty-no-liability).

---

## Table of contents
1. [How it works](#how-it-works)
2. [Requirements and installation](#requirements-and-installation)
3. [Quick start](#quick-start)
4. [Configuration reference](#configuration-reference)
5. [Excluding folders](#excluding-folders)
6. [Command-line options](#command-line-options)
7. [Output files](#output-files)
8. [Built-in safety features](#built-in-safety-features)
9. [Recommended workflow](#recommended-workflow)
10. [Running the tests](#running-the-tests)
11. [Limitations](#limitations)
12. [Risks](#risks)
13. [Privacy statement](#privacy-statement)
14. [Disclaimer (no warranty, no liability)](#disclaimer-no-warranty-no-liability)
15. [License](#license)
16. [Versioning and changelog](#versioning-and-changelog)
17. [Support and contributions](#support-and-contributions)
18. [Credits](#credits)

---

## How it works

**Step 1 - `find_matches.py`**

1. Scans `folder_base` (the reference/originals) and `folder_copy` recursively. By default only image files are considered (`.jpg .jpeg .jfif .png .gif .bmp .tif .tiff .webp .avif .heic .heif .svg .ico .raw .cr2 .nef .arw .dng .orf .rw2 .raf .pef .srw`); you can switch to all file types. Symbolic links to folders are not followed.
2. Folders listed in `exclude_folders` are skipped in **both** scanned folders (see [Excluding folders](#excluding-folders)).
3. Two files are a match when they are **byte-identical** (same SHA-256 checksum) and, depending on `match_by`, also have the same filename.
4. To stay fast, files of different size are never hashed against each other, and checksums are only calculated when the size (and, in `name_and_checksum` mode, the name) already matches.
5. A symbolic link or hard link that points to the very same file as its counterpart is not reported as a duplicate. In `checksum` mode, empty (0-byte) files are ignored.
6. Writes one row to `matches.csv` per matching file in `folder_copy` (or per matching file in `folder_base` if `record = folder_base`; each file is listed only once).
7. Writes the scanned files that were not selected, with the reason why, to `not_selected.csv`: by default only those of `folder_copy`, optionally those of both folders (`not_selected_scope`). This export can be switched off.

**Step 2 - `delete_matches.py`**

1. Reads `matches.csv` and, for every row, re-verifies the [safety conditions](#built-in-safety-features) (the file and its other copy still exist and still have the recorded checksum).
2. By default performs a **dry run** that only prints what would happen.
3. With `--delete` it **moves** the files into a quarantine folder (keeping the sub-folder structure), logs every action, and optionally removes folders that became empty.

> Only byte-identical files are detected. Resized, re-compressed or edited versions of an image are *not* duplicates in this sense.

## Requirements and installation

- Python 3.8 or newer. No third-party packages.
- Developed and tested on Python 3.12 on Linux, using small sets of sample files. The author also ran it on macOS 14.5 (Sonoma) with Python 3.13.2, where it worked as expected (a manual run, not the automated checks used on Linux). The source was additionally checked to be valid Python 3.8 syntax, but it has **not** been run on Python 3.8-3.11. It is expected to work on Windows but has **not** been tested there.

```bash
git clone https://github.com/<your-account>/<your-repo>.git
cd <your-repo>
```

No installation step is needed; run the scripts directly with `python` (on Linux/macOS usually `python3`).

## Quick start

1. Copy the example configuration and edit it:

   ```bash
   cp config.example.ini config.ini        # Windows: copy config.example.ini config.ini
   ```

   Set at least the two folders:

   ```ini
   [folders]
   folder_base = D:\Photos\Archive
   folder_copy = E:\Backup\Photos
   ```

   Also set `quarantine_folder` (section `[delete]`) to a folder **outside** both of these, and optionally list [folders to exclude](#excluding-folders).

2. Find the duplicates:

   ```bash
   python find_matches.py
   ```

3. Review the result with a dry run (nothing is changed):

   ```bash
   python delete_matches.py
   ```

4. Only when you are happy with the list, do it for real:

   ```bash
   python delete_matches.py --delete
   ```

   You are asked to type `yes` to confirm (skip with `--yes`). Files end up in the quarantine folder; review it and empty it yourself when you are sure.

> Run both scripts from the same working directory (or use absolute paths in `config.ini`): relative paths such as `matches.csv`, `quarantine` and `deleted_log.csv` are resolved from the folder you run the script *from*.

## Configuration reference

Both scripts read `config.ini` from the **same folder as the scripts**. Use `--config <file>` to point to another file. Your personal `config.ini` is listed in `.gitignore` so it is not committed by accident; `config.example.ini` is the template.

**File format rules**

- INI format: `[section]` headers and `key = value` lines.
- Lines starting with `#` or `;` are comments. Put comments on their **own line**, never behind a value.
- Do not use quotes around paths. Spaces in paths are fine.
- Windows (`C:\Users\me`) and Linux/macOS (`/home/me`) paths both work. Do not double backslashes.
- Relative paths are resolved from the folder you run the script *from*; absolute paths are safer.
- True/false values accept `true/false`, `yes/no`, `on/off`, `1/0`.
- A multi-line value (the `exclude_folders` list) has one entry per line, and those lines **must be indented**.

**Priority:** command-line argument > `config.ini` > built-in default.

### `[folders]` (required for `find_matches.py`)

| Setting | Default | Description |
|---|---|---|
| `folder_base` | - (required) | Reference folder (the originals). Not touched by default. |
| `folder_copy` | - (required) | Folder searched for duplicates of files in `folder_base`. By default the matches found here are moved away. |
| `exclude_folders` | (none) | Folders to skip in **both** scanned folders; one entry per line. See [Excluding folders](#excluding-folders). |

Both folders are searched recursively. They must be two separate folders: the script refuses identical folders or folders nested inside each other.

### `[options]`

| Setting | Default | Description |
|---|---|---|
| `output` | `matches.csv` | CSV written by `find_matches.py` and read by `delete_matches.py`. |
| `export_not_selected` | `true` | Also write a CSV with the scanned files that were **not** selected for deletion. |
| `not_selected_output` | `not_selected.csv` | Name (or path) of that CSV. Must differ from `output`. |
| `not_selected_scope` | `folder_copy` | Whose unselected files are exported: `folder_copy` (only the files of the copy folder) or `both` (also the files of `folder_base`, which can make the CSV much larger). |
| `record` | `folder_copy` | Whose copy of each match is listed in the CSV, i.e. which file `delete_matches.py` acts on: `folder_copy` or `folder_base`. **`folder_base` makes the scripts move your originals instead of the copies.** |
| `match_by` | `name_and_checksum` | `name_and_checksum`: same filename **and** same checksum. `checksum`: same checksum only, filenames ignored (also finds renamed duplicates, but see [Risks](#risks)). |
| `case_insensitive_names` | `true` | With `name_and_checksum`: treat `Photo.JPG` and `photo.jpg` as the same name. Also used when comparing excluded folder names. |
| `all_files` | `false` | Compare all file types instead of only images. |

### `[delete]` (used by `delete_matches.py`)

| Setting | Default | Description |
|---|---|---|
| `quarantine_folder` | `quarantine` | Where matched files are moved to. Must be **outside** both scanned folders and may not contain them (the script refuses otherwise). Name clashes get a ` (1)`, ` (2)` suffix. |
| `log_file` | `deleted_log.csv` | Every real action is appended here. Not written during a dry run. |
| `remove_empty_folders` | `true` | Remove sub-folders that became empty after the move (never the top-level folder itself; a folder containing anything, even a `Thumbs.db` or an excluded folder, is left alone). |
| `permanent_delete` | `false` | `true` deletes files for good instead of quarantining them. **Cannot be undone.** |

## Excluding folders

Use `exclude_folders` to keep folders out of the comparison. The list applies to **both** `folder_base` and `folder_copy`.

```ini
[folders]
folder_base = D:\Photos\Archive
folder_copy = E:\Backup\Photos
exclude_folders =
    @eaDir
    .thumbnails
    D:\Photos\Archive\Private
    E:\Backup\Photos\Work\Contracts
```

- **One entry per line, and the lines must be indented** (it is an INI multi-line value). A single entry may also be written on the same line: `exclude_folders = @eaDir`.
- **A plain folder name** (no `/` or `\`) skips every folder with that name, at any depth, in both scanned folders. Names are compared case-insensitively unless you set `case_insensitive_names = false`.
- **An absolute path** skips exactly that folder. It must lie inside `folder_base` or `folder_copy`; otherwise it is ignored with a warning. Use an absolute path when you want to exclude a folder in only one of the two scanned folders.
- **Everything below an excluded folder is skipped too.**
- **Not allowed:** relative paths with a separator (such as `Photos/2019`, because it is unclear what they are relative to), `.` and `..`, and any entry that equals or contains a scanned folder. These stop the script with a message.
- **Check the report.** The script prints how many folders each entry skipped. An entry that matched nothing produces a warning, which usually means a typo; a folder you meant to protect would then be scanned.
- `--exclude NAME_OR_PATH` (repeatable) on the command line **replaces** the list from `config.ini` for that run.
- **Libraries inside a scanned folder:** if a managed photo library sits inside a folder you scan, exclude it by name (for example `Photos Library.photoslibrary`); better still, never scan a managed library at all (see [Risks](#risks)).
- Files in excluded folders are not scanned, so they appear in neither `matches.csv` nor `not_selected.csv`, and `delete_matches.py` never touches them.

## Command-line options

Exit codes: `0` success; `1` refusal or error (invalid settings, unsafe folders, unwritable files, failed file operations); `2` invalid command-line arguments; `130` interrupted with Ctrl+C (`find_matches.py` may then leave incomplete output files; `delete_matches.py` keeps a log of what was already processed).

**`find_matches.py`**

| Option | Overrides |
|---|---|
| `-c`, `--config FILE` | use another config file |
| `--folder-base PATH` / `--folder-copy PATH` | `folder_base` / `folder_copy` |
| `--exclude NAME_OR_PATH` | `exclude_folders` (repeatable; replaces the config list) |
| `-o`, `--output FILE` | `output` |
| `--not-selected-output FILE` | `not_selected_output` |
| `--no-export-not-selected` | switches the not-selected export off |
| `--not-selected-scope {folder_copy,both}` | `not_selected_scope` |
| `--record {folder_base,folder_copy}` | `record` |
| `--match-by {name_and_checksum,checksum}` | `match_by` |
| `--case-sensitive` | forces case-sensitive name matching |
| `--all-files` | `all_files` |
| `--version` | prints the version |

**`delete_matches.py`**

| Option | Description |
|---|---|
| `-c`, `--config FILE` | use another config file |
| `-i`, `--input FILE` | CSV to read (default: `output` from the config) |
| `--delete` | actually act (**default is a dry run**) |
| `--yes` | skip the confirmation prompt (required when there is no interactive terminal) |
| `--quarantine PATH` | overrides `quarantine_folder` |
| `--log FILE` | overrides `log_file` |
| `--keep-empty-folders` | overrides `remove_empty_folders` |
| `--permanent` | overrides `permanent_delete` (delete for good) |
| `--version` | prints the version |

## Output files

**`matches.csv`** - the files selected for deletion

| Column | Meaning |
|---|---|
| `path` | folder of the listed file |
| `filename` | name of the listed file |
| `path_filename` | full path of the listed file |
| `checksum` | SHA-256 of the file |
| `other_copy` | full path of the identical file in the other folder |
| `root` | top-level scanned folder of the listed file |
| `other_root` | top-level scanned folder of the other copy |

`delete_matches.py` only accepts CSV files that contain all of these columns and skips rows in which a required value is empty.

**`not_selected.csv`** - the scanned files that were **not** selected for deletion. By default only files of `folder_copy` are listed; with `not_selected_scope = both` the files of `folder_base` are included as well. Rows are ordered by folder and path; files in excluded folders are not scanned and therefore not listed.

| Column | Meaning |
|---|---|
| `folder` | `folder_copy`, or `folder_base` (only with `not_selected_scope = both`) |
| `path`, `filename`, `path_filename` | location of the file |
| `size_bytes` | file size (empty if it could not be read) |
| `checksum` | SHA-256, only if it was calculated during matching (files without a same-size/same-name counterpart are never hashed, so this stays empty) |
| `reason` | why the file was not selected (see below) |

| `reason` | Meaning |
|---|---|
| `no_match` | no identical file exists in the other folder |
| `kept_identical_to_selected` | an identical file exists in the other folder and is listed in `matches.csv`; this one is the copy that stays. With the default `record = folder_copy` this only occurs for `folder_base` files (scope `both`); with `record = folder_base` it occurs for `folder_copy` files |
| `same_name_different_content` | (`name_and_checksum` mode) a file with the same name exists in the other folder, but its content differs |
| `same_physical_file` | a symbolic link or hard link to its counterpart; not a real duplicate |
| `empty_file_ignored` | (`checksum` mode) empty files are ignored |
| `unreadable` | the file could not be read (permissions, broken link, ...) and was not evaluated |

With the export switched on and `not_selected_scope = both`, every scanned file ends up in exactly one of the two CSVs (`matches.csv` or `not_selected.csv`); with the default scope this holds for every scanned file of `folder_copy` (scanned files of `folder_base` that are not selected are then in neither CSV). The export can be large on big libraries, especially with scope `both`; switch it off with `export_not_selected = false`. Files that `delete_matches.py` skips during a run (because they changed in the meantime) are recorded with status `SKIPPED` in the log.

**`deleted_log.csv`** (appended on every real run, timestamps in local time)

`timestamp, action (MOVE/DELETE/RMDIR), status (OK/SKIPPED/ERROR), source, destination, checksum, reason`

> All these files contain **full local file paths**. See the [Privacy statement](#privacy-statement) before sharing them.

## Built-in safety features

- Dry run is the default; `--delete` is required to change anything.
- Confirmation prompt before a real run (unless `--yes`).
- Files are moved to quarantine rather than deleted (unless you choose `permanent_delete`).
- For every listed file, **all** of these must be true, otherwise the file is skipped and the reason is shown (and logged during a real run):
  - the CSV row is complete;
  - the file lies inside its recorded folder;
  - the file still exists, and still has the checksum recorded in the CSV;
  - the other copy still exists, still has that same checksum, and is not the same physical file (symlink or hard link).
- Excluded folders are never scanned; a typo in an exclusion produces a warning.
- The quarantine folder may not be inside, or contain, a scanned folder.
- The log file is opened before anything is changed; if it cannot be written, nothing is touched.
- If a move fails halfway, the partial copy in the quarantine folder is removed and the original is left in place.
- Ctrl+C stops cleanly; everything processed up to that point is in the log.

These features reduce risk; they **cannot guarantee** that no wanted file is moved or that no data is lost. See [Risks](#risks).

## Recommended workflow

1. **Back up** both folders (or at least `folder_copy`) to a separate disk.
2. Point the scripts at **ordinary folders** (or at an export), **never at the inside of a managed photo library** and not at cloud-synced "online-only" files (see [Risks](#risks)).
3. Try the scripts on a **small test copy** of your data first.
4. Run `find_matches.py`, check the printed exclusion report, open `matches.csv`, and spot-check several rows.
5. Look through `not_selected.csv` (for example the `same_name_different_content` and `unreadable` rows) to confirm nothing important was missed or misjudged. Use `not_selected_scope = both` if you also want to review the files of `folder_base`.
6. Run `delete_matches.py` as a **dry run** and read the output.
7. Run with `--delete`, then inspect the quarantine folder and your applications (photo library, media server, etc.).
8. Only after verifying everything, empty the quarantine folder yourself.

## Running the tests

The repository contains an automated test suite in the `tests/` folder. It uses only Python's built-in `unittest`, so nothing has to be installed:

```bash
python -m unittest discover -s tests -v
```

(Use `python3` on Linux and macOS. A plain `python -m unittest` from the repository root works too.)

- **Safe to run.** Every test works in a temporary folder with its own copy of the scripts, so the tests never read your `config.ini` and never touch your own folders. The temporary folders are removed afterwards.
- **What is covered:** the matching modes, folder exclusions, the not-selected export and its scope, the safety checks of `delete_matches.py` (including simulated failures such as a full disk and Ctrl+C), the CSV formats, and consistency checks (versions, documentation, example config, standard-library-only imports).
- **Skipped automatically where the system cannot do something:** tests that need symbolic links or hard links, or file names that are not valid UTF-8, are skipped on systems that do not support them (for example symbolic links on Windows without Developer Mode). The output shows them as `skipped`; that is expected and not an error.
- **Status:** the suite passes on Linux with Python 3.12. It has not yet been run on other systems or Python versions; if a test fails on yours, please open an issue with the output (without personal paths).

## Limitations

- Detects byte-identical files only. Changing metadata (e.g. EXIF) changes the checksum, so such files are not matched.
- Does not look at image content, so visually similar images are not detected.
- Tested on small sample sets on Linux with Python 3.12 (plus one synthetic run with 40,000 small files) and run once by the author on macOS 14.5 with Python 3.13.2. The repository contains an automated test suite (see [Running the tests](#running-the-tests)), which has so far only been run on Linux with Python 3.12. Windows, network shares, cloud-synced folders (OneDrive, Dropbox, ...), very long paths and very large real-world libraries have not been specifically tested.
- Do not modify the scanned folders while the scripts are running.
- Moving files to a quarantine folder on another disk copies and then removes them, which can be slow and needs free space there.
- The CSV is a snapshot. Run `delete_matches.py` soon after `find_matches.py`; rows whose files changed in the meantime are skipped, but changes elsewhere are not detected.
- Exclusions are applied while scanning only; they are not stored in `matches.csv`.

## Risks

Using this software involves risks, including but not limited to:

- **Data loss.** Files can be moved or permanently deleted. A wrong folder, a wrong `record` value (which targets your originals), a misunderstood setting, or a bug can cause the wrong files to be affected. With `permanent_delete = true` there is no way back.
- **Wrong or missing exclusions.** A mistyped `exclude_folders` entry protects nothing: the folder you meant to keep out is scanned, and duplicates inside it can be moved. Always read the exclusion report and the dry run. `--exclude` on the command line replaces the list from the config file instead of adding to it.
- **Checksum-only matching.** With `match_by = checksum`, files with identical content but different names are treated as duplicates, even if you keep them separately on purpose (for example two intentionally identical files used in different projects). Moving one can break references to it.
- **Broken references.** Photo libraries, playlists, websites, scripts or other programs may point at a file that was moved.
- **Managed photo libraries and application data.** Programs such as Apple Photos (the `.photoslibrary` package), Lightroom catalogs, media servers and other photo managers keep their own database of the files they manage. Moving, renaming or deleting files inside such a library behind the program's back can damage the library or leave it with missing items. Do not use the inside of a managed library as `folder_base` or `folder_copy`; use the program's own duplicate tools or work on an export instead. If a library sits inside a folder you scan, exclude it, for example with the entry `Photos Library.photoslibrary` in `exclude_folders`.
- **Cloud-synced folders (iCloud Drive, OneDrive, Dropbox, Google Drive, ...).** Reading a file to calculate its checksum can make the sync client download "online-only" files, which can cost a lot of time, bandwidth and disk space. Moves and deletions are synchronised to the cloud and to your other devices, so a mistake spreads. Prefer a local copy of the data, or exclude online-only folders.
- **Edited or foreign CSV files.** `delete_matches.py` acts on whatever the CSV lists (subject to the safety checks above). Only use CSV files that you generated yourself with `find_matches.py`, and do not edit them by hand.
- **Race conditions.** If files change between the check and the move, unexpected results are possible.
- **Interrupted operations.** A crash, power loss or full disk during a move may leave files in an inconsistent state.
- **Platform and filesystem differences.** Behaviour can differ per operating system and filesystem (case sensitivity, symlinks, permissions, cloud-synced placeholders).
- **Exposed information.** The generated CSV files list your file paths; sharing them can reveal personal information.

You are solely responsible for backups, for verifying results, and for any decision to delete data.

## Privacy statement

- **The software runs entirely on your own computer.** It uses only the Python standard library and does not use the network. It has no telemetry, analytics, accounts or update checks.
- **The author does not collect, receive or store any of your data** through this software.
- **What it reads:** file names, sizes and file contents (only to calculate SHA-256 checksums) in the folders you configure, except the folders you exclude. File contents are not copied, stored or transmitted; only the checksum is kept.
- **What it writes (locally):** `matches.csv`, `not_selected.csv`, `deleted_log.csv` and the quarantine folder. The CSV files contain full file paths, which can include user names, device names and descriptive folder names, plus file sizes and checksums. `not_selected.csv` lists files that are **not** duplicates as well (by default those of `folder_copy`, with scope `both` those of both folders), so it can reveal more about your collection than `matches.csv`. Treat all of them as potentially personal data.
- **If you publish or share anything** (for example in an issue or pull request), remove or anonymise paths first, and never upload personal images or the CSV files. They are listed in `.gitignore` to reduce the chance of committing them by accident.
- **If you use this software on files that contain other people's personal data** (for example in a business context), you are responsible for complying with the data-protection rules that apply to you, such as the GDPR.
- Hosting platforms such as GitHub or Bitbucket process data you submit to them (issues, comments, commits) under their own privacy policies.

## Disclaimer (no warranty, no liability)

THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, ACCURACY, RELIABILITY AND NON-INFRINGEMENT. THE AUTHOR MAKES NO GUARANTEE THAT THE SOFTWARE IS FREE OF ERRORS OR THAT IT WILL MEET YOUR REQUIREMENTS.

YOU USE THE SOFTWARE ENTIRELY AT YOUR OWN RISK. TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, THE AUTHOR AND CONTRIBUTORS SHALL NOT BE LIABLE FOR ANY CLAIM, DAMAGE OR LOSS OF ANY KIND, INCLUDING BUT NOT LIMITED TO LOSS OR CORRUPTION OF DATA, LOSS OF PROFITS, BUSINESS INTERRUPTION, OR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL OR CONSEQUENTIAL DAMAGES, ARISING FROM THE USE OF, OR INABILITY TO USE, THE SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Nothing in this disclaimer excludes or limits any liability or any right that cannot be excluded or limited under applicable law.

The software is provided free of charge, as-is, without any obligation to maintain, update, fix or support it.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 MauPoLom.

## Versioning and changelog

This project uses [Semantic Versioning](https://semver.org/). Check your version with `python find_matches.py --version`.

| Version | Notes |
|---|---|
| 1.2.0 | New setting `not_selected_scope` (`folder_copy` or `both`). **Changed default:** `not_selected.csv` now lists only the unselected files of `folder_copy`; version 1.1.0 listed both folders (use `not_selected_scope = both` for that behaviour). `matches.csv` and `delete_matches.py` behaviour are unchanged. The repository also contains an automated `unittest` suite (`tests/`). |
| 1.1.0 | New: `exclude_folders` (skip folders by name or absolute path in both scanned folders, with a report and typo warnings) and `not_selected.csv` (export of every scanned file that was not selected for deletion, with a reason). Author name added. `matches.csv` and `delete_matches.py` behaviour are unchanged. |
| 1.0.0 | Initial release: config-file driven folder comparison, `name_and_checksum` / `checksum` matching, size pre-check, progress output, quarantine instead of delete, action log, empty-folder cleanup. |

## Support and contributions

Issues and pull requests are welcome but there is no guarantee of a response, a fix or ongoing maintenance. Do not attach personal files, file lists or CSV output to issues.

## Credits

Author: MauPoLom. Developed with the assistance of an AI model (Claude, by Anthropic). The code is provided without warranty, as described in the disclaimer above; AI-assisted code can contain errors, so review it yourself before relying on it.
