"""UmiEnjoyers BIS tabs are query params, not a single general dump."""
import json

from api.services.scraper import parse_umi_tab_labels, parse_umi_tab_links, umi_bis_url
from api.services.wiki_scaling import retrieve_umi_bis


def test_umi_bis_url_uses_speed_wizard_tab():
    assert umi_bis_url("Wizard", "speed-wizard") == (
        "https://www.umienjoyers.com/guides/best-in-slot/wizard?tab=speed-wizard"
    )
    assert umi_bis_url("Summoner").endswith("?tab=general")


def test_parse_umi_tab_links_keeps_build_tabs_not_class_nav():
    page = "https://www.umienjoyers.com/guides/best-in-slot/wizard?tab=general"
    links = [
        ("/guides/best-in-slot/summoner", "Summoner"),
        ("/guides/best-in-slot/wizard?tab=attack-wizard", "Attack Wizard"),
        ("?tab=speed-wizard", "Speed Wizard"),
        ("?tab=general", "General"),
    ]
    tabs = parse_umi_tab_links(page, links)
    slugs = [slug for slug, _name in tabs]
    assert slugs == ["attack-wizard", "speed-wizard", "general"]
    assert "summoner" not in slugs


def test_parse_umi_tab_links_always_includes_general():
    page = "https://www.umienjoyers.com/guides/best-in-slot/summoner"
    tabs = parse_umi_tab_links(page, [("/guides/best-in-slot/wizard", "Wizard")])
    assert tabs == [("general", "General")]


def test_parse_umi_tab_labels_slugifies_speed_wizard():
    tabs = parse_umi_tab_labels(
        ["Wizard", "Speed Wizard", "Attack Wizard", "General", "Sign in"]
    )
    assert tabs == [
        ("speed-wizard", "Speed Wizard"),
        ("attack-wizard", "Attack Wizard"),
        ("general", "General"),
    ]


async def test_retrieve_umi_bis_prefers_matching_stat_tab(redis_client):
    await redis_client.set(
        "umi:bis:v2:wizard",
        json.dumps(
            [
                "## Umi tab: Speed Wizard (?tab=speed-wizard)\nTideturner Trident",
                "https://www.umienjoyers.com/guides/best-in-slot/wizard?tab=general",
            ]
        ),
    )
    text = await retrieve_umi_bis(
        redis_client, "Wizard", ttl_seconds=60, cache_only=True, stat="Speed"
    )
    assert "?tab=speed-wizard" in text
    assert "Tideturner Trident" in text
    assert "Prefer the Umi tab that matches Speed Wizard" in text
