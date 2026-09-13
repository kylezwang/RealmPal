"""Fill specialist Redis stores from RealmEye. Chat must not do this.

  cd repo-root
  .\\api\\.venv\\Scripts\\python.exe -m api.scripts.warm_specialists --status
  .\\api\\.venv\\Scripts\\python.exe -m api.scripts.warm_specialists
  .\\api\\.venv\\Scripts\\python.exe -m api.scripts.warm_specialists Huntress
"""
import asyncio
import sys
from pathlib import Path

import redis.asyncio as aioredis

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import get_settings
from api.services.specialist_warm import specialist_snapshot, warm_all_specialists


def _print_status(snapshot: dict) -> None:
    print("Abilities")
    missing = []
    for row in snapshot["abilities"]:
        hours = row["ttl_seconds"] / 3600
        ttl = f"{hours:.1f}h" if row["ttl_seconds"] else "—"
        print(f"  {row['class_name']:<14} {row['abilities']:>9}  {ttl}")
        if row["abilities"] <= 0:
            missing.append(row["class_name"])
    filled = sum(1 for row in snapshot["abilities"] if row["abilities"] > 0)
    print(f"  {filled}/{len(snapshot['abilities'])} classes stored")
    if missing:
        print("  Empty:", ", ".join(missing))

    hubs = snapshot["hubs"]
    hub_filled = sum(1 for row in hubs if row["items"] > 0)
    print(f"Hubs              {hub_filled}/{len(hubs)}")
    empty_hubs = [row["slug"] for row in hubs if row["items"] <= 0]
    if empty_hubs:
        print("  Empty:", ", ".join(empty_hubs))

    items = snapshot["items"]
    print(f"Item profiles     {items['cached']}/{items['total']}")
    dungeons = snapshot["dungeons"]
    print(
        f"Dungeon guides    {dungeons['cached']}/{dungeons['total']}  "
        f"index={'yes' if dungeons['index'] else 'no'}"
    )
    dps = snapshot["dps"]
    print(
        f"DPS boards        graph={'yes' if dps['graph'] else 'no'}  "
        f"loadouts {dps['loadouts']}/{dps['edges']}"
    )
    umi_filled = sum(1 for row in snapshot["umi"] if row["stored"])
    print(f"Umi BIS           {umi_filled}/{len(snapshot['umi'])}")
    skins = snapshot["skins"]
    print(
        f"Skin catalog      {'yes' if skins['stored'] else 'no'}  "
        f"{skins['classes']} classes"
    )
    enchanting = snapshot.get("enchanting") or {}
    print(
        f"Enchanting rolls  {'yes' if enchanting.get('stored') else 'no'}  "
        f"{enchanting.get('rolls', 0)} rolls"
    )
    print("Players           live scrape (not stored)")


async def main() -> None:
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url)
    args = tuple(sys.argv[1:])
    try:
        if args and args[0] == "--status":
            _print_status(await specialist_snapshot(redis))
            return
        if args:
            from api.services.wiki_scaling import warm_all_class_scaling

            abilities = await warm_all_class_scaling(
                redis,
                ttl_seconds=settings.wiki_ttl_seconds,
                classes=args,
            )
            print(
                f"Stored {sum(abilities.values())} abilities across "
                f"{len(abilities)} classes: {abilities}"
            )
            return
        result = await warm_all_specialists(
            redis,
            ttl_seconds=settings.wiki_ttl_seconds,
            force=True,
        )
        abilities = result.get("abilities") or {}
        print(
            f"Abilities {sum(abilities.values())} across {len(abilities)} classes"
        )
        print(f"Hubs {len(result.get('hubs') or {})}")
        print(f"Items {result.get('items')}")
        print(f"Dungeons {result.get('dungeons')}")
        print(f"DPS {result.get('dps')}")
        print(f"Umi {sum((result.get('umi') or {}).values())}")
        print(f"Skins {result.get('skins')}")
        print(f"Enchanting {result.get('enchanting')}")
        print(f"Sets {result.get('sets')}")
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
