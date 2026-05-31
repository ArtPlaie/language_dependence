.PHONY: install test dry smoke run aggregate clean

install:
	uv sync --extra dev

test:
	uv run pytest

# M1 evidence: full call plan + cost estimate, zero API calls.
dry:
	uv run python -m eval.run --config configs/main.yaml --dry-run

# Tiny live smoke (needs OPENROUTER_API_KEY). Falls back to mock if unset.
smoke:
	uv run python -m eval.run --config configs/main.yaml --limit 5

run:
	uv run python -m eval.run --config configs/main.yaml

aggregate:
	uv run python -m eval.aggregate $(RUN)

clean:
	rm -rf .pytest_cache __pycache__ */__pycache__
