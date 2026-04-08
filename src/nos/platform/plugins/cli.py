"""CLI: ``nos plugin create <name>`` or ``nos-plugin create <name>``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scaffold import _parse_slug, create_plugin_project


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        prog="nos-plugin",
        description="NOS platform plugin utilities (also: nos plugin …)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Scaffold a pip-installable engine plugin package")
    p_create.add_argument("name", help="Plugin / distribution name (e.g. my-thing or my_thing)")
    p_create.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: ./<name> in kebab-case)",
    )

    args = parser.parse_args(argv)

    if args.cmd == "create":
        _pkg, dist = _parse_slug(args.name)
        out = args.out if args.out is not None else Path.cwd() / dist
        try:
            root = create_plugin_project(args.name, out)
        except (ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Created plugin project at {root}")
        return 0

    return 1
