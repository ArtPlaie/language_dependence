"""CLI: re-classify a run's raw log into results.csv (SPEC §4.4).

    python -m eval.classify --run <run_id> [--config configs/main.yaml] [--llm-model SLUG]

Reads ``data/raw/<run_id>.jsonl`` from disk and rebuilds ``runs/<run_id>/results.csv``
with ``parsed_outcome``/``parse_method``/``refused`` filled in. TIER-1: this never
re-calls the API for the responses themselves — a classifier change is a pure
re-parse of the raw log. ``--llm-model`` optionally enables the stage-2 LLM
fallback for the ambiguous leftovers (this DOES make paid calls, one per
ambiguous cell, and requires the provider key + network).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from eval.classifier import classify_results, make_llm_fallback
from eval.client import OpenRouterClient
from eval.config import load_config, load_items
from eval.runner import results_from_raw
from eval.storage import write_results_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.classify", description=__doc__)
    parser.add_argument("--run", required=True, metavar="RUN_ID", help="run id to (re)classify")
    parser.add_argument("--config", default="configs/main.yaml", help="path to configs/*.yaml")
    parser.add_argument("--llm-model", default=None,
                        help="(optional) OpenRouter slug for the stage-2 LLM fallback on "
                             "ambiguous cells — makes paid calls")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    items = load_items(cfg.paths.items)
    raw_path = Path(cfg.paths.raw_dir) / f"{args.run}.jsonl"
    if not raw_path.exists():
        print(f"error: no raw log at {raw_path}", file=sys.stderr)
        return 1

    rows = results_from_raw(args.run, raw_path)

    fallback = None
    client = None
    if args.llm_model:
        key = os.environ.get(cfg.provider.api_key_env)
        if not key:
            print(f"error: --llm-model needs {cfg.provider.api_key_env} set", file=sys.stderr)
            return 1
        client = OpenRouterClient.from_env(
            cfg.provider.api_key_env, cfg.provider.base_url, cfg.run.concurrency,
        )
        fallback = make_llm_fallback(client, args.llm_model)

    summary = classify_results(rows, items, llm_fallback=fallback)

    run_dir = Path(cfg.paths.runs_dir) / args.run
    n = write_results_csv(run_dir / "results.csv", rows)

    outcomes = Counter(r.parsed_outcome for r in rows)
    refusals = sum(1 for r in rows if r.refused)
    print(f"classified {n} rows from {raw_path}")
    print(f"  by method : {dict(summary)}")
    print(f"  refusals  : {refusals}/{n}")
    print(f"  outcomes  : {dict(outcomes)}")
    print(f"  -> {run_dir / 'results.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
