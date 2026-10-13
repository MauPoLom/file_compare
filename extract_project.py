#!/usr/bin/env python3
"""Recreate the project files from PROJECT_RECREATION_GUIDE.md.

Usage: python extract_project.py PROJECT_RECREATION_GUIDE.md [target_folder]
"""
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    target = Path(sys.argv[2] if len(sys.argv) > 2 else "duplicate-image-finder").resolve()
    if target.exists() and any(target.iterdir()):
        print(f"Target folder is not empty: {target}")
        return 1

    written = []
    i = 0
    while i < len(lines):
        m = re.match(r"^#### FILE: `([^`]+)`\s*$", lines[i])
        i += 1
        if not m:
            continue
        name = m.group(1)
        while i < len(lines) and not lines[i].startswith("```"):
            i += 1
        if i >= len(lines):
            print(f"No code block found for {name}")
            return 1
        fence = re.match(r"`+", lines[i]).group(0)
        i += 1
        body = []
        while i < len(lines) and lines[i].rstrip() != fence:
            body.append(lines[i])
            i += 1
        if i >= len(lines):
            print(f"Unterminated code block for {name}")
            return 1
        i += 1
        dest = (target / name).resolve()
        try:
            dest.relative_to(target)
        except ValueError:
            print(f"Refusing path outside the target folder: {name}")
            return 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(body) + "\n")
        written.append(name)

    if not written:
        print("No files found in the guide.")
        return 1
    print(f"Recreated {len(written)} file(s) in {target}:")
    for name in written:
        print(f"  {name}")
    print("Next: replace the repository URL placeholder (<your-account>/<your-repo>) in README.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
