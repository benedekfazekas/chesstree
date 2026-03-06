from __future__ import annotations

import argparse
import json as json_mod
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PGN ↔ JSON/EDN chess game converter")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- export: PGN → JSON/EDN ---
    export_parser = subparsers.add_parser(
        "export",
        help="Convert a PGN file to JSON or EDN",
    )
    export_parser.add_argument(
        "-i", "--input",
        type=argparse.FileType("r"),
        required=True,
        help="The input PGN file to be processed (use '-' for stdin)",
    )
    export_parser.add_argument(
        "-o", "--output",
        type=argparse.FileType("w"),
        default="-",
        help="The output file for results (default: stdout)",
    )
    export_parser.add_argument(
        "-b", "--forblack",
        action="store_true",
        help="Board images are generated from Black's perspective",
    )
    export_parser.add_argument(
        "-e", "--edn",
        action="store_true",
        help="Output EDN instead of JSON",
    )
    export_parser.add_argument(
        "-c", "--concise",
        action="store_true",
        help="Output compact (non-pretty-printed) JSON/EDN",
    )

    # --- import: JSON → PGN ---
    import_parser = subparsers.add_parser(
        "import",
        help="Convert a chesstree JSON file back to PGN",
    )
    import_parser.add_argument(
        "-i", "--input",
        type=argparse.FileType("r"),
        required=True,
        help="The input JSON file produced by 'chesstree export'",
    )
    import_parser.add_argument(
        "-o", "--output",
        type=argparse.FileType("w"),
        default="-",
        help="The output PGN file (default: stdout)",
    )

    return parser.parse_args()


def pgn_to_json(
    input_pgn: TextIO,
    output_json: TextIO,
    forblack: bool,
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
        board_img_for_black=forblack,
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


def cli() -> None:
    args = parse_args()
    if args.command == "export":
        pgn_to_json(args.input, args.output, args.forblack, args.edn, args.concise)
    elif args.command == "import":
        json_to_pgn(args.input, args.output)


if __name__ == "__main__":
    cli()
