"""CLI: validate configured model slugs against the live OpenRouter catalog.

    python -m eval.validate_models [--config configs/main.yaml] [--json]

Read-only: a single GET to ``/models`` (free, no completion is requested). For each
configured slug it reports FOUND/MISSING, the real per-1M-token prices, and — for
missing slugs — the closest available alternatives. This is the input for flipping
``verified: true`` and pulling real ``cost.by_model`` prices into the config.

It deliberately does NOT rewrite the YAML (that would clobber the file's comments);
it prints a ready-to-paste price/verified summary instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from difflib import get_close_matches

import httpx

from eval.config import load_config


def fetch_catalog(base_url: str, api_key: str | None) -> dict[str, dict]:
    """Return ``{slug: model_record}`` from the live /models endpoint."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=30.0)
    resp.raise_for_status()
    return {m["id"]: m for m in resp.json()["data"]}


def _per_million(record: dict) -> tuple[float, float]:
    """OpenRouter prices are per-token strings; convert to USD per 1M tokens."""
    p = record.get("pricing", {})
    return float(p.get("prompt", 0)) * 1_000_000, float(p.get("completion", 0)) * 1_000_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.validate_models", description=__doc__)
    parser.add_argument("--config", default="configs/main.yaml")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    key = os.environ.get(cfg.provider.api_key_env)
    try:
        catalog = fetch_catalog(cfg.provider.base_url, key)
    except httpx.HTTPError as exc:
        print(f"error: could not reach {cfg.provider.base_url}/models: {exc!r}", file=sys.stderr)
        return 2

    all_slugs = list(catalog)
    report: list[dict] = []
    for m in cfg.models:
        if m.id in catalog:
            pin, pout = _per_million(catalog[m.id])
            report.append({
                "id": m.id, "found": True, "input": round(pin, 4), "output": round(pout, 4),
                "canonical": catalog[m.id].get("canonical_slug"), "suggestions": [],
            })
        else:
            report.append({
                "id": m.id, "found": False, "input": None, "output": None,
                "canonical": None, "suggestions": get_close_matches(m.id, all_slugs, n=4, cutoff=0.4),
            })

    if args.json:
        print(json.dumps({"n_catalog": len(catalog), "models": report}, indent=2))
        return 0

    found = [r for r in report if r["found"]]
    missing = [r for r in report if not r["found"]]
    print(f"OpenRouter catalog: {len(catalog)} models. Configured: {len(report)} "
          f"({len(found)} found, {len(missing)} missing).\n")
    print(f"{'STATUS':<8}{'SLUG':<42}{'$in/M':>9}{'$out/M':>9}")
    print("-" * 68)
    for r in report:
        if r["found"]:
            print(f"{'FOUND':<8}{r['id']:<42}{r['input']:>9}{r['output']:>9}")
        else:
            print(f"{'MISSING':<8}{r['id']:<42}{'-':>9}{'-':>9}")
            for s in r["suggestions"]:
                print(f"{'':<8}  ~ {s}")

    if found:
        print("\n# ready-to-paste cost.by_model prices for the FOUND slugs:")
        for r in found:
            print(f"#   {r['id']}: {{input: {r['input']}, output: {r['output']}}}")
    if missing:
        print(f"\n{len(missing)} slug(s) absent — replace or drop them (see suggestions above).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
