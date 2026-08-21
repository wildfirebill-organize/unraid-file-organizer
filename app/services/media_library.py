"""Media library mode — routes TV episodes and movies into Plex/Jellyfin-style paths.

    Show Name S01E02.mkv                    → <root>/TV Shows/Show Name/Season 01/
    Show Name S01E02-E03.mkv                → same (multi-episode, routed by first ep)
    [Group] Cowboy Bebop - 05 [1080p].mkv   → <root>/TV Shows/Cowboy Bebop/Season 01/
    Naruto Shippuden Episode 220.mp4        → <root>/TV Shows/Naruto Shippuden/Season 01/
    Movie Name (2010).mp4                   → <root>/Movies/Movie Name (2010)/
    Movie.Name.2010.1080p.x264.mkv          → <root>/Movies/Movie Name (2010)/

Pure parsing helpers; the scanner applies results only when the mode is enabled
and no custom rule already claimed the file.
"""

import os
import re
from typing import Any, Dict, Optional

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts"}

BRACKET_PREFIX = re.compile(r"^(?:\[[^\]]*\]|\([^)]*\))[\._ ]*-?[\._ ]*")

EPISODE_SXXEXX = re.compile(
    r"^(?P<title>.+?)[\._ ]+[sS](?P<season>\d{1,2})[eE](?P<episode>\d{1,3})(?!\d)"
    r"(?:[\._-]*[eE](?P<end>\d{1,3})(?!\d))?(?P<rest>.*)$"
)
EPISODE_NXNN = re.compile(
    r"^(?P<title>.+?)[\._ ]+(?P<season>\d{1,2})x(?P<episode>\d{1,3})(?!\d)"
    r"(?:[\._-]*x?(?P<end>\d{1,3})(?!\d))?(?P<rest>.*)$"
)
ANIME_DASH = re.compile(r"^(?P<title>.+?)[\._ ]+-[\._ ]+(?P<episode>\d{1,3})(?!\d)(?P<rest>.*)$")
EPISODE_KW = re.compile(
    r"^(?P<title>.+?)[\._ ]+(?:ep|episode)[\._ ]*(?P<episode>\d{1,4})(?!\d)(?P<rest>.*)$",
    re.IGNORECASE,
)
MOVIE_PAREN = re.compile(r"^(?P<title>.+?)[\._ ]+\((?P<year>(?:19|20)\d{2})\)")

QUALITY_TOKEN_RE = re.compile(
    r"^(?:1080p|720p|2160p|480p|4k|x264|x265|h\.?264|h\.?265|hevc|avc|bluray|blu-ray|"
    r"bdrip|brrip|dvdrip|hdrip|web[\._]?dl|webrip|web|hdtv|remux|aac|ac3|dts|ddp(?:\d)?|"
    r"dd\+|[57]\.1|dualaudio|subbed|dubbed|extended|remastered|proper|repack|proof)$",
    re.IGNORECASE,
)
MOVIE_LOOSE = re.compile(
    r"^(?P<title>.+)[\._ ]+(?P<year>(?:19|20)\d{2})(?P<rest>[\._ ].*)?$"
)


def _clean_title(raw: str) -> str:
    cleaned = re.sub(r"[\._]+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_")
    return cleaned.title()


def _strip_bracket_prefixes(name: str) -> str:
    prev = None
    while prev != name:
        prev = name
        name = BRACKET_PREFIX.sub("", name)
    return name


def _extract_ep_title(rest: str) -> Optional[str]:
    """Pull a human episode title out of the post-pattern remainder."""
    if not rest:
        return None
    s = rest.strip(" ._-\t")
    if not s:
        return None
    words = []
    for tok in re.split(r"[\._ ]+", s):
        if not tok:
            continue
        if QUALITY_TOKEN_RE.match(tok):
            break
        if re.match(r"^[a-f0-9]{8}$", tok, re.IGNORECASE):
            break  # release hash
        words.append(tok)
    title = " ".join(words).strip()
    return title or None


def _loose_year_rest_ok(rest: Optional[str]) -> bool:
    """After a bare year, only quality/release tags may follow (or nothing)."""
    if not rest:
        return True
    tokens = [t for t in re.split(r"[\._ ]+", rest.strip(" ._")) if t]
    return all(QUALITY_TOKEN_RE.match(t) for t in tokens)


def parse_media(filename: str) -> Optional[Dict[str, Any]]:
    """Parse a video filename into an episode/movie descriptor, or None."""
    name, ext = os.path.splitext(filename)
    if ext.lower() not in VIDEO_EXTENSIONS:
        return None

    name = _strip_bracket_prefixes(name)

    # SxxExx (with optional multi-episode range and episode title)
    m = EPISODE_SXXEXX.match(name)
    if m:
        season, ep, end = int(m.group("season")), int(m.group("episode")), m.group("end")
        parsed = {
            "type": "episode",
            "title": _clean_title(m.group("title")),
            "season": season,
            "episode": ep,
            "ep_title": _extract_ep_title(m.group("rest")),
        }
        if end and int(end) > ep:
            parsed["episode_end"] = int(end)
        return parsed

    # 1x02 style
    m = EPISODE_NXNN.match(name)
    if m:
        season, ep, end = int(m.group("season")), int(m.group("episode")), m.group("end")
        parsed = {
            "type": "episode",
            "title": _clean_title(m.group("title")),
            "season": season,
            "episode": ep,
            "ep_title": _extract_ep_title(m.group("rest")),
        }
        if end and int(end) > ep:
            parsed["episode_end"] = int(end)
        return parsed

    # Anime absolute numbering: "Title - 05"
    m = ANIME_DASH.match(name)
    if m:
        return {
            "type": "episode",
            "title": _clean_title(m.group("title")),
            "season": 1,
            "episode": int(m.group("episode")),
            "ep_title": _extract_ep_title(m.group("rest")),
        }

    # "Title Episode 220" / "Title EP 12"
    m = EPISODE_KW.match(name)
    if m:
        return {
            "type": "episode",
            "title": _clean_title(m.group("title")),
            "season": 1,
            "episode": int(m.group("episode")),
            "ep_title": _extract_ep_title(m.group("rest")),
        }

    # Movie with parenthesised year
    m = MOVIE_PAREN.match(name)
    if m:
        return {
            "type": "movie",
            "title": _clean_title(m.group("title")),
            "year": int(m.group("year")),
        }

    # Release-scene movie: dotted/underscored name ending in a bare year + tags
    m = MOVIE_LOOSE.match(name)
    if m and _loose_year_rest_ok(m.group("rest")):
        return {
            "type": "movie",
            "title": _clean_title(m.group("title")),
            "year": int(m.group("year")),
        }

    return None


def destination_for(parsed: Dict[str, Any], cfg) -> str:
    root = cfg.media_library_root.rstrip("/\\")
    if parsed["type"] == "episode":
        return f"{root}/TV Shows/{parsed['title']}/Season {parsed['season']:02d}/"
    year = f" ({parsed['year']})" if parsed.get("year") else ""
    return f"{root}/Movies/{parsed['title']}{year}/"
