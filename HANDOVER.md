# SESSION HANDOVER — Cross-Lingual Safety Eval Harness

> Read this first when resuming in a new session. It captures state, decisions,
> blockers, and the exact next steps. Pair it with `CLAUDE.md` (rules) and
> `SPEC.md` (design + milestones).

_Last updated: 2026-05-31 · Branch: `claude/relaxed-maxwell-BEdrp`_

---

## 1. TL;DR — where we are

The harness measures **language-conditioned refusal & compliance**: does a model's
answer (and willingness to answer) change with the *language*/­*script* of an
otherwise identical prompt. Built milestone-by-milestone per `SPEC.md`.

| Milestone | Status | Evidence |
|---|---|---|
| Docs (CLAUDE/SPEC) | ✅ committed | in repo |
| **M1** skeleton + schema + dry-run | ✅ done | `make dry` → 22,880 cells + ~$2.3 cost, **0 API calls** |
| **M2 (mock half)** execute + raw JSONL + CSV + manifest + resume | ✅ done | mock smoke writes JSONL→CSV, resume +0 then 120→200; **10/10 tests** |
| **M2 (live half)** real OpenRouter call | ⛔ **BLOCKED** | env network policy blocks `openrouter.ai` |
| M3 resumability | ✅ effectively done (`--resume`) — needs live multi-model confirm |
| **M4** classifier + tests | ⬜ next, **doable offline** on the raw log |
| M5 aggregation + charts | ⬜ | |
| M6 README headline + sample run | ⬜ | |

**The one blocker:** outbound network to `openrouter.ai` is denied
(`Host not in allowlist`), so no live calls and no slug/price validation can
happen from inside the cloud session yet.

---

## 2. What the user must do to unblock LIVE runs

1. **Open network access** (web UI): cloud icon (shows current env name) → hover env
   → gear/settings → **Network access: Custom** → in **Allowed domains** add:
   ```
   openrouter.ai
   *.openrouter.ai
   ```
   ✅ also check *"Also include default list of common package managers"* (else
   PyPI/uv break). Save.
2. **Start a NEW session** on branch `claude/relaxed-maxwell-BEdrp`. Editing allowed
   hosts rebuilds the env cache + re-runs setup; a *resumed* session does **not**
   pick it up. (Docs: https://code.claude.com/docs/en/claude-code-on-the-web#network-access)
3. **Set the API key** as an env var in the environment settings:
   `OPENROUTER_API_KEY=...` (or a local `.env` — `.env` is gitignored).
4. (Optional, for real multilingual) **fill translations**: replace `TODO_TRANSLATE`
   placeholders in `prompts/translations.yaml`. Until then only `en`/`fr` cells are
   "live"; the rest run in mock.

---

## 3. First actions for the NEXT session (in order)

1. `git pull` / confirm on branch `claude/relaxed-maxwell-BEdrp`; `uv sync --extra dev`.
2. **Verify network is open:**
   `curl -sL https://openrouter.ai/api/v1/models -w "\n%{http_code}\n" | tail -1`
   - `200` → proceed. `403 Host not in allowlist` → still blocked; tell user.
3. **Validate model slugs** against the live `/models` list (slugs below are UNVERIFIED).
   Build the planned `eval validate-models` command (see §6) OR do an ad-hoc check.
   Confirm/replace: `openai/gpt-5.5`, `google/gemini-3.1-pro`,
   `meta-llama/llama-3.1-405b-instruct`, `qwen/qwen-max`, `deepseek/deepseek-chat`,
   `inceptionai/jais-30b-chat` (Jais — likely absent), `sarvamai/sarvam-m` (Sarvam — verify).
   Pull **real prices** into `configs/main.yaml` `cost.by_model` and flip `verified: true`.
4. **Live smoke:** `uv run python -m eval.run --config configs/main.yaml --limit 5`
   (with key set). Confirm raw JSONL + CSV land on disk. This closes M2-live.
5. Then continue with **M4 (classifier)** — or do M4 first while network is being sorted;
   it's fully offline.

---

## 4. Architecture (as built)

```
configs/main.yaml          # run/provider/models/languages/cost — validated + hashed
prompts/items.yaml         # REAL items/variants transcribed from the 2023 Excel
prompts/translations.yaml  # en/fr source text + TODO_TRANSLATE placeholders
eval/
  languages.py   # base-lang + script registry; resolves script-control pseudo-langs
  schema.py      # CallSpec (grid cell) + CallResult (CSV row, SPEC §3 columns)
  config.py      # pydantic models, validation, config_hash, loaders, TODO_TRANSLATE
  client.py      # Client protocol; OpenRouterClient (async/backoff) + MockClient
  storage.py     # RawWriter (JSONL before parsing), CSV writer, manifest, resume keys
  runner.py      # build_grid, dry_run_report, estimate_cost, select_pending,
                 #   results_from_raw, execute()
  run.py         # CLI: --dry-run / --mock / --limit / --resume / --allow-unverified
tests/           # test_m1_scaffold.py, test_m2_execute.py  (10 tests, green)
data/reference/Data_LLM_by_language.xlsx   # original study data (ingest in M5/M6)
data/raw/<run_id>.jsonl    # gitignored — verbatim payloads, written BEFORE parsing
runs/<run_id>/             # gitignored — results.csv + run_manifest.json
```

**Data flow (TIER-1 honored):** call → append verbatim raw to `data/raw/*.jsonl`
(flushed) → CSV is *derived from the JSONL on disk*, never from memory. A classifier
change (M4) re-reads the JSONL; it never re-calls the API.

---

## 5. Key decisions made (and why)

- **Provider = OpenRouter only.** One `OpenRouterClient` behind `Client.complete()`;
  "models" are OpenRouter slugs. Key: `OPENROUTER_API_KEY`. (User's call.)
- **Models = full Claude range + GPT-5.5 + Gemini 3.1 + big Mistral + big Llama +
  2 big Chinese (Qwen, DeepSeek) + Arabic (Jais) + Hindi (Sarvam).** Grouped by
  `region`. **All `verified: false`** until slugs are checked live.
- **`n_samples`**: global default `20` in `run:`, per-model override allowed. (Original
  study used ~100/50/10; tune later. 20 keeps the 11-model grid affordable.)
- **No inventing prompts/translations** (CLAUDE rule). Items + en/fr text are
  transcribed verbatim from the Excel; other languages are explicit `TODO_TRANSLATE`.
- **Mock-then-live**: untranslated cells / no-key → MockClient, so the whole pipeline
  runs offline. MockClient seeds on `cell_key` → realistic per-cell distributions.
- **Live safety gate**: live mode skips `is_mock` cells and `verified:false` models
  unless `--allow-unverified`. Dry-run defaults protect against accidental spend.
- **Sensitive content**: the compliance items (LGBTQ+/religion/politics) are the
  user's existing AI-safety stimuli measuring cross-lingual refusal robustness. We
  store only labels/counts; we do not expand/generate the harmful content.

---

## 6. TODO / not yet built

- [ ] **`eval validate-models`** (planned, needs network): query OpenRouter `/models`,
      confirm each slug exists, write real `cost.by_model` prices, flip `verified`.
      Drop/flag slugs that don't exist (expect Jais, possibly Sarvam).
- [ ] **M2-live smoke** once network + key are in place.
- [ ] **M4 classifier** (`eval/classifier.py`): two-stage — (a) normalize + regex match
      on option words & refusal markers; (b) ambiguous leftovers → cheap LLM classifier
      with strict schema. Set `parsed_outcome`, `parse_method`, `refused`. Re-reads
      `data/raw/*.jsonl`. Tests must cover: verbose answers, hedged answers,
      "I can't help with that", **non-English refusals**, answers in the wrong language.
- [ ] **M5 aggregate** (`eval/aggregate.py`): pandas pivot → `%A/%B/%refusal` by language
      per (model,item,variant); Wilson CI per cell; CSV + charts (`eval/report.py`,
      one figure per item). Reproduce the Excel pivot shape; ingest the historical
      Excel into the tidy CSV as a validation/`results/historical/` reference.
- [ ] **M6**: README headline = the **compliance-rate** finding (lead with it, before
      the Stalin/Mao value data); commit a `results/sample/` example run (mock or tiny live).

---

## 7. Commands

```bash
make install      # uv sync --extra dev
make test         # pytest (currently 10 green)
make dry          # full call plan + cost, ZERO API calls   (M1 evidence)
uv run python -m eval.run --config configs/main.yaml --mock --limit 30   # offline smoke
uv run python -m eval.run --config configs/main.yaml --limit 5           # LIVE (needs key+network)
uv run python -m eval.run --config configs/main.yaml --resume <RUN_ID>   # resume a run
```

Outputs: `data/raw/<run_id>.jsonl` (raw), `runs/<run_id>/results.csv`,
`runs/<run_id>/run_manifest.json`. Both `data/raw/` and `runs/` are gitignored.

---

## 8. Git state

- Branch: `claude/relaxed-maxwell-BEdrp` (push here only; never elsewhere without OK).
- Commit messages end with the session URL footer (per harness convention).
- Recent commits: docs → M1 → model lineup → client.py (wip) → M2 mock half.
- Push with `git push -u origin claude/relaxed-maxwell-BEdrp` (retry w/ backoff on net err).

## 9. Open questions for the user

1. Confirm/replace the **unverified slugs** (esp. GPT-5.5, Gemini 3.1, Llama-4 vs 3.1-405B).
2. **Jais/Sarvam**: keep as "best effort, drop if absent on OpenRouter"? (current assumption: yes.)
3. Final **`n_samples`** per model for the real run (cost vs. statistical power).
4. Will the user provide **real translations**, or do we run en/fr-only live + mock elsewhere?
