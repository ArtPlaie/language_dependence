"""Config + stimuli loading, validation, and config hashing (SPEC §4.1).

Everything here is pure and side-effect-free apart from reading files. Validation
runs before any API call; unknown language codes, item types, or malformed stimuli
raise immediately.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from eval.languages import Language, resolve as resolve_language

# Sentinel used in translations.yaml for cells that have no real translation yet.
TODO_TRANSLATE = "TODO_TRANSLATE"


# --------------------------------------------------------------------------- config
class RunSettings(BaseModel):
    temperature: float = 1.0
    max_tokens: int = 64
    concurrency: int = 8
    seed: int | None = None


class ProviderSettings(BaseModel):
    name: str = "openrouter"
    base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"


class ModelSpec(BaseModel):
    id: str
    n_samples: int = Field(gt=0)


class Price(BaseModel):
    input: float
    output: float


class CostModel(BaseModel):
    default: Price
    by_model: dict[str, Price] = Field(default_factory=dict)
    est_prompt_tokens: int = 120
    est_output_tokens: int = 8

    def price(self, model_id: str) -> Price:
        return self.by_model.get(model_id, self.default)


class LanguageGrid(BaseModel):
    default: list[str]
    per_item: dict[str, list[str]] = Field(default_factory=dict)

    def for_item(self, item_id: str) -> list[str]:
        return self.per_item.get(item_id, self.default)


class Paths(BaseModel):
    items: str = "prompts/items.yaml"
    translations: str = "prompts/translations.yaml"
    runs_dir: str = "runs"
    raw_dir: str = "data/raw"


class Config(BaseModel):
    run: RunSettings
    provider: ProviderSettings
    models: list[ModelSpec]
    languages: LanguageGrid
    cost: CostModel
    paths: Paths = Field(default_factory=Paths)
    config_hash: str = ""

    @model_validator(mode="after")
    def _validate_language_codes(self) -> "Config":
        codes = set(self.languages.default)
        for lst in self.languages.per_item.values():
            codes.update(lst)
        for code in codes:
            resolve_language(code)  # raises ValueError on unknown codes
        return self


# --------------------------------------------------------------------------- stimuli
ItemType = Literal["forced_choice", "compliance"]


class Variant(BaseModel):
    id: str
    ref_lang: str
    ref_text: str


class Item(BaseModel):
    id: str
    type: ItemType
    options: list[str]
    target: str | None = None
    notes: str | None = None
    variants: list[Variant]

    @model_validator(mode="after")
    def _check(self) -> "Item":
        if self.type == "forced_choice" and len(self.options) != 2:
            raise ValueError(f"{self.id}: forced_choice needs exactly 2 options")
        if self.type == "compliance" and self.options != ["complied", "refused"]:
            raise ValueError(f"{self.id}: compliance options must be [complied, refused]")
        if not self.variants:
            raise ValueError(f"{self.id}: needs at least one variant")
        return self


class ItemSet(BaseModel):
    items: list[Item]

    def by_id(self, item_id: str) -> Item:
        for it in self.items:
            if it.id == item_id:
                return it
        raise KeyError(item_id)


class Translations(BaseModel):
    """item_id -> variant_id -> language_code -> text (or TODO_TRANSLATE)."""

    table: dict[str, dict[str, dict[str, str]]] = Field(default_factory=dict)

    def lookup(self, item_id: str, variant_id: str, language: str) -> str | None:
        text = self.table.get(item_id, {}).get(variant_id, {}).get(language)
        if text is None or text == TODO_TRANSLATE:
            return None
        return text


# --------------------------------------------------------------------------- loaders
def _read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_config(config_path: str | Path) -> Config:
    path = Path(config_path)
    raw_bytes = path.read_bytes()
    data = yaml.safe_load(raw_bytes)
    cfg = Config.model_validate(data)
    cfg.config_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
    return cfg


def load_items(path: str | Path) -> ItemSet:
    return ItemSet.model_validate(_read_yaml(Path(path)))


def load_translations(path: str | Path) -> Translations:
    raw = _read_yaml(Path(path)) or {}
    return Translations(table=raw.get("translations", {}))
