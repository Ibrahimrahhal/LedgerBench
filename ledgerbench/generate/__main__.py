"""python -m ledgerbench.generate --size mini --seed 2026 [--out data]"""

from __future__ import annotations

import argparse
import sys

from ledgerbench.generate import main
from ledgerbench.generate.check import CheckError
from ledgerbench.generate.personas import SIZES
from ledgerbench.generate.questions import GenerationError


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ledgerbench.generate", description="Generate a LedgerBench dataset and check it."
    )
    parser.add_argument("--size", choices=sorted(SIZES), default="standard")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", default="data", help="output directory (default: data)")
    args = parser.parse_args(argv)
    try:
        main(args.size, args.seed, args.out)
    except (CheckError, GenerationError) as exc:
        print(f"generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(cli())
