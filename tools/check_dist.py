"""Verify that ELScript release archives contain only the intended public surfaces."""

from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from pathlib import Path

_VERSION_PATTERN = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _version(repo_root: Path) -> str:
    match = _VERSION_PATTERN.search((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    if match is None:
        raise ValueError("pyproject.toml does not contain a static project version")
    return match.group(1)


def _one(paths: tuple[Path, ...], kind: str) -> Path:
    if len(paths) != 1:
        names = ", ".join(path.name for path in paths) or "none"
        raise ValueError(f"expected one {kind}, found {names}")
    return paths[0]


def verify(dist_dir: Path, *, repo_root: Path) -> tuple[Path, Path]:
    version = _version(repo_root)
    wheel = _one(tuple(dist_dir.glob(f"elscript-{version}-*.whl")), "wheel")
    sdist = _one(tuple(dist_dir.glob(f"elscript-{version}.tar.gz")), "sdist")
    prefix = f"elscript-{version}"

    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
    wheel_required = {
        "elscript/__init__.py",
        "elscript/py.typed",
        f"{prefix}.dist-info/METADATA",
        f"{prefix}.dist-info/entry_points.txt",
        f"{prefix}.dist-info/licenses/LICENSE",
    }
    missing_wheel = sorted(wheel_required - wheel_names)
    if missing_wheel:
        raise ValueError(f"wheel is missing: {', '.join(missing_wheel)}")

    with tarfile.open(sdist) as archive:
        sdist_names = set(archive.getnames())
    sdist_required = {
        f"{prefix}/CHANGELOG.md",
        f"{prefix}/DESIGN.md",
        f"{prefix}/LICENSE",
        f"{prefix}/README.md",
        f"{prefix}/docs/configuration.md",
        f"{prefix}/docs/manifest.md",
        f"{prefix}/docs/providers.md",
        f"{prefix}/docs/releasing.md",
        f"{prefix}/docs/streaming.md",
        f"{prefix}/docs/syntax.md",
        f"{prefix}/docs/troubleshooting.md",
        f"{prefix}/tests/test_docs_examples.py",
        f"{prefix}/tools/check_dist.py",
    }
    missing_sdist = sorted(sdist_required - sdist_names)
    if missing_sdist:
        raise ValueError(f"sdist is missing: {', '.join(missing_sdist)}")

    forbidden_parts = {".codex", ".git", ".vibe"}
    forbidden_names = {"AGENTS.md", "VIBE.md"}
    leaked = sorted(
        name
        for name in sdist_names
        if forbidden_parts.intersection(Path(name).parts)
        or Path(name).name in forbidden_names
    )
    if leaked:
        raise ValueError(f"sdist contains internal workflow files: {', '.join(leaked)}")
    return wheel, sdist


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_dir", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    wheel, sdist = verify(args.dist_dir.resolve(), repo_root=repo_root)
    print(f"verified {wheel.name}")
    print(f"verified {sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
