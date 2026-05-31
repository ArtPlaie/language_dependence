"""Runner: expand config into the full call grid, project cost, dry-run (SPEC §4.3).

M1 scope: grid expansion + `--dry-run` plan/cost + `--limit`. Live execution
(writing raw JSONL + results.csv) lands in M2; calling it here raises clearly.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from eval.client import Client
from eval.config import Config, ItemSet, Translations
from eval.languages import resolve as resolve_language
from eval.schema import CallResult, CallSpec
from eval.storage import (
    RawWriter,
    completed_cell_keys,
    new_run_id,
    write_manifest,
    write_results_csv,
)


def build_grid(
    cfg: Config,
    items: ItemSet,
    translations: Translations,
    limit: int | None = None,
) -> list[CallSpec]:
    """Expand (model × item × variant × language × sample) into CallSpecs.

    A cell whose translation is missing (``TODO_TRANSLATE``) is marked
    ``is_mock`` with an empty prompt, so the grid is always complete and the
    pipeline can run end-to-end even before every language is translated.
    """
    specs: list[CallSpec] = []
    for model in cfg.models:
        n_samples = model.n_samples or cfg.run.n_samples
        for item in items.items:
            for variant in item.variants:
                for code in cfg.languages.for_item(item.id):
                    lang = resolve_language(code)
                    text = translations.lookup(item.id, variant.id, code)
                    for sample_idx in range(n_samples):
                        specs.append(
                            CallSpec(
                                model=model.id,
                                provider=cfg.provider.name,
                                item_id=item.id,
                                variant_id=variant.id,
                                language=code,
                                script=lang.script,
                                sample_idx=sample_idx,
                                prompt=text or "",
                                is_mock=text is None,
                            )
                        )
    if limit is not None:
        specs = specs[:limit]
    return specs


def select_pending(
    cfg: Config,
    grid: list[CallSpec],
    done: set[str],
    mode: str,
    allow_unverified: bool,
) -> list[CallSpec]:
    """Filter the grid to the cells we will actually call this invocation.

    - already-completed cells (by cell_key) are skipped (resumability);
    - in live mode, untranslated (mock) cells and unverified models are skipped
      (the latter unless ``allow_unverified``); mock mode runs everything.
    """
    verified = {m.id: m.verified for m in cfg.models}
    pending: list[CallSpec] = []
    for spec in grid:
        if spec.cell_key in done:
            continue
        if mode == "live":
            if spec.is_mock:
                continue
            if not allow_unverified and not verified.get(spec.model, False):
                continue
        pending.append(spec)
    return pending


def results_from_raw(run_id: str, raw_path: Path) -> list[CallResult]:
    """Rebuild CSV rows from the verbatim JSONL (parsing reads from disk, not memory).

    M2 leaves outcomes unparsed; the M4 classifier will fill parsed_outcome/refused
    from this same raw log without re-calling any API.
    """
    rows: list[CallResult] = []
    if not raw_path.exists():
        return rows
    with raw_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rows.append(
                CallResult(
                    run_id=run_id,
                    model=rec["model"],
                    provider=rec["provider"],
                    item_id=rec["item_id"],
                    variant_id=rec["variant_id"],
                    language=rec["language"],
                    script=rec["script"],
                    sample_idx=rec["sample_idx"],
                    raw_response=rec.get("response_text", ""),
                    parsed_outcome=None,
                    parse_method="unparsed",
                    refused=None,
                    latency_ms=rec.get("latency_ms"),
                    error=rec.get("error"),
                )
            )
    return rows


async def execute(
    cfg: Config,
    items: ItemSet,
    translations: Translations,
    client: Client,
    *,
    mode: str,
    limit: int | None = None,
    allow_unverified: bool = False,
    run_id: str | None = None,
) -> Path:
    """Run the grid: append raw JSONL as responses arrive, then (re)build CSV + manifest.

    Resumable: pass an existing ``run_id`` to skip cells already logged without error.
    """
    run_id = run_id or new_run_id()
    raw_path = Path(cfg.paths.raw_dir) / f"{run_id}.jsonl"
    run_dir = Path(cfg.paths.runs_dir) / run_id

    grid = build_grid(cfg, items, translations, limit=limit)
    done = completed_cell_keys(raw_path)
    pending = select_pending(cfg, grid, done, mode, allow_unverified)
    item_options = {it.id: it.options for it in items.items}

    async def run_one(spec: CallSpec) -> tuple[CallSpec, object]:
        content = spec.prompt or "(mock: untranslated cell)"
        messages = [{"role": "user", "content": content}]
        choices = item_options.get(spec.item_id, ["A", "B"])
        comp = await client.complete(
            spec.model, messages,
            temperature=cfg.run.temperature,
            max_tokens=cfg.run.max_tokens,
            seed=cfg.run.seed,
            choices=choices,
            seed_key=spec.cell_key,
        )
        return spec, comp

    model_snapshots: dict[str, str | None] = {}
    writer = RawWriter(raw_path)
    try:
        tasks = [asyncio.create_task(run_one(s)) for s in pending]
        for fut in asyncio.as_completed(tasks):
            spec, comp = await fut
            # TIER-1: write verbatim raw BEFORE any parsing.
            writer.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "cell_key": spec.cell_key,
                "model": spec.model,
                "provider": spec.provider,
                "item_id": spec.item_id,
                "variant_id": spec.variant_id,
                "language": spec.language,
                "script": spec.script,
                "sample_idx": spec.sample_idx,
                "is_mock": spec.is_mock,
                "prompt": content_for(spec),
                "response_text": comp.text,
                "model_snapshot": comp.model_snapshot,
                "latency_ms": comp.latency_ms,
                "error": comp.error,
                "raw_response": comp.raw,
            })
            model_snapshots[spec.model] = comp.model_snapshot
    finally:
        writer.close()

    # Source of truth = raw JSONL on disk; CSV is derived from it (includes resumed cells).
    rows = results_from_raw(run_id, raw_path)
    write_results_csv(run_dir / "results.csv", rows)
    write_manifest(run_dir / "run_manifest.json", cfg, run_id, model_snapshots, len(rows), mode)
    return run_dir


def content_for(spec: CallSpec) -> str:
    return spec.prompt or "(mock: untranslated cell)"


def estimate_cost(cfg: Config, grid: list[CallSpec]) -> dict[str, object]:
    """Project USD cost from per-model token-price estimates (dry-run only)."""
    pt = cfg.cost.est_prompt_tokens
    ot = cfg.cost.est_output_tokens
    per_model: dict[str, float] = {}
    live_calls = 0
    for spec in grid:
        if spec.is_mock:
            continue  # mock cells make no paid call
        live_calls += 1
        price = cfg.cost.price(spec.model)
        cost = (pt * price.input + ot * price.output) / 1_000_000
        per_model[spec.model] = per_model.get(spec.model, 0.0) + cost
    return {
        "total_usd": round(sum(per_model.values()), 4),
        "by_model_usd": {m: round(v, 4) for m, v in per_model.items()},
        "live_calls": live_calls,
        "mock_calls": len(grid) - live_calls,
        "assumed_tokens": {"prompt": pt, "output": ot},
    }


def dry_run_report(cfg: Config, grid: list[CallSpec]) -> str:
    """Human-readable call plan + cost projection. Makes ZERO API calls."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("DRY RUN — call plan (no API calls made)")
    lines.append("=" * 72)
    lines.append(f"config_hash : {cfg.config_hash}")
    lines.append(f"provider    : {cfg.provider.name} ({cfg.provider.base_url})")
    lines.append(f"temperature : {cfg.run.temperature}   max_tokens: {cfg.run.max_tokens}"
                 f"   concurrency: {cfg.run.concurrency}")
    lines.append("")

    by_model = Counter(s.model for s in grid)
    by_item = Counter(s.item_id for s in grid)
    by_lang = Counter(s.language for s in grid)
    mock = sum(1 for s in grid if s.is_mock)

    lines.append(f"TOTAL CELLS : {len(grid)}   (live: {len(grid) - mock}   mock/untranslated: {mock})")
    lines.append("")
    lines.append("by model:")
    for m, n in by_model.items():
        lines.append(f"  {m:<32} {n:>7}")
    lines.append("by item:")
    for i, n in sorted(by_item.items()):
        lines.append(f"  {i:<32} {n:>7}")
    lines.append("by language:")
    for code, n in sorted(by_lang.items()):
        lang = resolve_language(code)
        tag = " [script-control]" if lang.is_control else ""
        lines.append(f"  {code:<10} {lang.name} in {lang.script}{tag}: {n}")

    cost = estimate_cost(cfg, grid)
    lines.append("")
    lines.append("-" * 72)
    lines.append("COST ESTIMATE (rough; assumes "
                 f"{cost['assumed_tokens']['prompt']} prompt + "
                 f"{cost['assumed_tokens']['output']} output tokens/call)")
    for m, c in cost["by_model_usd"].items():
        lines.append(f"  {m:<32} ${c:>8.4f}")
    lines.append(f"  {'TOTAL (live calls only)':<32} ${cost['total_usd']:>8.4f}")
    lines.append(f"  live calls: {cost['live_calls']}   mock calls: {cost['mock_calls']}")
    lines.append("-" * 72)
    return "\n".join(lines)
