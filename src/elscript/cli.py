"""Thin command-line wrapper around the public ELScript API."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .api import render
from .diagnostics import format_error, format_warning
from .domain import OutputMode, RenderOptions
from .errors import ELScriptError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elscript",
        description="Render an ELScript YAML file or project directory to audio files.",
    )
    parser.add_argument("source", type=Path, help="ELScript .yaml/.yml file or project directory")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("audio"),
        metavar="DIRECTORY",
        help="output directory (default: ./audio)",
    )
    parser.add_argument("--mode", choices=tuple(OutputMode), help="single, scene, or segment")
    parser.add_argument("--model", metavar="MODEL_ID", help="override the provider model")
    parser.add_argument("--format", dest="output_format", metavar="OUTPUT_FORMAT")
    parser.add_argument("--seed", type=int, help="best-effort deterministic generation seed")
    parser.add_argument("--env-file", type=Path, metavar="PATH", help="explicit .env file")
    return parser


def _error_line(error: ELScriptError) -> str:
    return format_error(error)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    options = RenderOptions(
        model=args.model,
        output_format=args.output_format,
        output_mode=args.mode,
        seed=args.seed,
    )

    try:
        result = render(
            source=args.source,
            output_dir=args.output,
            options=options,
            env_file=args.env_file,
        )
    except ELScriptError as error:
        parser.exit(1, _error_line(error))

    for warning in result.warnings:
        print(format_warning(warning), file=sys.stderr)
    for output_file in result.files:
        print(output_file)
    if result.manifest_path is not None:
        print(result.manifest_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
