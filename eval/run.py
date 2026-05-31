"""CLI entry point: ``python -m eval.run`` (SPEC §4.3).

M1: validates config + stimuli, expands the grid, and on ``--dry-run`` prints the
full call plan and cost projection without making any API call. Live execution is
implemented in M2.
"""

from __future__ import annotations

import argparse
import sys

from eval.config import load_config, load_items, load_translations
from eval.runner import build_grid, dry_run_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.run", description=__doc__)
    parser.add_argument("--config", required=True, help="path to configs/*.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="print call plan + cost estimate, make ZERO API calls")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the grid to the first N cells")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    items = load_items(cfg.paths.items)
    translations = load_translations(cfg.paths.translations)
    grid = build_grid(cfg, items, translations, limit=args.limit)

    if args.dry_run:
        print(dry_run_report(cfg, grid))
        return 0

    # Cost is real money: never make calls implicitly. Live path arrives in M2.
    print("Live execution is not implemented yet (lands in M2).", file=sys.stderr)
    print("Use --dry-run to see the call plan and cost estimate.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
