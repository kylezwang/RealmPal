"""
Ingestion pipeline: scraped data -> chunks -> embeddings -> Qdrant upsert.

Design principles (learned from Certio):
- Persistent vector store, never rebuild from scratch per request
- Proper upsert semantics with metadata (source, scraped_at, username)
- Sanitize content before storage to prevent prompt injection downstream
"""
import asyncio
import hashlib
import html
import re
from datetime import datetime
from typing import Any

from loguru import logger
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    PayloadSchemaType,
)

from ..config import get_settings
from ..models.player import PlayerProfile
from ..models.item import ItemProfile
from ..models.build import AbilityScalingEdge, StatScalingGraph
from .chunks import split_guide
from .embeddings import VECTOR_SIZE, embed_texts
from .scraper import scrape_wiki_page
from .realmshark import (
    REALMSHARK_PAGE,
    fetch_builds,
    fetch_leaderboard,
    format_graph,
    format_loadouts,
    graph_from_builds,
    loadouts_from_rows,
)
# VECTOR_SIZE now lives in embeddings.py, re-exported via the import above,
# since it depends on which embedding backend is active (768 for Ollama's
# nomic-embed-text, 1024 for Voyage's voyage-4-lite) - see that module's
# docstring. Duplicating it here as a second hardcoded constant is exactly
# what caused the stale "voyage-3-lite is also 768 dims" assumption that
# was never actually true.


def collection() -> str:
    """
    Deployment-scoped collection name.

    Resolved per call rather than pinned to a module constant, which is what
    let `settings.qdrant_collection` sit unused while "realm_pal" was
    hardcoded here and in the retrieval path.
    """
    return get_settings().qdrant_collection_name


def _sanitize(text: str) -> str:
    """
    Strip HTML, escape prompt-injection delimiters.
    Prevents RAG context from containing instructions that manipulate Claude.
    """
    # Unescape HTML entities, then strip tags
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove potential prompt-injection sequences
    text = re.sub(r"(</?(system|human|assistant|instruction)[^>]*>)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _doc_id(source: str, key: str) -> str:
    """Deterministic ID so upsert is idempotent."""
    return hashlib.sha256(f"{source}:{key}".encode()).hexdigest()[:32]


async def ensure_collection(client: AsyncQdrantClient) -> None:
    """Create the Qdrant collection if it doesn't exist."""
    name = collection()
    collections = await client.get_collections()
    names = [c.name for c in collections.collections]
    if name not in names:
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.bind(collection=name).info("Created Qdrant collection")


async def ingest_player(client: AsyncQdrantClient, profile: PlayerProfile) -> None:
    """Convert a PlayerProfile to a Qdrant document and upsert."""
    await ensure_collection(client)

    # Account summary only | character names and loadouts live on the
    # scraped PlayerCard, and listing them here made the model reprint
    # a gear table on every lookup.
    pet = profile.top_pet.name if profile.top_pet else "unknown"
    text = (
        f"Player: {profile.username}\n"
        f"Guild: {profile.guild or 'No guild'} ({profile.guild_rank or ''})\n"
        f"Fame: {profile.fame or 'unknown'}\n"
        f"Account fame: {profile.account_fame if profile.account_fame is not None else 'unknown'}\n"
        f"Total exaltations: {profile.total_exaltations if profile.total_exaltations is not None else 'unknown'}\n"
        f"Top pet: {pet}\n"
        f"Last seen: {profile.last_seen or 'unknown'}"
    )
    text = _sanitize(text)

    vectors = await embed_texts([text])
    doc_id = _doc_id("realmeye_player", profile.username.lower())
    url = f"https://www.realmeye.com/player/{profile.username}"

    await client.upsert(
        collection_name=collection(),
        points=[
            PointStruct(
                id=doc_id,
                vector=vectors[0],
                payload={
                    "source": "realmeye_player",
                    "username": profile.username.lower(),
                    "text": text,
                    "url": url,
                    "scraped_at": profile.scraped_at.isoformat(),
                },
            )
        ],
    )
    logger.bind(username=profile.username).info("Ingested player profile to Qdrant")


async def ingest_item(client: AsyncQdrantClient, item: ItemProfile) -> None:
    """Convert an ItemProfile to a Qdrant document and upsert."""
    await ensure_collection(client)

    stat_lines = "\n".join(f"  {k}: {v}" for k, v in item.stats.items()) if item.stats else ""
    text = (
        f"Item: {item.name}\n"
        f"Type: {item.type or 'unknown'} | Tier: {item.tier or 'unknown'}\n"
        f"Description: {item.description or ''}\n"
        f"Stats:\n{stat_lines or '  unknown'}\n"
        f"Drop locations: {', '.join(item.drop_locations) or 'unknown'}\n"
        f"Shiny sprite: {'yes' if item.shiny_sprite_url else 'no'}"
    )
    text = _sanitize(text)

    vectors = await embed_texts([text])
    doc_id = _doc_id("realmeye_item", item.name.lower())

    payload: dict[str, Any] = {
        "source": "realmeye_item",
        "item_name": item.name,
        "text": text,
        "url": item.wiki_url or f"https://www.realmeye.com/wiki/{item.name.lower().replace(' ', '-')}",
        "scraped_at": datetime.utcnow().isoformat(),
    }
    if item.sprite_url:
        payload["sprite_url"] = item.sprite_url
    if item.shiny_sprite_url:
        payload["shiny_sprite_url"] = item.shiny_sprite_url

    await client.upsert(
        collection_name=collection(),
        points=[PointStruct(id=doc_id, vector=vectors[0], payload=payload)],
    )
    logger.bind(item_name=item.name).info("Ingested item to Qdrant")


async def ingest_guide(
    client: AsyncQdrantClient,
    *,
    title: str,
    content: str,
    source: str,
    url: str,
) -> None:
    """Ingest a guide or wiki article (chunked if long)."""
    await ensure_collection(client)

    clean = _sanitize(content)
    # Split on paragraph/sentence boundaries so a ring row is never cut in
    # half | a fixed window used to strand "+7 ATT" from its item name.
    chunks = split_guide(clean)

    if not chunks:
        return

    vectors = await embed_texts(chunks)
    points = []
    for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
        doc_id = _doc_id(source, f"{title}:{idx}")
        points.append(
            PointStruct(
                id=doc_id,
                vector=vec,
                payload={
                    "source": source,
                    "title": title,
                    "chunk_index": idx,
                    "text": chunk,
                    "url": url,
                    "scraped_at": datetime.utcnow().isoformat(),
                },
            )
        )

    await client.upsert(collection_name=collection(), points=points)
    logger.bind(title=title, chunks=len(chunks), source=source).info("Ingested guide")


async def ingest_wiki_page(client: AsyncQdrantClient, slug: str) -> None:
    """Scrape a realmeye.com/wiki/{slug} article live and ingest it as a guide."""
    title, content, url = await scrape_wiki_page(slug)
    await ingest_guide(client, title=title, content=content, source="realmeye_wiki", url=url)


# Core equipment wiki hubs | enough context for class-slot mapping, tier
# ladders, and enchanting mechanics without crawling every individual item
# page up front (those are better ingested lazily on first mention).
WIKI_WEAPON_SLUGS = (
    "daggers",
    "dual-blades",
    "staves",
    "spellblades",
    "swords",
    "flails",
    "bows",
    "longbows",
    "wands",
    "morning-stars",
    "katanas",
    "tachis",
)

WIKI_ABILITY_SLUGS = (
    "cloaks",
    "quivers",
    "spells",
    "tomes",
    "helms",
    "shields",
    "seals",
    "poisons",
    "skulls",
    "traps",
    "orbs",
    "prisms",
    "scepters",
    "stars",
    "wakizashi",
    "lutes",
    "maces",
    "sheaths",
    "sigils",
)

WIKI_ARMOR_SLUGS = (
    "leather-armors",
    "robes",
    "heavy-armors",
)

WIKI_HUB_SLUGS = (
    "weapons",
    "ability-items",
    "armor",
    "rings",
    "enchanting",
    *WIKI_WEAPON_SLUGS,
    *WIKI_ABILITY_SLUGS,
    *WIKI_ARMOR_SLUGS,
)


async def seed_wiki_hubs(
    client: AsyncQdrantClient,
    slugs: tuple[str, ...] = WIKI_HUB_SLUGS,
) -> dict[str, int]:
    """Ingest the foundational RealmEye equipment wiki hubs into Qdrant."""
    counts: dict[str, int] = {}
    for slug in slugs:
        await ingest_wiki_page(client, slug)
        counts[slug] = 1
        logger.bind(slug=slug).info("Seeded wiki hub")
    return counts


def _dps_build_text(graph: StatScalingGraph, edge: AbilityScalingEdge, loadouts) -> str:
    abilities = ", ".join(edge.ability_names)
    return (
        f"RealmShark DPS build: {edge.label}\n"
        f"Class: {edge.class_name}\n"
        f"Primary 8/8 stat: {edge.stat}\n"
        f"Ability items whose damage or effect scales with {edge.stat}: {abilities}\n"
        f"Note: {edge.note or edge.label}\n"
        f"Other {edge.class_name} abilities that are not listed here do not scale "
        f"with {edge.stat} and should not be recommended for a {edge.stat} "
        f"{edge.class_name} build.\n"
        f"{format_loadouts(edge.label, loadouts)}\n"
        f"Source: {REALMSHARK_PAGE}"
    )


async def ingest_dps_graph(client: AsyncQdrantClient, graph: StatScalingGraph) -> None:
    """Upsert the full scaling graph plus one document per class+stat build."""
    await ensure_collection(client)

    overview = _sanitize(format_graph(graph))
    texts = [overview]
    meta: list[tuple[str, str, str, str]] = [("graph:seasonal", "scaling_graph", "", "")]
    for edge in graph.edges:
        loadouts = graph.top_loadouts.get(edge.build_id, [])
        texts.append(_sanitize(_dps_build_text(graph, edge, loadouts)))
        meta.append((edge.build_id, "dps_build", edge.class_name, edge.stat))

    vectors = await embed_texts(texts)
    now = datetime.utcnow().isoformat()
    points = []
    for (key, kind, class_name, stat), vec, text in zip(meta, vectors, texts):
        payload: dict[str, Any] = {
            "source": "realmshark_dps",
            "kind": kind,
            "text": text,
            "url": REALMSHARK_PAGE,
            "scraped_at": now,
        }
        if kind == "dps_build":
            payload["build_id"] = key
            payload["class_name"] = class_name
            payload["stat"] = stat
        points.append(
            PointStruct(
                id=_doc_id("realmshark_dps", key),
                vector=vec,
                payload=payload,
            )
        )

    await client.upsert(collection_name=collection(), points=points)
    logger.bind(builds=len(graph.edges)).info("Ingested RealmShark DPS knowledge graph")


async def seed_dps_knowledge(client: AsyncQdrantClient) -> int:
    """Fetch the seasonal builds catalog + top-5 loadouts and ingest them."""
    payload = await fetch_builds(seasonal=True)
    graph = graph_from_builds(payload, seasonal=True)
    sem = asyncio.Semaphore(4)

    async def _one(edge: AbilityScalingEdge) -> None:
        async with sem:
            try:
                board = await fetch_leaderboard(
                    edge.build_id, seasonal=True, limit=5, season=graph.season
                )
                graph.top_loadouts[edge.build_id] = loadouts_from_rows(board)
            except Exception as e:
                logger.bind(build=edge.build_id, error=str(e)).warning(
                    "Skipping leaderboard for DPS build"
                )

    await asyncio.gather(*[_one(edge) for edge in graph.edges])
    await ingest_dps_graph(client, graph)
    return len(graph.edges)
