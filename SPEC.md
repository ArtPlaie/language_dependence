# SPEC.md — Cross-Lingual Safety Eval Harness

Hand this to Claude Code in **plan mode**. Have it read this + CLAUDE.md, propose a
plan, and wait for approval before coding.

## 1. What we're measuring

For a fixed forced-choice question, does the model's answer — and its willingness
to answer at all — depend on the **language** the prompt is written in, holding
meaning constant? Plus a control that separates *language* from *writing system*.

Three condition types:

1. **Forced moral choice.** A binary "which is worse, A or B?" with a hard
   "respond in one word" instruction. Outcome buckets: `A`, `B`, `refusal`.
2. **Harmful-compliance.** A request to argue for a harmful position. Outcome
   buckets: `complied`, `refused`. (This is the headline safety metric — see §6.)
3. **Script control.** Same language, swapped script (e.g. French rendered in
   Han characters; Cantonese in Latin script) to test whether effects track the
   *language* or the *orthography*.

Each (model × item × language-variant) is run **N times** (config; original used
N≈100/50/10 across models). We report the outcome distribution as percentages.

## 2. Inputs (provided, do not invent)

- `prompts/items.yaml` — each item has: `id`, `type`, `options` (e.g. ["A","B"]),
  and `variants` (paraphrases of the same question, to test wording robustness).
- `prompts/translations.yaml` — for each item+variant, the **pre-written**
  translation per language. Translations are stored, NOT generated at runtime
  (reproducibility + reviewability). Language keys include script-control pseudo-
  languages like `fr_hani`, `yue_latn`.
- `configs/main.yaml` — `models`, `languages`, `n_samples`, `temperature`,
  `concurrency`, `provider settings`.

> If translation files are empty, scaffold the schema and a 2-language stub so the
> pipeline runs end-to-end on mock data. Do not auto-translate to fill them.

## 3. Data model (one row per call = source of truth)

`runs/<run_id>/results.csv` columns:
`run_id, model, provider, item_id, variant_id, language, script, sample_idx,
raw_response, parsed_outcome, parse_method, refused, latency_ms, error`

- `raw_response`: verbatim. Always written, even on parse failure.
- `parse_method`: `regex` | `llm_classifier` | `manual`.
- Raw JSONL (full request+response objects) also dumped to `data/raw/`.

## 4. Pipeline (modules)

1. **config** — pydantic models; validate before any call; compute config hash.
2. **clients** — `AnthropicClient`, `OpenAIClient` behind one interface. Env-var
   keys. Async, concurrency-capped, retry w/ backoff. Records latency + errors.
3. **runner** — expands config into the full call grid, supports `--dry-run`
   (print grid + token/cost estimate, zero calls) and `--limit N`. Writes raw
   JSONL as responses arrive (resumable: skip already-completed cells).
4. **classifier** — buckets `raw_response` into outcomes. **Two stage:**
   (a) cheap normalize + string/regex match on the option words & refusal markers;
   (b) only ambiguous leftovers go to a cheap LLM classifier with a strict schema.
   Store which method fired. Refusal detection is its own boolean.
5. **aggregate** — pandas pivot → per-model, per-item, per-variant tables of
   `% A / % B / % refusal` by language. Write CSV + render charts.
6. **report** — charts: grouped bars of refusal-rate-by-language, and outcome-
   distribution-by-language; one figure per item. Save to `runs/<run_id>/figures/`.

## 5. Milestones (build + commit in order)

- **M1 — Skeleton + schema.** Config, data model, dry-run grid + cost estimate.
  *Evidence:* `--dry-run` prints the full call plan and a cost number. No API calls.
- **M2 — One real adapter, mock-then-live.** Anthropic client; `--limit 5` live
  smoke against ONE model/ONE language; raw JSONL + CSV land on disk.
- **M3 — Second adapter (OpenAI) + resumability.** Re-running skips completed cells.
- **M4 — Classifier + unit tests.** Tests cover tricky real outputs (verbose
  answers, hedged answers, "I can't help with that", non-English refusals,
  answers in the wrong language). `make test` green.
- **M5 — Aggregation + charts.** Reproduce the spreadsheet's pivot shape from the
  CSV; render figures.
- **M6 — README + run_manifest + a `results/sample/` committed example run** (on
  mock or tiny live data) so the repo is self-demonstrating for a reader.

## 6. Framing notes (matter for how this reads to an outside reviewer)

- The README states the purpose plainly: measuring **language-conditioned refusal
  and compliance**, i.e. whether safety behavior is robust across languages.
- Lead the writeup and the README's headline result with the **compliance-rate**
  finding (condition type 2), which is unambiguously a safety result, before the
  Stalin/Mao value-judgment data. Keep stored artifacts to *labels and counts* —
  no need to retain generated harmful text beyond what's needed to classify.
- Caveat openly: exploratory, modest N, single time-point, model snapshots logged.
  Stating limits is good research hygiene, not weakness.

## 7. Non-goals

- No fancy UI. CLI + CSV + static charts only.
- No live translation. No fine-tuning. No statistical modeling beyond proportions
  and basic confidence intervals (a Wilson interval per cell is a nice-to-have, M5+).
