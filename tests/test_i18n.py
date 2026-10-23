"""Проверка того, что все ключи интерфейса переведены."""

from __future__ import annotations

import re
from pathlib import Path

from ymrpc import i18n

ROOT = Path(__file__).resolve().parents[1]
CALL = re.compile(r"""\bt\(\s*["']([^"']+)["']""")


def _used_keys() -> set[str]:
    keys: set[str] = set()
    for path in (ROOT / "src" / "ymrpc").rglob("*.py"):
        keys.update(CALL.findall(path.read_text(encoding="utf-8")))
    return keys


def test_all_used_keys_exist_in_both_languages() -> None:
    missing_ru = sorted(key for key in _used_keys() if key not in i18n._RU)
    missing_en = sorted(key for key in _used_keys() if key not in i18n._EN)
    assert not missing_ru, f"нет русских переводов: {missing_ru}"
    assert not missing_en, f"нет английских переводов: {missing_en}"


def test_language_switch_and_fallback() -> None:
    i18n.set_language("en")
    assert i18n.t("app.save") == "Save"
    i18n.set_language("ru")
    assert i18n.t("app.save") == "Сохранить"
    i18n.set_language("xx")
    assert i18n.current_language() == "ru"
    assert i18n.t("missing.key") == "missing.key"


def test_source_labels() -> None:
    assert i18n.source_label("Yandex.Music") == "Яндекс Музыка"
    assert i18n.source_label("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify") == "Spotify"
    assert i18n.source_label("SomePlayer.exe", "Some Player") == "Some Player"
