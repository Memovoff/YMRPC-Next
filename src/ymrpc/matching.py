"""Сопоставление трека из плеера с результатами каталогов."""

from __future__ import annotations

import re
import unicodedata

from .models import MediaSnapshot, Track

_NOISE = re.compile(
    r"\b(remaster(ed)?|remastered\s+\d{4}|deluxe|explicit|clean|radio\s+edit|"
    r"album\s+version|single\s+version|mono|stereo|feat\.?|ft\.?|prod\.?)\b",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_FEAT = re.compile(r"\s+(feat\.?|ft\.?|при\s+участии)\s+.*$", re.IGNORECASE)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold().replace("ё", "е")
    value = _BRACKETS.sub(" ", value)
    value = _FEAT.sub("", value)
    value = _NOISE.sub(" ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def artist_tokens(value: str) -> set[str]:
    parts = re.split(r"[,&;/]|\bfeat\.?\b|\bft\.?\b", value or "", flags=re.IGNORECASE)
    return {normalize(part) for part in parts if normalize(part)}


def score(media: MediaSnapshot, track: Track) -> float:
    """0..1 — насколько результат похож на исходный трек."""
    source_title = normalize(media.title)
    if not source_title:
        return 0.0

    track_title = normalize(track.title)
    result = 0.0
    if source_title == track_title:
        result += 0.55
    elif source_title in track_title or track_title in source_title:
        result += 0.38
    else:
        title_words = set(source_title.split())
        other_words = set(track_title.split())
        overlap = len(title_words & other_words) / max(1, len(title_words))
        if overlap >= 0.6:
            result += 0.28 * overlap
        else:
            return 0.0

    source_artists = artist_tokens(media.artist)
    track_artists = artist_tokens(track.artist)
    if source_artists and track_artists:
        if source_artists & track_artists:
            result += 0.3
        elif any(a in b or b in a for a in source_artists for b in track_artists):
            result += 0.2
        else:
            result += 0.02
    else:
        result += 0.12

    if media.album and track.album and normalize(media.album) == normalize(track.album):
        result += 0.08

    media_duration = media.duration
    if media_duration and track.duration:
        delta = abs(media_duration - track.duration)
        if delta <= 2:
            result += 0.07
        elif delta <= 8:
            result += 0.04
        elif delta >= 40:
            result -= 0.12

    return max(0.0, min(1.0, result))


def choose(media: MediaSnapshot, tracks: list[Track], minimum: float = 0.55) -> Track | None:
    if not tracks:
        return None
    ranked = sorted(
        ((score(media, track), index, track) for index, track in enumerate(tracks)),
        key=lambda item: (item[0], -item[1]),
        reverse=True,
    )
    best_score, _index, best = ranked[0]
    return best if best_score >= minimum else None
