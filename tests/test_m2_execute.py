"""M2 tests: mock execution writes raw JSONL + CSV + manifest, and resumes."""

from __future__ import annotations

import asyncio
import json

import pytest

from eval.client import MockClient
from eval.config import load_config, load_items, load_translations
from eval.runner import build_grid, execute, results_from_raw, select_pending

CONFIG = "configs/main.yaml"


@pytest.fixture()
def loaded():
    cfg = load_config(CONFIG)
    return cfg, load_items(cfg.paths.items), load_translations(cfg.paths.translations)


def _run(cfg, items, tr, **kw):
    return asyncio.run(execute(cfg, items, tr, MockClient(), mode="mock", **kw))


def test_mock_run_writes_raw_csv_and_manifest(tmp_path, loaded):
    cfg, items, tr = loaded
    cfg.paths.runs_dir = str(tmp_path / "runs")
    cfg.paths.raw_dir = str(tmp_path / "raw")
    run_dir = _run(cfg, items, tr, limit=25, run_id="t1")

    raw = tmp_path / "raw" / "t1.jsonl"
    assert raw.exists()
    lines = [json.loads(l) for l in raw.read_text().splitlines() if l.strip()]
    assert len(lines) == 25
    # raw payload is retained verbatim, and CSV is derived from the raw log.
    assert all("raw_response" in r and "response_text" in r for r in lines)
    assert (run_dir / "results.csv").exists()
    assert (run_dir / "run_manifest.json").exists()
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["mode"] == "mock" and manifest["n_cells"] == 25


def test_resume_skips_completed_cells(tmp_path, loaded):
    cfg, items, tr = loaded
    cfg.paths.runs_dir = str(tmp_path / "runs")
    cfg.paths.raw_dir = str(tmp_path / "raw")
    _run(cfg, items, tr, limit=20, run_id="t2")
    raw = tmp_path / "raw" / "t2.jsonl"
    assert len(raw.read_text().splitlines()) == 20
    # Re-run same limit/run_id: nothing new appended.
    _run(cfg, items, tr, limit=20, run_id="t2")
    assert len(raw.read_text().splitlines()) == 20
    # Grow the cap: only the new cells are appended.
    _run(cfg, items, tr, limit=35, run_id="t2")
    assert len(raw.read_text().splitlines()) == 35


def test_live_mode_skips_mock_and_unverified(loaded):
    cfg, items, tr = loaded
    grid = build_grid(cfg, items, tr, limit=300)
    # All models are verified:false in the shipped config, so live (without override)
    # selects nothing; mock mode selects everything not already done.
    assert select_pending(cfg, grid, set(), "live", allow_unverified=False) == []
    assert len(select_pending(cfg, grid, set(), "mock", allow_unverified=False)) == 300


def test_mock_distribution_varies_within_a_cell(tmp_path, loaded):
    cfg, items, tr = loaded
    cfg.paths.runs_dir = str(tmp_path / "runs")
    cfg.paths.raw_dir = str(tmp_path / "raw")
    _run(cfg, items, tr, limit=60, run_id="t3")
    rows = results_from_raw("t3", tmp_path / "raw" / "t3.jsonl")
    # Within a single (model,item,variant,language) cell there should be >1 distinct answer.
    by_cell: dict[tuple, set[str]] = {}
    for r in rows:
        key = (r.model, r.item_id, r.variant_id, r.language)
        by_cell.setdefault(key, set()).add(r.raw_response)
    assert any(len(v) > 1 for v in by_cell.values())
