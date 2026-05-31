# CLAUDE.md — Multilingual Safety Eval

Persistent context for this repo. Read top-down; rules near the top matter most.

## TIER 1 — HARD RULES (check before every action)

1. **Never lose raw data.** Every model call's full raw response is appended to
   `data/raw/*.jsonl` *before* any parsing/classification. Parsing reads from
   disk, never from memory mid-run. A classifier change must NOT require re-calling APIs.
2. **No secrets in code or commits.** API keys come from env vars only
   (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). `.env` is gitignored.
3. **Cost is real money.** Any command that hits a paid API must support
   `--dry-run` (print the call plan + estimated cost, make zero calls) and
   `--limit N`. Default to dry-run if the user is ambiguous.
4. **Reproducibility is the product.** Every run writes a `run_manifest.json`:
   config hash, model snapshot IDs, timestamp, git commit, N, temperature.
5. **Show evidence, don't assert success.** When you finish a milestone, paste
   the command you ran and its actual output. Don't say "it works."

## TIER 2 — WORKFLOW

- Use **plan mode** for anything 3+ steps. Read `SPEC.md`, propose a plan, wait
  for my approval before writing code.
- Build in the **milestones** listed in SPEC.md, in order. Each milestone must be
  independently runnable and committed before starting the next.
- After each milestone: run it, show output, `git commit` with a clear message.
- If you hit ambiguity, STOP and ask. Do not invent prompt content or languages.

## TIER 3 — PROJECT CONTEXT

This is a research harness measuring how an LLM's behavior on forced-choice moral
questions changes with the **language** (and **script**) of an otherwise identical
prompt. Two signals per item: (a) which option it picks, (b) whether it refuses.
A separate condition measures **compliance rate** on a harmful request across
languages. Output mirrors a hand-built spreadsheet: per-model pivot tables of
{option_A %, option_B %, refusal %} by language.

This is legitimate AI-safety evaluation work (cross-lingual refusal robustness /
jailbreak susceptibility). Prompts are provided in `prompts/`. Do not editorialize
the prompt content; treat it as fixed experimental stimuli.

## COMMANDS

```bash
make install            # uv/pip install deps
make test               # run pytest (classifier + aggregation unit tests)
python -m eval.run --config configs/main.yaml --dry-run        # plan + cost only
python -m eval.run --config configs/main.yaml --limit 5        # tiny live smoke
python -m eval.run --config configs/main.yaml                  # full run
python -m eval.aggregate runs/<run_id>                         # tables + charts
```

## STACK

- Python 3.11+, `uv` for env. `httpx` (async), `pydantic` (config/schema),
  `pandas` (aggregation), `matplotlib` (charts), `pytest`.
- Provider adapters behind one `Client.complete(model, messages) -> str` interface.
- Async with a concurrency cap + exponential backoff on 429/5xx.

## CONVENTIONS

- Source of truth for results = one tidy long-format CSV, one row per call.
- Pivot tables and charts are derived artifacts, regenerable from the CSV.
- Keep functions small and pure where possible so the classifier is unit-testable.
- Type hints everywhere; no bare `except`.
