#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


NS = {"v": "https://schema.gradle.org/dependency-verification"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_expected(path: Path) -> dict[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported DJI checksum manifest schema: {payload.get('schema_version')!r}")

    components = payload.get("components")
    if not isinstance(components, dict) or not components:
        raise ValueError("DJI checksum manifest has no components")

    result: dict[str, dict[str, str]] = {}
    for coordinate, artifacts in components.items():
        if not isinstance(coordinate, str) or coordinate.count(":") != 2:
            raise ValueError(f"Invalid DJI component coordinate: {coordinate!r}")
        if not isinstance(artifacts, dict) or not artifacts:
            raise ValueError(f"DJI component {coordinate} has no artifact hashes")

        normalized: dict[str, str] = {}
        for filename, sha256 in artifacts.items():
            if not isinstance(filename, str) or not filename:
                raise ValueError(f"Invalid artifact name for {coordinate}")
            if not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256.lower()) is None:
                raise ValueError(f"Invalid SHA-256 for {coordinate}/{filename}")
            normalized[filename] = sha256.lower()
        result[coordinate] = normalized
    return result


def _load_observed(path: Path) -> dict[str, dict[str, str]]:
    root = ET.parse(path).getroot()
    components = root.find("v:components", NS)
    if components is None:
        raise ValueError("Gradle verification metadata has no components element")

    observed: dict[str, dict[str, str]] = {}
    for component in components.findall("v:component", NS):
        group = component.get("group") or ""
        if group != "com.dji":
            continue

        name = component.get("name") or ""
        version = component.get("version") or ""
        coordinate = f"{group}:{name}:{version}"
        artifact_hashes: dict[str, str] = {}

        for artifact in component.findall("v:artifact", NS):
            filename = artifact.get("name") or ""
            hashes = [
                node.get("value", "").lower()
                for node in artifact.findall("v:sha256", NS)
                if node.get("value")
            ]
            unique = sorted(set(hashes))
            if len(unique) != 1:
                raise ValueError(
                    f"Expected exactly one SHA-256 for {coordinate}/{filename}, got {unique}"
                )
            artifact_hashes[filename] = unique[0]

        observed[coordinate] = artifact_hashes
    return observed


def verify(expected_path: Path, metadata_path: Path) -> None:
    expected = _load_expected(expected_path)
    observed = _load_observed(metadata_path)

    expected_components = set(expected)
    observed_components = set(observed)
    if observed_components != expected_components:
        missing = sorted(expected_components - observed_components)
        unexpected = sorted(observed_components - expected_components)
        raise ValueError(
            "DJI dependency component set changed; "
            f"missing={missing}, unexpected={unexpected}"
        )

    failures: list[str] = []
    for coordinate, artifacts in expected.items():
        actual_artifacts = observed[coordinate]
        expected_names = set(artifacts)
        actual_names = set(actual_artifacts)
        if actual_names != expected_names:
            failures.append(
                f"{coordinate}: artifact set changed; "
                f"missing={sorted(expected_names - actual_names)}, "
                f"unexpected={sorted(actual_names - expected_names)}"
            )
            continue

        for filename, expected_hash in artifacts.items():
            actual_hash = actual_artifacts[filename]
            if actual_hash != expected_hash:
                failures.append(
                    f"{coordinate}/{filename}: SHA-256 mismatch "
                    f"(expected {expected_hash}, got {actual_hash})"
                )

    if failures:
        raise ValueError("\n".join(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify resolved com.dji Gradle artifacts against reviewed SHA-256 values."
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=Path("gradle/dji-dependency-sha256.json"),
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("gradle/verification-metadata.xml"),
    )
    args = parser.parse_args(argv)

    try:
        verify(args.expected, args.metadata)
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f"DJI dependency verification FAILED: {exc}", file=sys.stderr)
        return 1

    print("DJI dependency verification PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
