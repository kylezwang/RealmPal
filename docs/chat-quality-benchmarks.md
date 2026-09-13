# Chat quality benchmarks

Starting traces for token + factual quality, plus the stored-answer map
for the same prompts. More logs incoming. Operational notes stay in
`BACKLOG.md`.

Moved out of `BACKLOG.md` on Sep 13, 2026. The map and 10-trace table
below are the set as they existed that day.

## History

### Until Sep 13, 2026

Lived in `BACKLOG.md` under **Chat quality benchmarks → stored-answer
map** and **Chat quality base cases**. Copied here in full the same day.
No rows were dropped.

## Stored-answer map

Almost all of these should skip Claude after minting. Only live player
lookups stay off this path.

| Benchmark prompt | Stored? | How |
|---|---|---|
| Best attack Bard / Dex Huntress / Wis Mystic / Dex Samurai / Mana Mystic / Wis Kensei | **Yes** | `wiki:build:v1:{class}:{stat}`. Huntress appears twice in the log. One brief after mint. |
| Guide to complete Hardmode Shatters | **Yes** | Wiki dump from warmed `wiki:guide:v6:` (`wiki:guide-brief:v2`). HM focuses the last Hard Mode heading, no regular-page lead. Keep the HMS fact: after the purple dome (the Source) on the clear to Nox, drag all 4 branches/flames to center. “Wings” is regular Shatters. |
| Where does X drop? (same family; not in the table) | **Yes** | Template from `item:profile:v3` `drop_locations`. No model. |
| What does Vampire Slayer Archer look like with Large Crown Cloth? | **Mostly no model already** | Skin composite is code. Short chat text can be a template. That row burned ~$0.02 on unused wiki RAG. Skip RAG on skin-only asks. |
| Look up player Turbine | **No. Keep live** | Player profiles go stale in minutes (`player_ttl_seconds` = 120). Do not store “the Turbine answer.” Still skip wiki RAG on player-only lookups (that row paid for unused chunks). |

Rule of thumb: same question for every user (build, dungeon how-to, drops, best bows) → RealmPal brief. About **this player right now** → live scrape, keep it cheap. Constrained follow-ups (“no ST”, “white bag only”) still stream Claude. They do not replace the brief.

## Base-case traces

| Prompt | In / out | Cost | Notes |
|---|---|---|---|
| What does Vampire Slayer Archer look like with Large Crown Cloth? | 6,548 / 56 | $0.0205 | Two wiki RAG pulls (incl. unused Archer ability scaling). Composite is not LLM. |
| Guide to complete Hardmode Shatters | 11,603 / 848 | $0.0475 | `context_chunks: 8`. Wiki RAG mixed regular Shatters (“wings”) into HMS. Item-card burst hit anonymous lookup 12/min (fetches were unauthenticated). |
| Look up player Turbine | 4,139 / 94 | $0.0138 | Wiki RAG still ran for a player-only lookup. |
| Best attack build for Bard (after player lookup) | 8,343 / 846 | $0.0377 | 15s to first token (`context_chunks: 18`). RAG glued prior “Look up player Turbine” into the query. Live wiki crawl held the one Chromium lock so item cards (Triangle, Doom Bow, Ritual Robe) queued. Curly-apostrophe slugs 8s-timed-out. Doom Bow leaked into a Bard takeaway. |
| Best items for a Dex Huntress | 7,660 / 963 | $0.0374 | Wiki specialist cancelled so item cards could load. Answer missed the **2 DEX-scaling traps**. Chat must read the twice-weekly stored hub, not live-scrape. |
| Best items for a Dex Huntress (stored hub) | 8,547 / 594 | $0.0346 | Fast. Named Lotus + Honeytomb. |
| Best wis mystic build? | 9,426 / 981 | $0.0430 | No stored Mystic wiki (`answering from DPS boards`). Not on RealmShark. |
| Best dex samurai build? | 9,077 / 813 | $0.0394 | RealmShark board present; no stored Samurai wiki. Invented Berserk on **Ryu's Blade** (Lotus effect leaked from the Huntress turn / global prompt). |
| Best items for a Mana mystic (after warm) | 11,041 / 1,065 | $0.0491 | Fast chat. Item cards still live-scraped. They read `item:profile:v2` while warm wrote v3. Fixed; cards now prefer v3. |
| Best items for a Wis Kensei (after v3 + warm) | 8,906 / 994 | $0.0416 | Chat + almost every card from Redis. Only Rift Rippers scraped. Grid showed Ninja leather (Hirejou Tenne, Venerable Coral Silk, Centaur's Shielding). Grid now filters `wearable=false`; comparison prose stays. |

Recorded chat costs (10 traces) average **$0.0365**/msg. The eight build-style rows average **$0.041**. Stored hits are ~$0.

**HMS fact to keep:** after the purple dome (the Source) on the clear to Nox (2nd boss), drag all 4 branches/flames to the center. “Wings” is regular The Shatters, not Hardmode.
