from __future__ import annotations

import json
from importlib.resources import files


_CURRENT_LANG = "en"
_STRINGS: dict[str, str] = {}


def _load_locale(lang: str) -> dict[str, str]:
    lang_lower = lang.lower() if lang else "en"
    if lang_lower not in ("en", "ru"):
        lang_lower = "en"
    try:
        path = files("terminal_lyrics.i18n") / f"{lang_lower}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return dict(data)
    except Exception:
        return {}


def set_lang(lang: str) -> None:
    global _CURRENT_LANG, _STRINGS
    _CURRENT_LANG = (lang or "en").lower()
    if _CURRENT_LANG not in ("en", "ru"):
        _CURRENT_LANG = "en"
    _STRINGS = _load_locale(_CURRENT_LANG)


def t(key: str, **kwargs: str | int) -> str:
    if not _STRINGS:
        set_lang(_CURRENT_LANG)
    s = _STRINGS.get(key, key)
    if kwargs:
        try:
            return s.format(**kwargs)
        except KeyError:
            return s
    return s


# Load default on import
set_lang("en")
