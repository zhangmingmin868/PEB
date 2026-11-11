"""Interface languages: English, 简体中文, Español, Français.

All visible texts are written in English in the source code and passed through
``tr()``; translations live in ``translations.py`` keyed by the English text.
"""
from __future__ import annotations

from .translations import TRANSLATIONS

LANGUAGES = {"en": "English", "zh": "简体中文", "es": "Español", "fr": "Français"}
_lang = "en"


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in LANGUAGES else "en"


def language() -> str:
    return _lang


def tr(text: str) -> str:
    t = TRANSLATIONS.get(_lang, {}).get(text)
    if t is None and _lang != "en":
        t = TRANSLATIONS.get("en", {}).get(text)
    return text if t is None else t


def trf(text: str, **kw) -> str:
    """Translate then format: trf("Run {n}", n=3)."""
    return tr(text).format(**kw)
