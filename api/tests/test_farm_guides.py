from api.services.farm_guides import extract_farm_guide, farm_reply_text
from api.services.stored_answers import try_stored_reply


def test_extract_farm_ogmur_and_scythe():
    assert extract_farm_guide("how to farm ogmur") == "ogmur"
    assert extract_farm_guide("How do I farm Shield of Ogmur?") == "ogmur"
    assert extract_farm_guide("ogmur farm") == "ogmur"
    assert extract_farm_guide("how to farm scythe") == "scythe"
    assert extract_farm_guide("farming jailer's scythe") == "scythe"
    assert extract_farm_guide("best attack bard") is None
    assert extract_farm_guide("how to farm life pots") is None


def test_farm_reply_emits_token_and_item_hooks():
    ogmur = farm_reply_text("ogmur") or ""
    assert "[farm:ogmur]" in ogmur
    assert "[item:Shield of Ogmur]" in ogmur
    scythe = farm_reply_text("scythe") or ""
    assert "[farm:scythe]" in scythe
    assert "[item:Jailer's Scythe]" in scythe


async def test_stored_ogmur_farm_skips_claude(redis_client, anon_settings):
    reply = await try_stored_reply(
        redis_client,
        "How to farm Ogmur",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert reply.kind == "farm"
    assert "[farm:ogmur]" in reply.text


def test_web_farm_token_parser():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "web" / "lib" / "farmTldr.ts").read_text(
        encoding="utf-8"
    )
    assert "[farm:ogmur]" not in source or "ogmur:" in source
    assert "parseFarmToken" in source
    assert "Jailer's Scythe" in source
    component = (
        Path(__file__).resolve().parents[2] / "web" / "components" / "chat" / "FarmTldr.tsx"
    ).read_text(encoding="utf-8")
    assert "SwapArrows" in component
    bubble = (
        Path(__file__).resolve().parents[2]
        / "web"
        / "components"
        / "chat"
        / "MessageBubble.tsx"
    ).read_text(encoding="utf-8")
    assert "FarmTldr" in bubble
