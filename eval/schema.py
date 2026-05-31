"""Data model: the tidy long-format row that is the source of truth.

One :class:`CallResult` == one model call == one CSV row (SPEC §3). Pivot tables
and charts are derived from these rows and never the other way around.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Columns of runs/<run_id>/results.csv, in order (SPEC §3).
CSV_COLUMNS: list[str] = [
    "run_id", "model", "provider", "item_id", "variant_id", "language",
    "script", "sample_idx", "raw_response", "parsed_outcome", "parse_method",
    "refused", "latency_ms", "error",
]

ParseMethod = Literal["regex", "llm_classifier", "manual", "unparsed"]


class CallSpec(BaseModel):
    """One cell of the expanded grid: a single intended model call.

    ``cell_key`` uniquely identifies the (model, item, variant, language,
    sample) tuple and is used for resumability (skip already-completed cells).
    """

    model: str
    provider: str
    item_id: str
    variant_id: str
    language: str          # config code, e.g. "fr" or "fr_hani"
    script: str            # human-readable script name
    sample_idx: int
    prompt: str            # the exact text sent to the model ("" if not translated yet)
    is_mock: bool = False   # True when no real translation/key is available

    @property
    def cell_key(self) -> str:
        return f"{self.model}|{self.item_id}|{self.variant_id}|{self.language}|{self.sample_idx}"


class CallResult(BaseModel):
    """A completed (or failed) call. Serializes directly to one CSV row."""

    run_id: str
    model: str
    provider: str
    item_id: str
    variant_id: str
    language: str
    script: str
    sample_idx: int
    raw_response: str = ""
    parsed_outcome: str | None = None
    parse_method: ParseMethod = "unparsed"
    refused: bool | None = None
    latency_ms: int | None = None
    error: str | None = None

    def to_row(self) -> dict[str, object]:
        return {c: getattr(self, c) for c in CSV_COLUMNS}
