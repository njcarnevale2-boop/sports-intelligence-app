#!/usr/bin/env python3
"""Install a verified SIA seed package onto a destination root safely.

Design goals:
- Deterministic manifest-based install
- SHA-256 verification before copy
- No-clobber by default
- Refuse to overwrite differing existing files
- Idempotent repeated execution
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


EXIT_OK = 0
EXIT_BAD_ARGS = 2
EXIT_MANIFEST_ERROR = 3
EXIT_EXISTING_DIFFERS = 4


PROTECTED_FILENAMES = {
	"sports_intelligence.db",
	"nfl_model.duckdb",
	"refresh_state.json",
}


@dataclass(frozen=True)
class Artifact:
	path: str
	size_bytes: int
	sha256: str


def _sha256_file(path: Path) -> str:
	h = hashlib.sha256()
	with path.open("rb") as f:
		for chunk in iter(lambda: f.read(1024 * 1024), b""):
			h.update(chunk)
	return h.hexdigest()


def _parse_manifest(manifest_path: Path) -> tuple[dict[str, Any], list[Artifact]]:
	try:
		payload = json.loads(manifest_path.read_text(encoding="utf-8"))
	except Exception as exc:
		raise ValueError(f"Could not read manifest: {manifest_path} ({exc})") from exc

	raw_artifacts = payload.get("artifacts")
	if not isinstance(raw_artifacts, list) or not raw_artifacts:
		raise ValueError("Manifest is missing a non-empty artifacts list")

	artifacts: list[Artifact] = []
	for idx, item in enumerate(raw_artifacts):
		if not isinstance(item, dict):
			raise ValueError(f"Manifest artifact at index {idx} is not an object")
		rel_path = str(item.get("path") or "").strip()
		size = item.get("size_bytes")
		sha = str(item.get("sha256") or "").strip().lower()

		if not rel_path or rel_path.startswith("/") or ".." in Path(rel_path).parts:
			raise ValueError(f"Invalid artifact path at index {idx}: {rel_path!r}")
		if not isinstance(size, int) or size < 0:
			raise ValueError(f"Invalid size_bytes for {rel_path!r}")
		if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
			raise ValueError(f"Invalid sha256 for {rel_path!r}")

		artifacts.append(Artifact(path=rel_path, size_bytes=size, sha256=sha))

	return payload, artifacts


def _iter_manifest_issues(source_root: Path, artifacts: Iterable[Artifact]) -> Iterable[str]:
	for artifact in artifacts:
		src = source_root / artifact.path
		if not src.exists() or not src.is_file():
			yield f"SOURCE_MISSING|{artifact.path}"
			continue

		actual_size = src.stat().st_size
		if actual_size != artifact.size_bytes:
			yield (
				f"SIZE_MISMATCH|{artifact.path}|manifest={artifact.size_bytes}|"
				f"actual={actual_size}"
			)

		actual_sha = _sha256_file(src)
		if actual_sha != artifact.sha256:
			yield f"CHECKSUM_MISMATCH|{artifact.path}"


def _load_source(source: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
	if source.is_dir():
		return source, None

	if source.is_file() and source.suffix in {".tar", ".tgz", ".gz"}:
		tmp_dir = tempfile.TemporaryDirectory(prefix="sia-render-seed-")
		with tarfile.open(source, mode="r:*") as tf:
			try:
				tf.extractall(tmp_dir.name, filter="data")
			except TypeError:
				tf.extractall(tmp_dir.name)
		return Path(tmp_dir.name), tmp_dir

	raise ValueError("Source must be a directory or a tar/tgz archive")


def _is_protected(path: Path) -> bool:
	return path.name in PROTECTED_FILENAMES


def bootstrap(source: Path, destination_root: Path, manifest_name: str) -> int:
	source_root, temp_handle = _load_source(source)
	try:
		manifest_path = source_root / manifest_name
		if not manifest_path.exists():
			print(f"ERROR: manifest not found at {manifest_path}")
			return EXIT_MANIFEST_ERROR

		_, artifacts = _parse_manifest(manifest_path)

		issues = list(_iter_manifest_issues(source_root, artifacts))
		if issues:
			print("MANIFEST_VALIDATION: FAIL")
			for issue in issues:
				print(issue)
			return EXIT_MANIFEST_ERROR

		destination_root.mkdir(parents=True, exist_ok=True)

		differing: list[str] = []
		for artifact in artifacts:
			src = source_root / artifact.path
			dst = destination_root / artifact.path
			if dst.exists() and dst.is_file():
				if _sha256_file(dst) != artifact.sha256:
					label = "EXISTING_FILE_DIFFERS_PROTECTED" if _is_protected(dst) else "EXISTING_FILE_DIFFERS"
					differing.append(f"{label}|{artifact.path}")

		if differing:
			print("INSTALL_PLAN: BLOCKED")
			for row in differing:
				print(row)
			print("ACTION_REQUIRED: explicit operator intervention required; no files copied")
			return EXIT_EXISTING_DIFFERS

		installed = 0
		skipped = 0
		for artifact in artifacts:
			src = source_root / artifact.path
			dst = destination_root / artifact.path

			if dst.exists():
				skipped += 1
				continue

			dst.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(src, dst)
			if _sha256_file(dst) != artifact.sha256:
				print(f"ERROR: post-copy checksum mismatch for {artifact.path}")
				return EXIT_MANIFEST_ERROR
			installed += 1

		print("MANIFEST_VALIDATION: PASS")
		print("CHECKSUM_VALIDATION: PASS")
		print(f"ARTIFACTS_TOTAL: {len(artifacts)}")
		print(f"FILES_INSTALLED: {installed}")
		print(f"FILES_SKIPPED_EXISTING: {skipped}")
		print("FILES_OVERWRITTEN: 0")
		print("RESULT: SUCCESS")
		return EXIT_OK
	finally:
		if temp_handle is not None:
			temp_handle.cleanup()


def main() -> int:
	parser = argparse.ArgumentParser(description="Install SIA Render seed package safely")
	parser.add_argument("--source", required=True, help="Seed source directory or tar/tgz archive")
	parser.add_argument("--destination-root", required=True, help="Destination root path (e.g. /data)")
	parser.add_argument(
		"--manifest",
		default="seed_manifest_v1.json",
		help="Manifest path relative to source root (default: seed_manifest_v1.json)",
	)
	args = parser.parse_args()

	source = Path(args.source).expanduser().resolve()
	destination = Path(args.destination_root).expanduser().resolve()

	if not source.exists():
		print(f"ERROR: source does not exist: {source}")
		return EXIT_BAD_ARGS

	try:
		return bootstrap(source=source, destination_root=destination, manifest_name=str(args.manifest))
	except ValueError as exc:
		print(f"ERROR: {exc}")
		return EXIT_BAD_ARGS


if __name__ == "__main__":
	raise SystemExit(main())
