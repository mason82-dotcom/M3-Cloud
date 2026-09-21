#!/usr/bin/env python3
"""Fail CI on Android Lint errors outside explicitly grandfathered UI debt."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

IGNORED_ERROR_IDS = {"MissingTranslation", "UseAppTint"}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_android_lint_errors.py <lint-results.xml>", file=sys.stderr)
        return 2

    report = Path(sys.argv[1])
    root = ET.parse(report).getroot()
    failures: list[str] = []

    for issue in root.findall("issue"):
        if issue.attrib.get("severity") != "Error":
            continue
        issue_id = issue.attrib.get("id", "unknown")
        if issue_id in IGNORED_ERROR_IDS:
            continue

        location = issue.find("location")
        file_name = location.attrib.get("file", "<unknown>") if location is not None else "<unknown>"
        line = location.attrib.get("line", "?") if location is not None else "?"
        message = issue.attrib.get("message", "")
        failures.append(f"{issue_id}: {file_name}:{line}: {message}")

    if failures:
        print("Android Lint correctness gate failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    ignored = ", ".join(sorted(IGNORED_ERROR_IDS))
    print(f"Android Lint correctness gate passed (grandfathered: {ignored})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
