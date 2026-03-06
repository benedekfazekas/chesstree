from __future__ import annotations

import argparse
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PGN to JSON/EDN converter")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-i", "--input",
        type=argparse.FileType("r"),
        required=True,
        help="The input PGN file to be processed (use '-' for stdin)",
    )
    parser.add_argument(
        "-o", "--output",
        type=argparse.FileType("w"),
        default="-",
        help="The output file for results (default: stdout)",
    )
    parser.add_argument(
        "-b", "--forblack",
        action="store_true",
        help="Board images are generated from Black's perspective",
    )
    parser.add_argument(
        "-e", "--edn",
        action="store_true",
        help="Output EDN instead of JSON",
    )
    parser.add_argument(
        "-c", "--concise",
        action="store_true",
        help="Output compact (non-pretty-printed) JSON/EDN",
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


def cli() -> None:
    args = parse_args()
    pgn_to_json(args.input, args.output, args.forblack, args.edn, args.concise)


if __name__ == "__main__":
    cli()
