from __future__ import annotations

import argparse
import json as json_mod
import pathlib
import chess
import sys
from typing import TextIO

try:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("chesstree")
    except PackageNotFoundError:
        __version__ = "unknown"
except ImportError:
    __version__ = "unknown"

from chesstree import json_exporter
from chesstree.json_parser import parse_json
from chesstree.dot_exporter import export_dot
from chesstree.dothtml_exporter import export_dothtml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert chess games between PGN, JSON, and EDN formats.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-i", "--input",
        type=argparse.FileType("r"),
        required=True,
        help="Input file — PGN or chesstree JSON (use '-' for stdin)",
    )
    parser.add_argument(
        "-o", "--output",
        type=argparse.FileType("w"),
        default="-",
        help="Output file (default: stdout)",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["json", "edn", "pgn", "dot", "dothtml"],
        default="json",
        help="Output format: json (default), edn, pgn, dot, or dothtml",
    )
    parser.add_argument(
        "--input-format",
        choices=["pgn", "json"],
        default=None,
        help="Override auto-detected input format (auto-detected from file extension by default)",
    )
    parser.add_argument(
        "-b", "--forblack",
        action="store_true",
        help="Board images from Black's perspective (dot/dothtml output)",
    )
    parser.add_argument(
        "--images",
        nargs="+",
        choices=["none", "all", "variations", "commented"],
        default=["variations"],
        metavar="MODE",
        help=(
            "Image generation mode for dot/dothtml output (default: variations). "
            "Choices: none, all, variations, commented. "
            "'variations' and 'commented' may be combined. "
            "SVG files are written alongside the output file; "
            "stdout output includes image references but does not write SVG files. "
            "Has no effect on json/edn output."
        ),
    )
    parser.add_argument(
        "--template",
        type=argparse.FileType("r"),
        default=None,
        metavar="FILE",
        help=(
            "Custom HTML template file for dothtml output. "
            "Must contain the placeholders {{CHESSTREE_TITLE}}, {{CHESSTREE_IMAGES}}, "
            "and {{CHESSTREE_DOT}}. Only used with -f dothtml."
        ),
    )
    parser.add_argument(
        "-c", "--concise",
        action="store_true",
        help="Compact output, no pretty-printing (json/edn output only)",
    )
    return parser.parse_args()


def _detect_input_format(input_file: TextIO, override: str | None) -> str:
    if override:
        return override
    name = getattr(input_file, "name", "")
    if name.endswith(".json"):
        return "json"
    return "pgn"


def pgn_to_json(
    input_pgn: TextIO,
    output_json: TextIO,
    edn: bool,
    concise: bool = False,
) -> None:
    extension = "edn" if edn else "json"
    print(f"Reading {input_pgn.name} and converting to {extension}", file=sys.stderr)

    parsed_game = chess.pgn.read_game(input_pgn)
    if parsed_game is None:
        print(f"Error: no valid PGN game found in {input_pgn.name}", file=sys.stderr)
        sys.exit(1)

    exporter = json_exporter.JsonExporter(
        headers=True,
        variations=True,
        comments=True,
        edn=edn,
        concise=concise,
    )
    game_json_edn = parsed_game.accept(exporter)
    print(game_json_edn, file=output_json, end="\n\n")
    print(f"Conversion to {extension} done, written to {output_json.name}", file=sys.stderr)


def json_to_pgn(input_json: TextIO, output_pgn: TextIO) -> None:
    print(f"Reading {input_json.name} and converting to PGN", file=sys.stderr)

    try:
        data = json_mod.load(input_json)
    except json_mod.JSONDecodeError as exc:
        print(f"Error: {input_json.name} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    game = parse_json(data)
    print(game, file=output_pgn, end="\n\n")
    print(f"Conversion to PGN done, written to {output_pgn.name}", file=sys.stderr)


def game_to_dot(
    input_file: TextIO,
    output_file: TextIO,
    input_fmt: str,
    images: list | None = None,
    forblack: bool = False,
) -> None:
    print(f"Reading {input_file.name} and converting to DOT", file=sys.stderr)

    if input_fmt == "json":
        try:
            data = json_mod.load(input_file)
        except json_mod.JSONDecodeError as exc:
            print(f"Error: {input_file.name} is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        game = parse_json(data)
    else:
        game = chess.pgn.read_game(input_file)
        if game is None:
            print(f"Error: no valid PGN game found in {input_file.name}", file=sys.stderr)
            sys.exit(1)

    modes = frozenset(images or ["variations"])
    dot_str, images_dict = export_dot(game, image_modes=modes, board_img_for_black=forblack)
    print(dot_str, file=output_file)

    is_stdout = getattr(output_file, "name", "<stdout>") == "<stdout>"
    if not is_stdout and images_dict:
        output_dir = pathlib.Path(output_file.name).parent
        for filename, svg_content in images_dict.items():
            (output_dir / filename).write_text(svg_content)
        print(
            f"Written {len(images_dict)} SVG image(s) to {output_dir}",
            file=sys.stderr,
        )

    print(f"Conversion to DOT done, written to {output_file.name}", file=sys.stderr)


def game_to_dothtml(
    input_file: TextIO,
    output_file: TextIO,
    input_fmt: str,
    images: list | None = None,
    forblack: bool = False,
    template_file: TextIO | None = None,
) -> None:
    print(f"Reading {input_file.name} and converting to dothtml", file=sys.stderr)

    if input_fmt == "json":
        try:
            data = json_mod.load(input_file)
        except json_mod.JSONDecodeError as exc:
            print(f"Error: {input_file.name} is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        game = parse_json(data)
    else:
        game = chess.pgn.read_game(input_file)
        if game is None:
            print(f"Error: no valid PGN game found in {input_file.name}", file=sys.stderr)
            sys.exit(1)

    modes = frozenset(images or ["variations"])
    template_path = pathlib.Path(template_file.name) if template_file else None

    try:
        html_str, images_dict = export_dothtml(
            game,
            image_modes=modes,
            board_img_for_black=forblack,
            template_path=template_path,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(html_str, file=output_file, end="")

    is_stdout = getattr(output_file, "name", "<stdout>") == "<stdout>"
    if not is_stdout and images_dict:
        output_dir = pathlib.Path(output_file.name).parent
        for filename, svg_content in images_dict.items():
            (output_dir / filename).write_text(svg_content)
        print(
            f"Written {len(images_dict)} SVG image(s) to {output_dir}",
            file=sys.stderr,
        )

    print(f"Conversion to dothtml done, written to {output_file.name}", file=sys.stderr)


def cli() -> None:
    args = parse_args()

    if args.template and args.format != "dothtml":
        print("Warning: --template is only used with -f dothtml; ignoring.", file=sys.stderr)

    input_fmt = _detect_input_format(args.input, args.input_format)
    output_fmt = args.format

    if input_fmt == "pgn" and output_fmt in ("json", "edn"):
        pgn_to_json(args.input, args.output,
                    edn=(output_fmt == "edn"),
                    concise=args.concise)
    elif input_fmt == "json" and output_fmt == "pgn":
        json_to_pgn(args.input, args.output)
    elif input_fmt in ("pgn", "json") and output_fmt == "dot":
        game_to_dot(args.input, args.output, input_fmt, images=args.images, forblack=args.forblack)
    elif input_fmt in ("pgn", "json") and output_fmt == "dothtml":
        game_to_dothtml(
            args.input, args.output, input_fmt,
            images=args.images,
            forblack=args.forblack,
            template_file=args.template,
        )
    else:
        print(
            f"Error: unsupported conversion: {input_fmt} → {output_fmt}. "
            f"Supported: pgn→json, pgn→edn, pgn→dot, pgn→dothtml, json→pgn, json→dot, json→dothtml",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    cli()
