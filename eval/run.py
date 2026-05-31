"""CLI entry point: ``python -m eval.run`` (SPEC §4.3).

- ``--dry-run``: print the call plan + cost estimate, make ZERO API calls.
- otherwise: execute the grid. Uses OpenRouter when the API key is set, else falls
  back to the offline MockClient so the pipeline runs end-to-end ("mock-then-live").
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from eval.client import MockClient, OpenRouterClient
from eval.config import load_config, load_items, load_translations
from eval.runner import build_grid, dry_run_report, execute


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.run", description=__doc__)
    parser.add_argument("--config", required=True, help="path to configs/*.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="print call plan + cost estimate, make ZERO API calls")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the grid to the first N cells")
    parser.add_argument("--mock", action="store_true",
                        help="force the offline MockClient even if a key is set")
    parser.add_argument("--allow-unverified", action="store_true",
                        help="(live) also call models whose slug is not yet verified")
    parser.add_argument("--resume", metavar="RUN_ID", default=None,
                        help="resume a run id: skip cells already logged without error")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    items = load_items(cfg.paths.items)
    translations = load_translations(cfg.paths.translations)

    if args.dry_run:
        grid = build_grid(cfg, items, translations, limit=args.limit)
        print(dry_run_report(cfg, grid))
        return 0

    # Choose client: live OpenRouter if a key exists and --mock not forced, else mock.
    has_key = bool(os.environ.get(cfg.provider.api_key_env))
    use_live = has_key and not args.mock
    if use_live:
        client = OpenRouterClient.from_env(
            cfg.provider.api_key_env, cfg.provider.base_url, cfg.run.concurrency,
        )
        mode = "live"
    else:
        client = MockClient()
        mode = "mock"
        if not args.mock:
            print(f"note: {cfg.provider.api_key_env} not set — running in MOCK mode.",
                  file=sys.stderr)

    async def _go() -> int:
        try:
            run_dir = await execute(
                cfg, items, translations, client,
                mode=mode, limit=args.limit,
                allow_unverified=args.allow_unverified, run_id=args.resume,
            )
        finally:
            if isinstance(client, OpenRouterClient):
                await client.aclose()
        print(f"[{mode}] run complete -> {run_dir}")
        print(f"  results : {run_dir / 'results.csv'}")
        print(f"  manifest: {run_dir / 'run_manifest.json'}")
        return 0

    return asyncio.run(_go())


if __name__ == "__main__":
    raise SystemExit(main())
