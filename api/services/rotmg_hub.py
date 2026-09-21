"""Official RotMG Hub patch notes (hub.realmofthemadgod.com).

Fourth knowledge pillar beside RealmEye, UmiEnjoyers, and RealmShark.
Patch truth for events, rotations, and new item names before the wiki
catches up. Does not replace Shark/Umi/wiki for BIS ranking.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Any, Optional

import redis.asyncio as aioredis
from loguru import logger

from .chunks import wrap_slot_chunk

HUB_BASE = "https://hub.realmofthemadgod.com"
HUB_UPDATES_URL = f"{HUB_BASE}/news0/updates0"
INDEX_KEY = "rotmg-hub:index:v1"
POST_PREFIX = "rotmg-hub:post:v1:"
SPRITES_KEY = "rotmg-hub:sprites:v1"
NAMES_KEY = "rotmg-hub:names:v1"
HUB_TTL_SECONDS = 86400  # 24h; MOTMG posts change weekly
MAX_BODY_CHARS = 24_000
MAX_POSTS_BOOT = 24
MAX_POSTS_FORCE = 48
LATEST_SCAN = 5
_SCORE_STOP = frozenset(
    {
        "where",
        "does",
        "drop",
        "drops",
        "from",
        "this",
        "that",
        "have",
        "what",
        "with",
        "they",
        "them",
        "then",
        "when",
        "your",
        "about",
        "item",
        "items",
        "only",
        "just",
        "into",
        "which",
    }
)

_AGHANIM_NEWS = re.compile(r"static-platform\.aghanim\.com/news/", re.I)
_SKIP_IMG = re.compile(r"/hub/|peg|steam|social|logo|icon", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n{3,}")
_BOLD = re.compile(r"\*{2,}")
_TABLE_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_TABLE_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
_IMG = re.compile(
    r'<img[^>]+src=["\']([^"\']+)["\'][^>]*(?:alt=["\']([^"\']*)["\'])?',
    re.I,
)
_CARD_LINK = re.compile(
    r'<a[^>]+href=["\'](/news0/updates0/([^"\']+))["\'][^>]*class="[^"]*'
    r"border-sem-component-br-component-card",
    re.I,
)
_CARD_DATE = re.compile(
    r"text-sem-component-tx-component-news-date[^>]*>\s*<p[^>]*>([^<]+)</p>",
    re.I,
)
_CARD_TITLE = re.compile(
    r"text-sem-component-tx-component-news-title[^>]*>([^<]+)<",
    re.I,
)
_CARD_IMG = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
_PROSE = re.compile(
    r'<div class="prose[^"]*prose-hub[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
    re.I | re.S,
)
_H1 = re.compile(r'<h1[^>]*class="[^"]*text-heading-h1[^"]*"[^>]*>([^<]+)</h1>', re.I)

_HUB_URL = re.compile(r"hub\.realmofthemadgod\.com/news0/updates0", re.I)
_MOTMG = re.compile(
    r"\b(?:motmg|month of the mad god|mad god mayhem)\b",
    re.I,
)
_PATCH = re.compile(
    r"\b(?:patch notes?|update notes?|what(?:'s| is) new|what shipped|"
    r"season \d+|retrowinds?|time chamber|weekly rotation|"
    r"legacy portals?|venerable equipment|new shinies?)\b",
    re.I,
)
_TIME_CHAMBER = re.compile(r"\btime chamber\b|\blegacy portals?\b", re.I)
_ROTATION = re.compile(r"\bweek(?:ly)?\s*(?:\d|one|two|three|four|five)\b", re.I)
_SHINIES = re.compile(r"\bnew shinies?\b", re.I)
_EVENT_WHITE = re.compile(r"\bevent whites?\b|\bnew encounters?\b", re.I)
_NEW_PLAYER = re.compile(r"\bnew\s+(?:player|to\b|here)\b|\bbeginner\b", re.I)
_NEW_ITEM_ASK = re.compile(
    r"\b(?:the\s+)?new\s+"
    r"(?:ut|st|item|white|shiny|encounter|prism|staff|bow|sword|ring|robe|"
    r"armor|set|[a-z][\w'’-]{2,})\b"
    r"|\bwhere\s+(?:does|do)\s+(?:the\s+)?new\b"
    r"|\bwhat(?:'s| is)\s+(?:the\s+)?new\b",
    re.I,
)
_DROP_ASK = re.compile(r"\b(?:where\s+(?:does|do).+\bdrop|drop\s+locations?)\b", re.I)


@dataclass(frozen=True)
class HubQuery:
    """A message that should read official Hub patch notes."""

    survey: bool = False
    slug_hint: Optional[str] = None
    topic: str = ""


def post_url(slug: str) -> str:
    return f"{HUB_UPDATES_URL}/{slug.strip('/')}"


def normalize_hub_name(name: str) -> str:
    text = unescape((name or "").strip())
    text = _BOLD.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()


def _strip_html(fragment: str) -> str:
    text = unescape(_TAG.sub(" ", fragment or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_index_cards(html: str) -> list[dict[str, str]]:
    """Parse hydrated index HTML into card rows."""
    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _CARD_LINK.finditer(html or ""):
        href = match.group(1)
        slug = match.group(2).strip("/")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        tail = html[match.end() : match.end() + 2500]
        date_m = _CARD_DATE.search(tail)
        title_m = _CARD_TITLE.search(tail)
        img_m = _CARD_IMG.search(tail)
        cards.append(
            {
                "slug": slug,
                "title": _strip_html(title_m.group(1)) if title_m else slug,
                "date": _strip_html(date_m.group(1)) if date_m else "",
                "url": f"{HUB_BASE}{href}",
                "thumbnail_url": img_m.group(1) if img_m else "",
            }
        )
    return cards


_H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)
_H3 = re.compile(r"<h3[^>]*>(.*?)</h3>", re.I | re.S)


def _section_blocks_from_html(prose_html: str) -> list[dict[str, str]]:
    """Split prose HTML on h2/h3 headings."""
    sections: list[dict[str, str]] = []
    parts = re.split(r"(<h[23][^>]*>.*?</h[23]>)", prose_html or "", flags=re.I | re.S)
    current_title = ""
    current = ""
    for part in parts:
        if not part.strip():
            continue
        h2 = _H2.fullmatch(part.strip())
        h3 = None if h2 else _H3.fullmatch(part.strip())
        if h2 or h3:
            if current_title or current:
                sections.append({"title": current_title, "body": _strip_html(current)})
            current_title = _strip_html((h2 or h3).group(1))
            current = ""
        else:
            current += part
    if current_title or current:
        sections.append({"title": current_title, "body": _strip_html(current)})
    return sections


def _parse_table_pairs(html: str) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for row in _TABLE_ROW.findall(html or ""):
        cells = [_strip_html(c) for c in _TABLE_CELL.findall(row)]
        cells = [c for c in cells if c]
        if len(cells) >= 2 and "base item" not in cells[0].lower():
            pairs.append({"base": cells[0], "new": cells[1]})
    return pairs


def _parse_list_items(section_body: str) -> list[str]:
    items: list[str] = []
    for line in (section_body or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("* ") or stripped.startswith("- "):
            name = stripped[2:].strip()
            name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
            if name and len(name) > 2:
                items.append(name)
    return items


def _parse_list_items_from_html(prose_html: str, section_title: str) -> list[str]:
    """Pull <li> names from the HTML block under a matching h2 title."""
    items: list[str] = []
    title_pat = re.escape(section_title)
    block = re.search(
        rf"<h2[^>]*>\s*{title_pat}\s*</h2>(.*?)(?=<h2|$)",
        prose_html or "",
        re.I | re.S,
    )
    if not block:
        return items
    for li in re.findall(r"<li[^>]*>(.*?)</li>", block.group(1), re.I | re.S):
        name = _strip_html(li)
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        if name and len(name) > 2:
            items.append(name)
    return items


def _parse_event_whites(section_body: str) -> list[str]:
    return [row["name"] for row in _parse_event_white_rows(section_body)]


def _parse_event_white_rows(section_body: str) -> list[dict[str, str]]:
    """'Rectangular Prism (Prism) from the Cube Deity' lines."""
    rows: list[dict[str, str]] = []
    blob = section_body or ""
    for line in blob.splitlines():
        stripped = line.strip()
        if stripped.startswith("* ") or stripped.startswith("- "):
            stripped = stripped[2:].strip()
        m = re.match(
            r"^(.+?)\s*\(([^)]+)\)\s+from\s+(.+?)\.?$",
            stripped,
            re.I,
        )
        if m:
            rows.append(
                {
                    "name": m.group(1).strip(),
                    "slot": m.group(2).strip(),
                    "source": m.group(3).strip(" ."),
                }
            )
    if rows:
        return rows
    for m in re.finditer(
        r"([A-Z][A-Za-z0-9'’\- ]+?)\s*\(([^)]+)\)\s+from\s+([^.(]+)",
        blob,
    ):
        rows.append(
            {
                "name": m.group(1).strip(),
                "slot": m.group(2).strip(),
                "source": m.group(3).strip(" ."),
            }
        )
    return rows


def _caption_for_img(prose_html: str, match: re.Match[str]) -> str:
    alt = (match.group(2) or "").strip()
    if alt:
        return alt
    row = re.search(
        rf"<tr[^>]*>.*?{re.escape(match.group(0))}.*?</tr>",
        prose_html or "",
        re.I | re.S,
    )
    if row:
        cells = [_strip_html(c) for c in _TABLE_CELL.findall(row.group(0))]
        for cell in cells:
            if cell and "http" not in cell.lower() and len(cell) > 3:
                return cell
    tail = prose_html[match.end() : match.end() + 200]
    return _strip_html(tail.split("<", 1)[0])


def _parse_sprites(prose_html: str) -> list[dict[str, str]]:
    sprites: list[dict[str, str]] = []
    for match in _IMG.finditer(prose_html or ""):
        url = match.group(1)
        if not _AGHANIM_NEWS.search(url) or _SKIP_IMG.search(url):
            continue
        caption = _caption_for_img(prose_html, match)
        caption_key = normalize_hub_name(caption)
        if caption_key and len(caption_key) > 3:
            sprites.append({"url": url, "caption": caption.strip()})
    return sprites


def parse_article_html(
    html: str,
    slug: str,
    *,
    date: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Parse SSR article HTML into a stored post payload."""
    prose_match = _PROSE.search(html or "")
    prose_html = prose_match.group(1) if prose_match else ""
    if not title:
        h1 = _H1.search(html or "")
        title = _strip_html(h1.group(1)) if h1 else slug.replace("-", " ").title()
    body_text = _strip_html(prose_html)
    if len(body_text) > MAX_BODY_CHARS:
        body_text = body_text[: MAX_BODY_CHARS - 3] + "..."

    sections = _section_blocks_from_html(prose_html)
    table_pairs = _parse_table_pairs(prose_html)
    item_names: list[str] = []
    sprites = _parse_sprites(prose_html)

    for pair in table_pairs:
        item_names.append(pair["new"])

    for section in sections:
        title_lower = section["title"].lower()
        body = section["body"]
        if "new shinies" in title_lower:
            item_names.extend(_parse_list_items_from_html(prose_html, title_lower))
            item_names.extend(_parse_list_items(body))
        elif "new uts" in title_lower or "encounters" in title_lower:
            whites = _parse_event_white_rows(body)
            item_names.extend(row["name"] for row in whites)
        elif "twelve dungeons" in title_lower or "time chamber" in title_lower:
            item_names.extend(_parse_list_items_from_html(prose_html, title_lower))
            item_names.extend(_parse_list_items(body))

    item_names = list(dict.fromkeys(n for n in item_names if n))
    structured: dict[str, Any] = {"table_pairs": table_pairs}
    for section in sections:
        key = section["title"].lower()
        if "weekly dungeon rotation" in key:
            structured["weekly_rotation"] = section["body"]
        if "twelve dungeons" in key:
            structured["time_chamber_dungeons"] = _parse_list_items_from_html(
                prose_html, section["title"]
            ) or _parse_list_items(section["body"])
        if "new shinies" in key:
            structured["new_shinies"] = _parse_list_items_from_html(
                prose_html, section["title"]
            ) or _parse_list_items(section["body"])
        if "new uts" in key or "encounters" in key:
            structured["event_whites"] = _parse_event_white_rows(
                section["body"]
            ) or _parse_event_white_rows(
                "\n".join(
                    f"* {n}"
                    for n in _parse_list_items_from_html(prose_html, section["title"])
                )
            )
            if not structured["event_whites"]:
                structured["event_whites"] = _parse_event_white_rows(section["body"])
    if not structured.get("event_whites"):
        structured["event_whites"] = _parse_event_white_rows(body_text)

    return {
        "slug": slug,
        "title": title,
        "date": date,
        "url": post_url(slug),
        "text": body_text,
        "sections": sections,
        "items": item_names,
        "sprites": sprites,
        "structured": structured,
    }


def extract_hub_query(message: str, history: Optional[list[str]] = None) -> Optional[HubQuery]:
    """True when the user wants official patch / event notes."""
    text = (message or "").strip()
    if not text:
        return None
    if _HUB_URL.search(text):
        slug_m = re.search(r"/updates0/([a-z0-9-]+)", text, re.I)
        return HubQuery(slug_hint=slug_m.group(1) if slug_m else None, topic="hub_url")
    if _MOTMG.search(text):
        return HubQuery(topic="motmg", slug_hint="motmg")
    if _TIME_CHAMBER.search(text):
        return HubQuery(topic="time_chamber")
    if _ROTATION.search(text) and _PATCH.search(text):
        return HubQuery(topic="rotation")
    if _SHINIES.search(text):
        return HubQuery(topic="shinies")
    if _EVENT_WHITE.search(text):
        return HubQuery(topic="encounters")
    if _NEW_PLAYER.search(text):
        pass
    elif _NEW_ITEM_ASK.search(text) or (
        _DROP_ASK.search(text) and re.search(r"\bnew\b", text, re.I)
    ):
        return HubQuery(topic="new_item")
    if _PATCH.search(text):
        return HubQuery(survey=True, topic="patch")
    if history:
        for prev in reversed(history):
            if _PATCH.search(prev) or _MOTMG.search(prev):
                if _ROTATION.search(text) or _SHINIES.search(text):
                    return HubQuery(topic="follow_up")
                break
    return None


async def load_index(redis: aioredis.Redis) -> list[dict[str, str]]:
    raw = await redis.get(INDEX_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


async def load_post(redis: aioredis.Redis, slug: str) -> Optional[dict[str, Any]]:
    raw = await redis.get(f"{POST_PREFIX}{slug}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def load_sprite_map(redis: aioredis.Redis) -> dict[str, dict[str, str]]:
    raw = await redis.get(SPRITES_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def hub_item_names(redis: aioredis.Redis) -> list[str]:
    raw = await redis.get(NAMES_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


async def hub_sprite_url(redis: aioredis.Redis, name: str) -> Optional[str]:
    key = normalize_hub_name(name)
    if not key:
        return None
    sprites = await load_sprite_map(redis)
    row = sprites.get(key)
    return row.get("url") if row else None


def _score_post(post: dict[str, Any], query: HubQuery, message: str) -> int:
    if query.slug_hint and post.get("slug") == query.slug_hint:
        return 1000
    text = (message or "").lower()
    title = (post.get("title") or "").lower()
    body = (post.get("text") or "").lower()
    slug = (post.get("slug") or "").lower()
    score = 0
    if query.topic == "motmg" and "mad god" in title:
        score += 200
    if query.topic == "time_chamber" and "time chamber" in body:
        score += 150
    if query.topic == "rotation" and "weekly dungeon rotation" in body:
        score += 150
    if query.topic == "shinies" and "new shinies" in body:
        score += 120
    if query.topic == "encounters" and "new uts" in body:
        score += 120
    if slug == "motmg" or "mad god" in title:
        score += 50
    whites = (post.get("structured") or {}).get("event_whites") or []
    item_blob = " ".join(
        [normalize_hub_name(n) for n in (post.get("items") or [])]
        + [normalize_hub_name(row.get("name") or "") for row in whites]
    )
    if query.topic in {"new_drop", "new_item"}:
        for token in re.findall(r"[a-z0-9']{4,}", text):
            if token in _SCORE_STOP:
                continue
            if token in item_blob:
                score += 200
            elif token in title or token in body:
                score += 8
    else:
        for token in re.findall(r"[a-z0-9']{4,}", text):
            if token in _SCORE_STOP:
                continue
            if token in title or token in body:
                score += 5
    return score


def _format_post_brief(post: dict[str, Any], *, compact: bool = False) -> str:
    lines = [
        f"OFFICIAL PATCH NOTES: {post.get('title') or post.get('slug')}",
    ]
    if post.get("date"):
        lines.append(f"Published: {post['date']}")
    structured = post.get("structured") or {}
    if structured.get("new_shinies"):
        lines.append("New shinies: " + ", ".join(structured["new_shinies"][:20]))
    if structured.get("time_chamber_dungeons"):
        lines.append(
            "Time Chamber dungeons: "
            + ", ".join(structured["time_chamber_dungeons"])
        )
    if structured.get("event_whites"):
        whites = structured["event_whites"][:16]
        lines.append(
            "New event whites: "
            + "; ".join(
                f"{row['name']} ({row.get('slot') or '?'}) from {row.get('source') or '?'}"
                for row in whites
            )
        )
    if structured.get("table_pairs"):
        pairs = structured["table_pairs"][:12]
        pair_text = "; ".join(f"{p['base']} -> {p['new']}" for p in pairs)
        lines.append(f"Venerable / reskin tables: {pair_text}")
    if structured.get("weekly_rotation"):
        rot = structured["weekly_rotation"]
        if len(rot) > 1200:
            rot = rot[:1197] + "..."
        lines.append(f"Weekly rotation:\n{rot}")
    body = post.get("text") or ""
    limit = 900 if compact else 4000
    if len(body) > limit:
        body = body[: limit - 3] + "..."
    lines.append(body)
    lines.append(
        "Official Hub patch notes are source of truth for what shipped this "
        "season. They do not replace RealmShark/Umi/RealmEye for BIS picks. "
        "If a new item has no RealmEye page yet, name it from here and say "
        "the wiki store does not have stats yet."
    )
    return "\n\n".join(lines)


async def ensure_motmg_post(
    redis: aioredis.Redis, *, ttl_seconds: int = HUB_TTL_SECONDS
) -> Optional[dict[str, Any]]:
    """Keep the living MOTMG page in the store even when the index is older seasons."""
    post = await load_post(redis, "motmg")
    whites = ((post or {}).get("structured") or {}).get("event_whites") or []
    if post and whites:
        await _index_has_motmg(redis, post, ttl_seconds=ttl_seconds)
        return post
    try:
        from .scraper import fetch_rotmg_hub_article

        post = await fetch_rotmg_hub_article("motmg")
    except Exception as e:
        logger.bind(error=str(e)).warning("RotMG Hub MOTMG fallback fetch failed")
        return await load_post(redis, "motmg")
    if not post.get("text"):
        return await load_post(redis, "motmg")
    await redis.setex(f"{POST_PREFIX}motmg", ttl_seconds, json.dumps(post))
    await _index_has_motmg(redis, post, ttl_seconds=ttl_seconds)
    names = list(post.get("items") or [])
    if names:
        existing = await hub_item_names(redis)
        merged = list(dict.fromkeys([*names, *existing]))
        await redis.setex(NAMES_KEY, ttl_seconds, json.dumps(merged))
    return post


async def _index_has_motmg(
    redis: aioredis.Redis, post: dict[str, Any], *, ttl_seconds: int
) -> None:
    index = await load_index(redis)
    if any((card.get("slug") or "") == "motmg" for card in index):
        if index and (index[0].get("slug") or "") != "motmg":
            motmg = next(c for c in index if (c.get("slug") or "") == "motmg")
            rest = [c for c in index if (c.get("slug") or "") != "motmg"]
            await redis.setex(INDEX_KEY, ttl_seconds, json.dumps([motmg, *rest]))
        return
    card = {
        "slug": "motmg",
        "title": post.get("title") or "Month of the Mad God Patch Notes",
        "date": post.get("date") or "",
        "url": post.get("url") or post_url("motmg"),
        "thumbnail_url": "",
    }
    await redis.setex(INDEX_KEY, ttl_seconds, json.dumps([card, *index]))


async def seed_motmg_if_empty(
    redis: aioredis.Redis, *, ttl_seconds: int = HUB_TTL_SECONDS
) -> None:
    """Compat wrapper. Always upsert MOTMG, even when older season cards exist."""
    await ensure_motmg_post(redis, ttl_seconds=ttl_seconds)


def _scan_cards(index: list[dict[str, str]]) -> list[dict[str, str]]:
    """Latest 5 index cards, with MOTMG first so Season 30 is never skipped."""
    latest = [card for card in (index or []) if (card.get("slug") or "") != "motmg"][
        :LATEST_SCAN
    ]
    motmg = next(
        (card for card in (index or []) if (card.get("slug") or "") == "motmg"),
        {"slug": "motmg", "title": "Month of the Mad God Patch Notes", "date": "", "url": post_url("motmg"), "thumbnail_url": ""},
    )
    return [motmg, *latest]


async def retrieve_rotmg_hub(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int = HUB_TTL_SECONDS,
    cache_only: bool = True,
    history: Optional[list[str]] = None,
) -> str:
    query = extract_hub_query(message, history=history)
    if not query:
        return ""
    await ensure_motmg_post(redis, ttl_seconds=ttl_seconds)
    index = await load_index(redis)
    soft_miss = query.topic in {"new_item", "new_drop"}
    if not index:
        if cache_only:
            if soft_miss:
                return ""
            return (
                "OFFICIAL PATCH NOTES. The RotMG Hub store is empty. "
                "Say the official patch notes are not cached yet rather "
                "than inventing event details."
            )
        await warm_rotmg_hub(redis, ttl_seconds=ttl_seconds, force=True)
        index = await load_index(redis)
    scan = _scan_cards(index or [])
    posts: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for i, card in enumerate(scan):
        slug = card.get("slug") or ""
        if not slug or slug in seen:
            continue
        seen.add(slug)
        post = await load_post(redis, slug)
        if not post:
            continue
        recency = max(0, LATEST_SCAN - i) * 10
        posts.append((_score_post(post, query, message) + recency, post))
    posts.sort(key=lambda row: row[0], reverse=True)
    matched = [post for score, post in posts if score >= 200]
    if matched:
        chosen = matched[:LATEST_SCAN]
    elif query.topic in {"new_item", "new_drop"}:
        # Found live Sep 21: Season 29 Part 2 / Season 28 Part 2 were the
        # newest dated cards, not Season 30 Part 2. Those notes never name
        # the prism. Prefer the living MOTMG page; otherwise miss to wiki.
        motmg_post = next(
            (p for _s, p in posts if (p.get("slug") or "") == "motmg"),
            None,
        )
        chosen = [motmg_post] if motmg_post else []
    elif query.topic in {"motmg", "encounters", "patch"} or query.survey:
        chosen = [post for _score, post in posts][:LATEST_SCAN]
    else:
        chosen = [post for score, post in posts if score > 0][:2]
    if not chosen and query.survey:
        chosen = [post for _score, post in posts[:2]]
    if not chosen:
        if soft_miss:
            return ""
        return (
            "OFFICIAL PATCH NOTES. No matching RotMG Hub post was in the store "
            "for this question. Say so rather than inventing patch details."
        )
    blocks = []
    for i, post in enumerate(chosen):
        body = _format_post_brief(post, compact=i > 0)
        blocks.append(
            wrap_slot_chunk("patchnotes", body, source=post.get("url") or post_url(post["slug"]))
        )
    return "\n\n".join(blocks)


async def hub_drop_for_query(
    redis: aioredis.Redis, needle: str
) -> Optional[tuple[str, str, str]]:
    """Match a drop ask like 'prism' to a Hub new-item + source.

    Returns (item_name, source_line, post_url) or None.
    """
    token = normalize_hub_name(needle)
    if not token or token in {"item", "items", "drop", "drops"}:
        return None
    await ensure_motmg_post(redis)
    index = await load_index(redis)
    seen: set[str] = set()
    for card in [*_scan_cards(index), *(index or [])]:
        slug = card.get("slug") or ""
        if not slug or slug in seen:
            continue
        seen.add(slug)
        post = await load_post(redis, slug)
        if not post:
            continue
        whites = (post.get("structured") or {}).get("event_whites") or []
        for row in whites:
            name = row.get("name") or ""
            if token in normalize_hub_name(name).split() or normalize_hub_name(name).endswith(token):
                src = row.get("source") or "the latest RotMG Hub patch notes"
                url = post.get("url") or post_url(post.get("slug") or "")
                return name, src, url
        for name in post.get("items") or []:
            key = normalize_hub_name(name)
            if token in key.split() or key.endswith(token):
                url = post.get("url") or post_url(post.get("slug") or "")
                return name, "the latest RotMG Hub patch notes", url
    return None


async def matching_hub_excerpt(
    redis: aioredis.Redis,
    names: list[str],
    *,
    max_names: int = 3,
) -> str:
    """Short Hub excerpt when a build/dungeon names a recent patch item."""
    if not names:
        return ""
    hub_names = {normalize_hub_name(n): n for n in await hub_item_names(redis)}
    if not hub_names:
        return ""
    hits: list[str] = []
    for name in names:
        key = normalize_hub_name(name)
        if key in hub_names:
            hits.append(hub_names[key])
        if len(hits) >= max_names:
            break
    if not hits:
        return ""
    index = await load_index(redis)
    post: Optional[dict[str, Any]] = None
    for card in index[:6]:
        candidate = await load_post(redis, card.get("slug") or "")
        if not candidate:
            continue
        items = {normalize_hub_name(n) for n in candidate.get("items") or []}
        if any(normalize_hub_name(h) in items for h in hits):
            post = candidate
            break
    if not post:
        return ""
    snippet = (
        f"Official Hub note ({post.get('title')}): mentions "
        + ", ".join(hits)
        + ". Patch notes are source of truth for new items; wiki stats may "
        "not exist yet."
    )
    return wrap_slot_chunk(
        "patchnotes",
        snippet,
        source=post.get("url") or post_url(post["slug"]),
    )


async def rotmg_hub_store_status(redis: aioredis.Redis) -> dict[str, int]:
    index = await load_index(redis)
    ttl = await redis.ttl(INDEX_KEY)
    posts = 0
    for card in index:
        if await redis.get(f"{POST_PREFIX}{card.get('slug')}"):
            posts += 1
    sprites = await load_sprite_map(redis)
    return {
        "stored": 1 if index else 0,
        "posts": posts,
        "sprites": len(sprites),
        "ttl_seconds": max(0, int(ttl or 0)),
    }


async def warm_rotmg_hub(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int = HUB_TTL_SECONDS,
    force: bool = False,
    max_posts: Optional[int] = None,
) -> dict[str, int]:
    from .scraper import fetch_rotmg_hub_article, scrape_rotmg_hub_index

    cap = max_posts or (MAX_POSTS_FORCE if force else MAX_POSTS_BOOT)
    existing_index = await load_index(redis)
    try:
        cards = await scrape_rotmg_hub_index(max_posts=cap)
    except Exception as e:
        logger.bind(error=str(e)).warning("RotMG Hub index scrape failed")
        if existing_index:
            return {"stored": 1, "posts": len(existing_index), "error": 1}
        return {"stored": 0, "posts": 0, "error": 1}

    if not cards:
        if existing_index:
            return {"stored": 1, "posts": len(existing_index), "error": 1}
        return {"stored": 0, "posts": 0}

    if not any((card.get("slug") or "") == "motmg" for card in cards):
        cards = [
            {
                "slug": "motmg",
                "title": "Month of the Mad God Patch Notes",
                "date": "",
                "url": post_url("motmg"),
                "thumbnail_url": "",
            },
            *cards,
        ]
    else:
        motmg = next(c for c in cards if (c.get("slug") or "") == "motmg")
        cards = [motmg, *[c for c in cards if (c.get("slug") or "") != "motmg"]]

    await redis.setex(INDEX_KEY, ttl_seconds, json.dumps(cards))
    sprite_map: dict[str, dict[str, str]] = {}
    if force:
        sprite_map = await load_sprite_map(redis)
    all_names: list[str] = []
    stored = 0
    for card in cards:
        slug = card.get("slug") or ""
        if not slug:
            continue
        key = f"{POST_PREFIX}{slug}"
        if not force and await redis.get(key):
            post = await load_post(redis, slug)
            if post:
                stored += 1
                all_names.extend(post.get("items") or [])
                for sp in post.get("sprites") or []:
                    cap_name = sp.get("caption") or ""
                    if cap_name:
                        sprite_map[normalize_hub_name(cap_name)] = {
                            "url": sp.get("url") or "",
                            "caption": cap_name,
                            "post_slug": slug,
                        }
            continue
        try:
            post = await fetch_rotmg_hub_article(
                slug,
                date=card.get("date") or "",
                title=card.get("title") or "",
            )
        except Exception as e:
            logger.bind(slug=slug, error=str(e)).warning("RotMG Hub article fetch failed")
            continue
        await redis.setex(key, ttl_seconds, json.dumps(post))
        stored += 1
        all_names.extend(post.get("items") or [])
        for sp in post.get("sprites") or []:
            cap_name = sp.get("caption") or ""
            if cap_name:
                sprite_map[normalize_hub_name(cap_name)] = {
                    "url": sp.get("url") or "",
                    "caption": cap_name,
                    "post_slug": slug,
                }

    all_names = list(dict.fromkeys(n for n in all_names if n))
    await redis.setex(SPRITES_KEY, ttl_seconds, json.dumps(sprite_map))
    await redis.setex(NAMES_KEY, ttl_seconds, json.dumps(all_names))
    return {"stored": 1, "posts": stored, "sprites": len(sprite_map)}
