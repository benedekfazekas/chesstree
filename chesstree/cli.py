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
from chesstree.d3html_exporter import export_d3html
from chesstree import opening_divider
from chesstree import leaf_evaluator
from chesstree.utils import CURRENT_SCHEMA_VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="chesstree",
        description="Convert chess games between PGN, JSON, and EDN formats.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__} (schema {CURRENT_SCHEMA_VERSION})")
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
        choices=["json", "edn", "pgn", "dot", "dothtml", "d3html"],
        default="json",
        help="Output format: json (default), edn, pgn, dot, dothtml, or d3html",
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
            "Image generation mode for dot/dothtml/d3html output (default: variations). "
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
            "Custom HTML template file for dothtml or d3html output. "
            "Must contain the required placeholders for the chosen format. "
            "Only used with -f dothtml or -f d3html."
        ),
    )
    parser.add_argument(
        "-a", "--hover-for-all-moves",
        action="store_true",
        dest="hover",
        help=(
            "Embed per-move hover board images (d3html output only). "
            "Mouseover a move to see the board position in a popup."
        ),
    )
    parser.add_argument(
        "--no-move-highlight",
        action="store_false",
        dest="highlight_last_move",
        help=(
            "Disable last-move square highlighting on board images "
            "(dot/dothtml/d3html output only). Highlighting is on by default."
        ),
    )
    parser.add_argument(
        "--var-summary-leaves",
        action="store_true",
        dest="var_summary_leaves",
        help=(
            "Add a variation summary table to d3html output: one row per leaf variation line "
            "(variations with no further sub-variations). Always includes the last main-line position."
        ),
    )
    parser.add_argument(
        "--var-summary-all",
        action="store_true",
        dest="var_summary_all",
        help=(
            "Add a variation summary table to d3html output: one row for every variation node "
            "regardless of depth. Always includes the last main-line position. "
            "Takes precedence over --var-summary-leaves."
        ),
    )
    parser.add_argument(
        "-c", "--concise",
        action="store_true",
        help="Compact output, no pretty-printing (json/edn output only)",
    )
    parser.add_argument(
        "--annotate-opening-end",
        action="store_true",
        default=False,
        dest="annotate_opening_end",
        help=(
            "Append [%%opening_end] to the move where the opening ends "
            "(computed locally by chesstree.opening_divider); "
            "no-op if the opening never ends."
        ),
    )
    parser.add_argument(
        "--annotate-eval",
        action="store_true",
        default=False,
        dest="annotate_eval",
        help=(
            "Enable engine-based [%%eval ...] annotation of positions "
            "(requires a UCI engine such as Stockfish on PATH)."
        ),
    )
    parser.add_argument(
        "--eval-scope",
        choices=["leaves", "branch-points", "all"],
        default="branch-points",
        dest="eval_scope",
        help=(
            "Which nodes to evaluate — leaves (terminal leaves only), "
            "branch-points (leaves + branch points, the default), "
            "or all (every node)."
        ),
    )
    parser.add_argument(
        "--engine",
        default=leaf_evaluator.DEFAULT_ENGINE,
        dest="engine",
        metavar="PATH",
        help="Path to / name of the UCI engine binary (default: stockfish).",
    )
    parser.add_argument(
        "--eval-depth",
        type=int,
        default=None,
        dest="eval_depth",
        help="Engine search depth (default 20 when neither depth nor time given).",
    )
    parser.add_argument(
        "--eval-time",
        type=float,
        default=None,
        dest="eval_time",
        help="Engine search time per position in seconds. Takes precedence over --eval-depth when both are given.",
    )
    return parser.parse_args()


def _detect_input_format(input_file: TextIO, override: str | None) -> str:
    if override:
        return override
    name = getattr(input_file, "name", "")
    if name.endswith(".json"):
        return "json"
    return "pgn"


def _maybe_annotate_opening_end(game: chess.pgn.Game, enabled: bool) -> None:
    """Annotate the opening-end move in place when the flag is set (no-op on None)."""
    if not enabled or game is None:
        return
    ply = opening_divider.opening_end_ply(game)
    if ply is not None:
        opening_divider.annotate_opening_end(game, ply)


def _maybe_annotate_evals_from_params(
    game: chess.pgn.Game | None,
    annotate_eval: bool,
    eval_scope: str,
    engine: str,
    eval_depth: int | None,
    eval_time: float | None,
) -> None:
    """Annotate game positions with [%eval ...] when annotate_eval is True.

    Builds an engine provider from the given params, runs annotation, then
    closes the engine. On EngineUnavailable, prints a warning and returns
    without annotating (does not crash the conversion).
    """
    if not annotate_eval or game is None:
        return
    if eval_time is not None:
        limit: chess.engine.Limit | None = chess.engine.Limit(time=eval_time)
    elif eval_depth is not None:
        limit = chess.engine.Limit(depth=eval_depth)
    else:
        limit = None
    try:
        provider, closer = leaf_evaluator.make_engine_provider(engine, limit)
    except leaf_evaluator.EngineUnavailable as exc:
        print(f"Warning: {exc}", file=sys.stderr)
        print("Warning: continuing without eval annotation", file=sys.stderr)
        return
    try:
        leaf_evaluator.annotate_evals(game, provider, scope=eval_scope)
    finally:
        closer()


def pgn_to_json(
    input_pgn: TextIO,
    output_json: TextIO,
    edn: bool,
    concise: bool = False,
    annotate_opening_end: bool = False,
    annotate_eval: bool = False,
    eval_scope: str = "branch-points",
    engine: str = "stockfish",
    eval_depth: int | None = None,
    eval_time: float | None = None,
) -> None:
    extension = "edn" if edn else "json"
    print(f"Reading {input_pgn.name} and converting to {extension}", file=sys.stderr)

    parsed_game = chess.pgn.read_game(input_pgn)
    if parsed_game is None:
        print(f"Error: no valid PGN game found in {input_pgn.name}", file=sys.stderr)
        sys.exit(1)

    _maybe_annotate_opening_end(parsed_game, annotate_opening_end)
    _maybe_annotate_evals_from_params(parsed_game, annotate_eval, eval_scope, engine, eval_depth, eval_time)

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


def json_to_pgn(input_json: TextIO, output_pgn: TextIO, annotate_opening_end: bool = False,
                annotate_eval: bool = False, eval_scope: str = "branch-points",
                engine: str = "stockfish", eval_depth: int | None = None,
                eval_time: float | None = None) -> None:
    print(f"Reading {input_json.name} and converting to PGN", file=sys.stderr)

    try:
        data = json_mod.load(input_json)
    except json_mod.JSONDecodeError as exc:
        print(f"Error: {input_json.name} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    game = parse_json(data)
    _maybe_annotate_opening_end(game, annotate_opening_end)
    _maybe_annotate_evals_from_params(game, annotate_eval, eval_scope, engine, eval_depth, eval_time)
    print(game, file=output_pgn, end="\n\n")
    print(f"Conversion to PGN done, written to {output_pgn.name}", file=sys.stderr)


def pgn_to_pgn(
    input_pgn: TextIO,
    output_pgn: TextIO,
    annotate_opening_end: bool = False,
    annotate_eval: bool = False,
    eval_scope: str = "branch-points",
    engine: str = "stockfish",
    eval_depth: int | None = None,
    eval_time: float | None = None,
) -> None:
    print(f"Reading {input_pgn.name} and converting to PGN", file=sys.stderr)

    game = chess.pgn.read_game(input_pgn)
    if game is None:
        print(f"Error: no valid PGN game found in {input_pgn.name}", file=sys.stderr)
        sys.exit(1)

    _maybe_annotate_opening_end(game, annotate_opening_end)
    _maybe_annotate_evals_from_params(game, annotate_eval, eval_scope, engine, eval_depth, eval_time)

    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    pgn_str = game.accept(exporter)
    print(pgn_str, file=output_pgn, end="\n\n")
    print(f"Conversion to PGN done, written to {output_pgn.name}", file=sys.stderr)


def game_to_dot(
    input_file: TextIO,
    output_file: TextIO,
    input_fmt: str,
    images: list | None = None,
    forblack: bool = False,
    highlight_last_move: bool = True,
    annotate_opening_end: bool = False,
    annotate_eval: bool = False,
    eval_scope: str = "branch-points",
    engine: str = "stockfish",
    eval_depth: int | None = None,
    eval_time: float | None = None,
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

    _maybe_annotate_opening_end(game, annotate_opening_end)
    _maybe_annotate_evals_from_params(game, annotate_eval, eval_scope, engine, eval_depth, eval_time)

    modes = frozenset(images or ["variations"])
    dot_str, images_dict = export_dot(game, image_modes=modes, board_img_for_black=forblack, highlight_last_move=highlight_last_move)
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
    highlight_last_move: bool = True,
    annotate_opening_end: bool = False,
    annotate_eval: bool = False,
    eval_scope: str = "branch-points",
    engine: str = "stockfish",
    eval_depth: int | None = None,
    eval_time: float | None = None,
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

    _maybe_annotate_opening_end(game, annotate_opening_end)
    _maybe_annotate_evals_from_params(game, annotate_eval, eval_scope, engine, eval_depth, eval_time)
    modes = frozenset(images or ["variations"])
    template_path = pathlib.Path(template_file.name) if template_file else None

    try:
        html_str, images_dict = export_dothtml(
            game,
            image_modes=modes,
            board_img_for_black=forblack,
            template_path=template_path,
            highlight_last_move=highlight_last_move,
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


def game_to_d3html(
    input_file: TextIO,
    output_file: TextIO,
    input_fmt: str,
    images: list | None = None,
    forblack: bool = False,
    template_file: TextIO | None = None,
    hover: bool = False,
    highlight_last_move: bool = True,
    var_summary_mode: str | None = None,
    annotate_opening_end: bool = False,
    annotate_eval: bool = False,
    eval_scope: str = "branch-points",
    engine: str = "stockfish",
    eval_depth: int | None = None,
    eval_time: float | None = None,
) -> None:
    print(f"Reading {input_file.name} and converting to d3html", file=sys.stderr)

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

    _maybe_annotate_opening_end(game, annotate_opening_end)
    _maybe_annotate_evals_from_params(game, annotate_eval, eval_scope, engine, eval_depth, eval_time)
    modes = frozenset(images or ["variations"])
    template_path = pathlib.Path(template_file.name) if template_file else None

    try:
        html_str, images_dict = export_d3html(
            game,
            image_modes=modes,
            board_img_for_black=forblack,
            template_path=template_path,
            hover=hover,
            highlight_last_move=highlight_last_move,
            var_summary_mode=var_summary_mode,
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

    print(f"Conversion to d3html done, written to {output_file.name}", file=sys.stderr)


def cli() -> None:
    args = parse_args()

    if args.template and args.format not in ("dothtml", "d3html"):
        print("Warning: --template is only used with -f dothtml or -f d3html; ignoring.", file=sys.stderr)

    if args.hover and args.format != "d3html":
        print("Warning: -a/--hover-for-all-moves is only used with -f d3html; ignoring.", file=sys.stderr)

    if (args.var_summary_leaves or args.var_summary_all) and args.format != "d3html":
        print("Warning: --var-summary-leaves/--var-summary-all is only used with -f d3html; ignoring.", file=sys.stderr)

    input_fmt = _detect_input_format(args.input, args.input_format)
    output_fmt = args.format

    if input_fmt == "pgn" and output_fmt in ("json", "edn"):
        pgn_to_json(args.input, args.output,
                    edn=(output_fmt == "edn"),
                    concise=args.concise,
                    annotate_opening_end=args.annotate_opening_end,
                    annotate_eval=args.annotate_eval,
                    eval_scope=args.eval_scope,
                    engine=args.engine,
                    eval_depth=args.eval_depth,
                    eval_time=args.eval_time)
    elif input_fmt == "pgn" and output_fmt == "pgn":
        pgn_to_pgn(args.input, args.output,
                   annotate_opening_end=args.annotate_opening_end,
                   annotate_eval=args.annotate_eval,
                   eval_scope=args.eval_scope,
                   engine=args.engine,
                   eval_depth=args.eval_depth,
                   eval_time=args.eval_time)
    elif input_fmt == "json" and output_fmt == "pgn":
        json_to_pgn(args.input, args.output,
                    annotate_opening_end=args.annotate_opening_end,
                    annotate_eval=args.annotate_eval,
                    eval_scope=args.eval_scope,
                    engine=args.engine,
                    eval_depth=args.eval_depth,
                    eval_time=args.eval_time)
    elif input_fmt in ("pgn", "json") and output_fmt == "dot":
        game_to_dot(args.input, args.output, input_fmt,
                    images=args.images, forblack=args.forblack,
                    highlight_last_move=args.highlight_last_move,
                    annotate_opening_end=args.annotate_opening_end,
                    annotate_eval=args.annotate_eval,
                    eval_scope=args.eval_scope,
                    engine=args.engine,
                    eval_depth=args.eval_depth,
                    eval_time=args.eval_time)
    elif input_fmt in ("pgn", "json") and output_fmt == "dothtml":
        game_to_dothtml(
            args.input, args.output, input_fmt,
            images=args.images,
            forblack=args.forblack,
            template_file=args.template,
            highlight_last_move=args.highlight_last_move,
            annotate_opening_end=args.annotate_opening_end,
            annotate_eval=args.annotate_eval,
            eval_scope=args.eval_scope,
            engine=args.engine,
            eval_depth=args.eval_depth,
            eval_time=args.eval_time,
        )
    elif input_fmt in ("pgn", "json") and output_fmt == "d3html":
        var_summary_mode: str | None = None
        if args.var_summary_all:
            var_summary_mode = "all"
        elif args.var_summary_leaves:
            var_summary_mode = "leaves"
        game_to_d3html(
            args.input, args.output, input_fmt,
            images=args.images,
            forblack=args.forblack,
            template_file=args.template,
            hover=args.hover,
            highlight_last_move=args.highlight_last_move,
            var_summary_mode=var_summary_mode,
            annotate_opening_end=args.annotate_opening_end,
            annotate_eval=args.annotate_eval,
            eval_scope=args.eval_scope,
            engine=args.engine,
            eval_depth=args.eval_depth,
            eval_time=args.eval_time,
        )
    else:
        print(
            f"Error: unsupported conversion: {input_fmt} → {output_fmt}. "
            f"Supported: pgn→json, pgn→edn, pgn→pgn, pgn→dot, pgn→dothtml, pgn→d3html, "
            f"json→pgn, json→dot, json→dothtml, json→d3html",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    cli()
