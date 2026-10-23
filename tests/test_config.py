"""Настройки: чтение, запись, санитизация и повреждённый JSON."""

from __future__ import annotations

import json
from dataclasses import replace

from ymrpc import config
from ymrpc.config import ConfigStore
from ymrpc.models import AppRule, CaptureMode, RuleAction, Settings


def test_roundtrip(tmp_path) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    settings = replace(
        Settings(),
        capture_mode=CaptureMode.YNISON,
        ui_language="en",
        rpc_language="en",
        mini_player_pos=(120, 240),
        rules=(AppRule("chrome", RuleAction.IGNORE), AppRule("spotify", RuleAction.PREFER, 50)),
    )
    store.save(settings)
    loaded = ConfigStore(path).settings
    assert loaded.capture_mode == CaptureMode.YNISON
    assert loaded.ui_language == "en"
    assert loaded.rpc_language == "en"
    assert loaded.mini_player_pos == (120, 240)
    assert loaded.rules == settings.rules


def test_sanitizes_invalid_values(tmp_path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    saved = store.save(
        replace(
            Settings(),
            details_template="   ",
            overlay_port=80,
            overlay_accent="red",
            update_repo="not a repo",
            pause_timeout=-999,
            lyrics_offset=100,
            rules=(AppRule("  chrome  "), AppRule("")),
        )
    )
    assert saved.details_template == Settings().details_template
    assert saved.overlay_port == 1024
    assert saved.overlay_accent == "#ffcc00"
    assert saved.update_repo == Settings().update_repo
    assert saved.pause_timeout == -1
    assert saved.lyrics_offset == 30.0
    assert [rule.pattern for rule in saved.rules] == ["chrome"]


def test_corrupt_file_falls_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert ConfigStore(path).settings == Settings()


def test_unknown_fields_are_ignored(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"settings": {"ui_language": "de", "overlay_theme": "blue", "unknown": 1}}),
        encoding="utf-8",
    )
    settings = ConfigStore(path).settings
    assert settings.ui_language == "ru"
    assert settings.overlay_theme == "dark"


def test_partial_config_uses_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"settings": {"presence_enabled": False}}), encoding="utf-8")
    settings = ConfigStore(path).settings
    assert settings.presence_enabled is False
    assert settings.overlay_port == Settings().overlay_port
    assert settings.details_template == Settings().details_template


def test_old_ynison_mode_migrates_to_auto(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"schema": 1, "settings": {"capture_mode": "ynison"}}),
        encoding="utf-8",
    )
    assert ConfigStore(path).settings.capture_mode == CaptureMode.AUTO
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["schema"] == 2
    assert migrated["settings"]["capture_mode"] == "auto"


def test_explicit_ynison_mode_is_kept_after_save(tmp_path) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.save(replace(Settings(), capture_mode=CaptureMode.YNISON))
    assert ConfigStore(path).settings.capture_mode == CaptureMode.YNISON


def test_legacy_update_repo_migrates_to_new_default(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "schema": 2,
                "settings": {"update_repo": "FozerG/YMRPC-Next"},
            }
        ),
        encoding="utf-8",
    )
    assert ConfigStore(path).settings.update_repo == Settings().update_repo
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["settings"]["update_repo"] == Settings().update_repo


def test_custom_update_repo_is_kept(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"schema": 2, "settings": {"update_repo": "owner/custom-repo"}}),
        encoding="utf-8",
    )
    assert ConfigStore(path).settings.update_repo == "owner/custom-repo"


def test_identical_settings_do_not_rewrite_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.save(Settings())
    before = path.stat().st_mtime_ns

    def forbidden(*_args, **_kwargs):
        raise AssertionError("идентичные настройки не должны перезаписывать файл")

    monkeypatch.setattr(config.os, "fsync", forbidden)
    store.save(store.settings)
    monkeypatch.undo()
    assert path.stat().st_mtime_ns == before
