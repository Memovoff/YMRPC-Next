"""Ynison: redirect-хост должен принадлежать Яндекс Музыке."""

from __future__ import annotations

import pytest

from ymrpc.sources.ynison import _validated_host


@pytest.mark.parametrize(
    "value",
    [
        "music.yandex.ru",
        "music.yandex.ru.",
        "ynison.music.yandex.ru",
        "redirector.music.yandex.ru",
        "MUSIC.YANDEX.RU",
    ],
)
def test_trusted_ynison_hosts(value: str) -> None:
    assert _validated_host(value) is not None


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "yandex.ru",
        "music.yandex.ru.evil.example",
        "evil-music.yandex.ru.example",
        "music.yandex.ru:443",
        "music.yandex.ru/path",
        "music.yandex.ru\n.evil.example",
        "music.yandex.ru\x00.evil.example",
        " " + "a" * 300 + ".music.yandex.ru",
    ],
)
def test_untrusted_ynison_hosts(value) -> None:
    assert _validated_host(value) is None
