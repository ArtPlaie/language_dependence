# Cross-Lingual Safety Eval Harness

Measuring **language-conditioned refusal and compliance**: does a model's
willingness to answer — and which answer it gives — depend on the *language* a
prompt is written in, holding meaning constant? A script-control condition
separates *language* effects from *writing-system* effects.

This is exploratory AI-safety evaluation work (cross-lingual refusal robustness /
jailbreak susceptibility). Prompts are fixed experimental stimuli; the harness
stores only labels and counts of model behavior.

> Status: under construction. See `SPEC.md` for the design and milestones,
> `CLAUDE.md` for the working rules. README headline results land in M6.

## Quickstart

```bash
make install                 # uv sync (deps + dev)
make dry                     # full call plan + cost estimate, ZERO API calls
make smoke                   # tiny live smoke (needs OPENROUTER_API_KEY; mock fallback)
make test                    # unit tests (classifier + aggregation)
```

API keys come from env vars only (`OPENROUTER_API_KEY`); copy `.env.example` to
`.env` (gitignored). Every paid command supports `--dry-run` and `--limit N`.
