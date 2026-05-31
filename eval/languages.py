"""Canonical language registry + script-control resolution.

A language code is either a base language (e.g. ``fr``) or a script-control
pseudo-language ``<base>_<script>`` (e.g. ``fr_hani`` = French rendered in Han
characters). The base carries the *meaning*; the script tag overrides the
*orthography*, letting us separate language effects from writing-system effects.
"""

from __future__ import annotations

from dataclasses import dataclass

# ISO 15924-ish script tags used by the pseudo-language suffixes.
_SCRIPT_NAMES: dict[str, str] = {
    "latn": "Latin",
    "hani": "Han",
    "cyrl": "Cyrillic",
    "arab": "Arabic",
    "jpan": "Japanese",
}

# Base languages: code -> (human name, default script tag).
_BASE_LANGUAGES: dict[str, tuple[str, str]] = {
    "en":  ("English", "latn"),
    "fr":  ("French", "latn"),
    "de":  ("German", "latn"),
    "ru":  ("Russian", "cyrl"),
    "uk":  ("Ukrainian", "cyrl"),
    "ar":  ("Arabic", "arab"),
    "ja":  ("Japanese", "jpan"),
    "cmn": ("Mandarin", "hani"),
    "yue": ("Cantonese", "hani"),
    "zh":  ("Chinese", "hani"),
}


@dataclass(frozen=True)
class Language:
    """A resolved language cell in the grid."""

    code: str          # as written in config, e.g. "fr" or "fr_hani"
    base: str          # base language code, e.g. "fr"
    name: str          # human-readable language name, e.g. "French"
    script: str        # human-readable script name, e.g. "Han"
    is_control: bool    # True for script-control pseudo-languages


def resolve(code: str) -> Language:
    """Resolve a config language code into a :class:`Language`.

    Raises ``ValueError`` for unknown base languages or script tags so config
    validation fails loudly before any API call.
    """
    base, _, script_tag = code.partition("_")
    if base not in _BASE_LANGUAGES:
        raise ValueError(f"Unknown base language {base!r} in code {code!r}")
    name, default_script = _BASE_LANGUAGES[base]
    if script_tag:
        if script_tag not in _SCRIPT_NAMES:
            raise ValueError(f"Unknown script tag {script_tag!r} in code {code!r}")
        return Language(
            code=code, base=base, name=name,
            script=_SCRIPT_NAMES[script_tag], is_control=True,
        )
    return Language(
        code=code, base=base, name=name,
        script=_SCRIPT_NAMES[default_script], is_control=False,
    )
