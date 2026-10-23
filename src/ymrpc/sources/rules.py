"""Выбор активного источника по правилам приложений."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import AppRule, MediaSnapshot, PlaybackStatus, RuleAction, SessionInfo


@dataclass(frozen=True, slots=True)
class Candidate:
    session: SessionInfo
    priority: int = 0


def app_ignored(source_id: str, source_name: str, rules: tuple[AppRule, ...]) -> bool:
    return any(
        rule.action == RuleAction.IGNORE and rule.matches(source_id, source_name) for rule in rules
    )


def app_priority(source_id: str, source_name: str, rules: tuple[AppRule, ...]) -> int:
    values = [
        rule.priority
        for rule in rules
        if rule.action == RuleAction.PREFER and rule.matches(source_id, source_name)
    ]
    return max(values, default=0)


def choose(
    sessions: list[SessionInfo],
    rules: tuple[AppRule, ...],
    selected: str = "",
) -> SessionInfo | None:
    active = [
        session
        for session in sessions
        if session.status in (PlaybackStatus.PLAYING, PlaybackStatus.PAUSED)
    ]
    if not active:
        return None

    if selected:
        for session in active:
            if session.source_id == selected:
                return session

    ranked: list[tuple[int, int, int, SessionInfo]] = []
    for index, session in enumerate(active):
        if app_ignored(session.source_id, session.source_name, rules):
            continue
        ranked.append(
            (
                1 if session.status == PlaybackStatus.PLAYING else 0,
                app_priority(session.source_id, session.source_name, rules),
                -index,
                session,
            )
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return ranked[0][3]


def choose_auto(
    windows: MediaSnapshot | None,
    ynison: MediaSnapshot | None,
) -> MediaSnapshot | None:
    """Авторежим: локальное воспроизведение важнее удалённого.

    Если в Windows что-то играет, показываем его. Иначе берём играющий
    Ynison (телефон/веб). Если играет только Ynison — он и выигрывает.
    Пауза Windows считается лучше, чем отсутствие трека.
    """
    if windows is not None and windows.status == PlaybackStatus.PLAYING:
        return windows
    if ynison is not None and ynison.status == PlaybackStatus.PLAYING:
        return ynison
    return windows if windows is not None else ynison
