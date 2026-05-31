"""Run output: raw JSONL (written BEFORE parsing), results CSV, run manifest.

TIER-1 rule: every call's full raw payload is appended to data/raw/*.jsonl before
any parsing/classification, so a classifier change never requires re-calling APIs.
Resumability reads completed cell keys back from that JSONL.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from eval.config import Config
from eval.schema import CSV_COLUMNS, CallResult


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


class RawWriter:
    """Append-only JSONL writer for verbatim request+response records."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")

    def append(self, record: dict) -> None:
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()  # durable before parsing — never lose raw data

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "RawWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def completed_cell_keys(raw_path: Path) -> set[str]:
    """Cell keys already recorded WITHOUT error (used to skip on resume)."""
    done: set[str] = set()
    if not raw_path.exists():
        return done
    with raw_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("error") is None and rec.get("cell_key"):
                done.add(rec["cell_key"])
    return done


def write_results_csv(path: Path, results: Iterable[CallResult]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([r.to_row() for r in results], columns=CSV_COLUMNS)
    df.to_csv(path, index=False)
    return len(df)


def write_manifest(
    path: Path,
    cfg: Config,
    run_id: str,
    model_snapshots: dict[str, str | None],
    n_cells: int,
    mode: str,
) -> None:
    """Reproducibility manifest (TIER-1 rule #4)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "config_hash": cfg.config_hash,
        "mode": mode,  # "mock" | "live"
        "provider": cfg.provider.model_dump(),
        "temperature": cfg.run.temperature,
        "max_tokens": cfg.run.max_tokens,
        "default_n_samples": cfg.run.n_samples,
        "models": [
            {
                "id": m.id,
                "region": m.region,
                "n_samples": m.n_samples or cfg.run.n_samples,
                "verified": m.verified,
                "snapshot": model_snapshots.get(m.id),
            }
            for m in cfg.models
        ],
        "n_cells": n_cells,
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
