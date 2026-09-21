"""Official RotMG Hub patch-note store and retrieval."""
from __future__ import annotations

import json

import pytest

from api.services.rag import build_system_prompt
from api.services.rotmg_hub import (
    INDEX_KEY,
    NAMES_KEY,
    POST_PREFIX,
    SPRITES_KEY,
    extract_hub_query,
    matching_hub_excerpt,
    parse_article_html,
    parse_index_cards,
    retrieve_rotmg_hub,
)
from api.services.specialist_warm import missing_specialist_work

SEASON_29_SLUG = "season-29-part-2-alien-overdrive"
SEASON_28_SLUG = "season-28-part-2-the-return-of-stromwell"


def _old_season_cards() -> list[dict[str, str]]:
    return [
        {
            "slug": SEASON_29_SLUG,
            "title": "Season 29 Part 2: Alien Overdrive",
            "date": "Jul 15, 2026",
            "url": f"https://hub.realmofthemadgod.com/news0/updates0/{SEASON_29_SLUG}",
        },
        {
            "slug": SEASON_28_SLUG,
            "title": "Season 28 Part 2: The Return of Stromwell",
            "date": "May 20, 2026",
            "url": f"https://hub.realmofthemadgod.com/news0/updates0/{SEASON_28_SLUG}",
        },
    ]


def _old_season_post(slug: str, title: str) -> dict:
    return {
        "slug": slug,
        "title": title,
        "date": "",
        "url": f"https://hub.realmofthemadgod.com/news0/updates0/{slug}",
        "text": f"{title} patch notes. Weekly rotation and encounter tweaks. No prism.",
        "items": ["Alien Blaster"] if "alien" in title.lower() else ["Stromwell Staff"],
        "structured": {},
    }


INDEX_HTML = """
<section>
  <a href="/news0/updates0/motmg"
     class="relative border-sem-component-br-component-card w-full">
    <img src="https://static-platform.aghanim.com/pages/abc.webp" />
    <div class="text-sem-component-tx-component-news-date"><p>Aug 31, 2026</p></div>
    <div class="text-sem-component-tx-component-news-title text-heading-h4">
      Month of the Mad God Patch Notes
    </div>
  </a>
</section>
"""

ARTICLE_HTML = """
<h1 class="text-heading-h1">Month of the Mad God Patch Notes</h1>
<div class="blog-item"><div class="blog-text">
<div class="prose max-w-none prose-hub">
<h2>New Shinies Items</h2>
<ul><li>Adventurers Scarf</li><li>Torrential Staff</li></ul>
<h2>New Venerable Equipments</h2>
<table>
<tr><td><b>Base Item</b></td><td><b>New Item</b></td></tr>
<tr><td>Ancient Stone Sword</td><td>Venerable Ancient Stone Sword</td></tr>
<tr><td>Doom Bow</td><td>Venerable Doom Bow</td></tr>
</table>
<h2>New UTs and Encounters for the Realm</h2>
<ul>
<li>Rectangular Prism (Prism) from the Cube Deity</li>
<li>Shifting Shroud (Robe) from the Artificial Slop</li>
</ul>
<h2>The Twelve Dungeons</h2>
<ul><li>Pirate Cave</li><li>The Shatters</li></ul>
<h2>Weekly Dungeon Rotation</h2>
<p>Week 1: The Crawling Depths, Ice Citadel</p>
<table>
<tr>
<td><img src="https://static-platform.aghanim.com/news/dd/35/8d/54/pet.gif" /></td>
<td>Mini Old Forgotten King Pet Skin</td>
</tr>
</table>
</div></div></div>
"""


def test_parse_index_cards():
    cards = parse_index_cards(INDEX_HTML)
    assert len(cards) == 1
    assert cards[0]["slug"] == "motmg"
    assert "Mad God" in cards[0]["title"]
    assert cards[0]["date"] == "Aug 31, 2026"


def test_parse_article_html_extracts_sections_and_sprites():
    post = parse_article_html(
        ARTICLE_HTML,
        "motmg",
        date="Aug 31, 2026",
        title="Month of the Mad God Patch Notes",
    )
    assert post["slug"] == "motmg"
    assert "Adventurers Scarf" in post["items"]
    assert "Venerable Doom Bow" in post["items"]
    assert post["structured"]["new_shinies"] == ["Adventurers Scarf", "Torrential Staff"]
    assert "Pirate Cave" in post["structured"]["time_chamber_dungeons"]
    assert "Week 1" in post["structured"]["weekly_rotation"]
    assert any("aghanim.com/news/" in sp["url"] for sp in post["sprites"])


def test_extract_hub_query():
    assert extract_hub_query("what's in MOTMG this month")
    assert extract_hub_query("Time Chamber dungeons list")
    assert extract_hub_query("week 3 rotation patch notes")
    assert extract_hub_query("new shinies this update")
    assert extract_hub_query("https://hub.realmofthemadgod.com/news0/updates0/motmg")
    assert extract_hub_query("Where does the new prism drop?")
    assert extract_hub_query("what's the new rectangular prism")
    assert extract_hub_query("Attack Bard build") is None
    assert extract_hub_query("Turbine's huntress look") is None
    assert extract_hub_query("I'm a new player") is None


@pytest.mark.asyncio
async def test_retrieve_rotmg_hub_cache_only(redis_client):
    index = [
        {
            "slug": "motmg",
            "title": "Month of the Mad God Patch Notes",
            "date": "Aug 31, 2026",
            "url": "https://hub.realmofthemadgod.com/news0/updates0/motmg",
        }
    ]
    post = parse_article_html(ARTICLE_HTML, "motmg", date="Aug 31, 2026")
    await redis_client.set(INDEX_KEY, json.dumps(index))
    await redis_client.set(f"{POST_PREFIX}motmg", json.dumps(post))

    text = await retrieve_rotmg_hub(
        redis_client,
        "what is in MOTMG",
        cache_only=True,
    )
    assert "hub.realmofthemadgod.com/news0/updates0/motmg" in text
    assert "Venerable Doom Bow" in text or "New shinies" in text


@pytest.mark.asyncio
async def test_new_prism_drop_uses_hub_event_white(redis_client):
    """Found live Sep 21: 'Where does the new prism drop?' hit a generic
    RealmEye prism wiki page with no loot, because Hub routing only matched
    MOTMG/patch keywords, not 'new <item> drop'."""
    from api.services.rotmg_hub import hub_drop_for_query

    post = parse_article_html(ARTICLE_HTML, "motmg", date="Aug 31, 2026")
    await redis_client.set(
        INDEX_KEY,
        json.dumps(
            [
                {
                    "slug": "motmg",
                    "title": "Month of the Mad God Patch Notes",
                    "date": "Aug 31, 2026",
                    "url": "https://hub.realmofthemadgod.com/news0/updates0/motmg",
                }
            ]
        ),
    )
    await redis_client.set(f"{POST_PREFIX}motmg", json.dumps(post))
    text = await retrieve_rotmg_hub(
        redis_client, "Where does the new prism drop?", cache_only=True
    )
    assert "Rectangular Prism" in text
    assert "Cube Deity" in text
    hit = await hub_drop_for_query(redis_client, "prism")
    assert hit is not None
    assert hit[0] == "Rectangular Prism"
    assert "Cube Deity" in hit[1]


@pytest.mark.asyncio
async def test_new_prism_drop_prefers_hub_over_wiki_prisms(redis_client):
    """Found live Sep 21: wiki had a Prisms ability hub with no loot, so
    Claude cited RealmEye instead of the Cube Deity Hub line."""
    from api.models.item import ItemProfile
    from api.services.stored_answers import _drop_reply
    from api.services.wiki_scaling import write_cached_item

    post = parse_article_html(ARTICLE_HTML, "motmg", date="Aug 31, 2026")
    await redis_client.set(
        INDEX_KEY,
        json.dumps(
            [
                {
                    "slug": "motmg",
                    "title": "Month of the Mad God Patch Notes",
                    "date": "Aug 31, 2026",
                    "url": "https://hub.realmofthemadgod.com/news0/updates0/motmg",
                }
            ]
        ),
    )
    await redis_client.set(f"{POST_PREFIX}motmg", json.dumps(post))
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Prisms",
            wiki_url="https://www.realmeye.com/wiki/prisms",
            drop_locations=[],
        ),
        60,
    )
    reply = await _drop_reply(
        redis_client, "Where does the new prism drop?", ttl=60
    )
    assert reply is not None
    assert "Rectangular Prism" in reply.text
    assert "Cube Deity" in reply.text
    assert "realmeye.com/wiki/prisms" not in reply.text.lower()


@pytest.mark.asyncio
async def test_new_item_hub_miss_returns_empty_so_wiki_can_run(redis_client, monkeypatch):
    async def no_seed(*_args, **_kwargs):
        return None

    monkeypatch.setattr("api.services.rotmg_hub.ensure_motmg_post", no_seed)
    text = await retrieve_rotmg_hub(
        redis_client, "Where does the new prism drop?", cache_only=True
    )
    assert text == ""


@pytest.mark.asyncio
async def test_new_prism_uses_motmg_not_old_season_cards(redis_client):
    """Found live Sep 21: Claude cited Season 29 Part 2 Alien Overdrive and
    Season 28 Part 2 The Return of Stromwell. Those cards were the newest
    dated Hub posts; Season 30 Part 2 lives on the MOTMG URL."""
    motmg = parse_article_html(ARTICLE_HTML, "motmg", date="Sep 21, 2026")
    await redis_client.set(INDEX_KEY, json.dumps(_old_season_cards()))
    await redis_client.set(f"{POST_PREFIX}{SEASON_29_SLUG}", json.dumps(
        _old_season_post(SEASON_29_SLUG, "Season 29 Part 2: Alien Overdrive")
    ))
    await redis_client.set(f"{POST_PREFIX}{SEASON_28_SLUG}", json.dumps(
        _old_season_post(SEASON_28_SLUG, "Season 28 Part 2: The Return of Stromwell")
    ))
    await redis_client.set(f"{POST_PREFIX}motmg", json.dumps(motmg))

    text = await retrieve_rotmg_hub(
        redis_client, "Where does the new prism drop?", cache_only=True
    )
    assert "Rectangular Prism" in text
    assert "Cube Deity" in text
    assert "Alien Overdrive" not in text
    assert "Stromwell" not in text


@pytest.mark.asyncio
async def test_ensure_motmg_fetches_when_index_is_older_seasons(
    redis_client, monkeypatch
):
    """Index can be full of Season 29/28 cards while MOTMG was never stored,
    because seed_motmg_if_empty only ran when the index was empty."""
    from api.services.rotmg_hub import hub_drop_for_query

    motmg = parse_article_html(ARTICLE_HTML, "motmg", date="Sep 21, 2026")

    async def fake_fetch(slug: str, **_kwargs):
        assert slug == "motmg"
        return motmg

    monkeypatch.setattr(
        "api.services.scraper.fetch_rotmg_hub_article", fake_fetch
    )
    await redis_client.set(INDEX_KEY, json.dumps(_old_season_cards()))
    await redis_client.set(f"{POST_PREFIX}{SEASON_29_SLUG}", json.dumps(
        _old_season_post(SEASON_29_SLUG, "Season 29 Part 2: Alien Overdrive")
    ))
    await redis_client.set(f"{POST_PREFIX}{SEASON_28_SLUG}", json.dumps(
        _old_season_post(SEASON_28_SLUG, "Season 28 Part 2: The Return of Stromwell")
    ))

    text = await retrieve_rotmg_hub(
        redis_client, "Where does the new prism drop?", cache_only=True
    )
    assert "Rectangular Prism" in text
    assert "Cube Deity" in text
    assert "Alien Overdrive" not in text
    assert "Stromwell" not in text
    hit = await hub_drop_for_query(redis_client, "prism")
    assert hit is not None
    assert hit[0] == "Rectangular Prism"
    assert "Cube Deity" in hit[1]


@pytest.mark.asyncio
async def test_matching_hub_excerpt_exact_new_item_only(redis_client):
    post = parse_article_html(ARTICLE_HTML, "motmg")
    await redis_client.set(
        INDEX_KEY,
        json.dumps([{"slug": "motmg", "title": "MOTMG", "date": "", "url": ""}]),
    )
    await redis_client.set(f"{POST_PREFIX}motmg", json.dumps(post))
    await redis_client.set(NAMES_KEY, json.dumps(post["items"]))

    hit = await matching_hub_excerpt(redis_client, ["Venerable Doom Bow"])
    assert hit
    assert "hub.realmofthemadgod.com" in hit

    miss = await matching_hub_excerpt(redis_client, ["Doom Bow"])
    assert miss == ""


@pytest.mark.asyncio
async def test_hub_sprite_map_lookup(redis_client):
    from api.services.rotmg_hub import hub_sprite_url

    sprites = {
        "venerable doom bow": {
            "url": "https://static-platform.aghanim.com/news/abc.gif",
            "caption": "Venerable Doom Bow",
            "post_slug": "motmg",
        }
    }
    await redis_client.set(SPRITES_KEY, json.dumps(sprites))
    url = await hub_sprite_url(redis_client, "Venerable Doom Bow")
    assert url == "https://static-platform.aghanim.com/news/abc.gif"


def test_system_prompt_mentions_hub_patch_truth():
    prompt = build_system_prompt("Source: https://example.test\nunused")
    assert "Official RotMG Hub patch notes" in prompt
    assert "RealmShark first" in prompt
    assert "hub.realmofthemadgod.com/news0/updates0" in prompt


def test_missing_work_includes_empty_rotmg_hub():
    snap = {
        "abilities": [],
        "hubs": [],
        "items": {"cached": 1, "total": 1},
        "dungeons": {"cached": 1, "total": 1, "index": 1},
        "dps": {"graph": 1, "loadouts": 1, "edges": 1},
        "umi": [],
        "skins": {"stored": 1},
        "enchanting": {"stored": 1},
        "rotmg_hub": {"stored": 0, "posts": 0},
    }
    work = missing_specialist_work(snap)
    assert work["rotmg_hub"] is True
