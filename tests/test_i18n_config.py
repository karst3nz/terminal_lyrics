from __future__ import annotations

import os
from pathlib import Path

import pytest

from terminal_lyrics.config import load_config, save_config_lang
from terminal_lyrics.i18n import set_lang, t


class TestI18n:
    """Test i18n t() and set_lang."""

    def test_t_en(self):
        set_lang("EN")
        assert t("no_mpris_players") == "No active MPRIS players"
        assert t("lyrics_not_found") == "No lyrics found for current track"
        assert t("cache_cleared", path="/tmp/cache") == "Cache cleared: /tmp/cache"

    def test_t_ru(self):
        set_lang("RU")
        assert t("no_mpris_players") == "Нет активных MPRIS-плееров"
        assert t("lyrics_not_found") == "Слова не найдены для текущего трека"
        assert t("cache_cleared", path="/tmp/cache") == "Кэш очищен: /tmp/cache"

    def test_t_fallback_to_key(self):
        set_lang("EN")
        assert t("nonexistent_key") == "nonexistent_key"


class TestConfigLang:
    """Test config --lang and load_config lang priority."""

    def test_save_config_lang_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("TERMINAL_LYRICS_LANG", raising=False)

        save_config_lang("RU")
        cfg = load_config()
        assert cfg.lang == "RU"

        save_config_lang("EN")
        cfg = load_config()
        assert cfg.lang == "EN"

    def test_load_lang_priority_config_over_env(self, tmp_path, monkeypatch):
        (tmp_path / "terminal-lyrics").mkdir(parents=True, exist_ok=True)
        (tmp_path / "terminal-lyrics" / "config.json").write_text(
            '{"lang": "RU"}', encoding="utf-8"
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("TERMINAL_LYRICS_LANG", "EN")

        cfg = load_config()
        assert cfg.lang == "RU"

    def test_load_lang_env_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("TERMINAL_LYRICS_LANG", "RU")

        cfg = load_config()
        assert cfg.lang == "RU"
