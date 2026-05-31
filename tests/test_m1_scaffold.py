"""M1 smoke tests: config + stimuli load, grid expands, dry-run is pure."""

from __future__ import annotations

import pytest

from eval.config import load_config, load_items, load_translations
from eval.languages import resolve
from eval.runner import build_grid, estimate_cost

CONFIG = "configs/main.yaml"


@pytest.fixture(scope="module")
def loaded():
    cfg = load_config(CONFIG)
    items = load_items(cfg.paths.items)
    translations = load_translations(cfg.paths.translations)
    return cfg, items, translations


def test_config_hash_is_stable_and_short(loaded):
    cfg, _, _ = loaded
    assert len(cfg.config_hash) == 16
    assert load_config(CONFIG).config_hash == cfg.config_hash


def test_language_resolution_and_script_control():
    fr = resolve("fr")
    assert (fr.name, fr.script, fr.is_control) == ("French", "Latin", False)
    fr_hani = resolve("fr_hani")
    assert (fr_hani.base, fr_hani.script, fr_hani.is_control) == ("fr", "Han", True)
    with pytest.raises(ValueError):
        resolve("xx")


def test_grid_size_matches_models_items_langs(loaded):
    cfg, items, translations = loaded
    grid = build_grid(cfg, items, translations)
    expected = 0
    for model in cfg.models:
        n = model.n_samples or cfg.run.n_samples
        for item in items.items:
            n_langs = len(cfg.languages.for_item(item.id))
            expected += n * len(item.variants) * n_langs
    assert len(grid) == expected
    assert len(grid) > 0


def test_untranslated_cells_are_mock_with_empty_prompt(loaded):
    cfg, items, translations = loaded
    grid = build_grid(cfg, items, translations)
    # The v1_humor variant's source is English -> en cells carry real text;
    # its Russian cells are untranslated -> mock with empty prompt.
    en = [s for s in grid if s.item_id == "stalin_mao"
          and s.variant_id == "v1_humor" and s.language == "en"]
    ru = [s for s in grid if s.item_id == "stalin_mao"
          and s.variant_id == "v1_humor" and s.language == "ru"]
    assert en and all(not s.is_mock and s.prompt for s in en)
    assert ru and all(s.is_mock and s.prompt == "" for s in ru)
    # The native-French variant carries real text on its fr cell instead.
    fr_native = [s for s in grid if s.item_id == "stalin_mao"
                 and s.variant_id == "v4_native_fr" and s.language == "fr"]
    assert fr_native and all(not s.is_mock and s.prompt for s in fr_native)


def test_limit_caps_grid(loaded):
    cfg, items, translations = loaded
    assert len(build_grid(cfg, items, translations, limit=5)) == 5


def test_cost_counts_only_live_calls(loaded):
    cfg, items, translations = loaded
    grid = build_grid(cfg, items, translations)
    cost = estimate_cost(cfg, grid)
    assert cost["live_calls"] + cost["mock_calls"] == len(grid)
    assert cost["total_usd"] >= 0.0
