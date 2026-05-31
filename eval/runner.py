"""Runner: expand config into the full call grid, project cost, dry-run (SPEC §4.3).

M1 scope: grid expansion + `--dry-run` plan/cost + `--limit`. Live execution
(writing raw JSONL + results.csv) lands in M2; calling it here raises clearly.
"""

from __future__ import annotations

from collections import Counter

from eval.config import Config, ItemSet, Translations
from eval.languages import resolve as resolve_language
from eval.schema import CallSpec


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
