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

## History

### Until Sep 14, 2026 (production trace added below)
The table above was the full base-case set as of Sep 13. Row added below
from a real Sep 14 production session, found while reviewing live logs
after the skin-visualizer scraper fix.

## Quota/meter depletion policy, confirmed Sep 16, 2026

A turn that never calls Claude does not spend quota for any of the three
roles. Only a real model call meters.

| Account type | Stored answer (no Claude) | Real Claude call |
|---|---|---|
| Anonymous (no account) | Does not deplete | Depletes the daily 3 in-depth responses |
| Free (signed in) | Does not deplete | Depletes the daily free-message quota |
| Paid | Does not deplete the Claude included-reply meter | Depletes |

Logic: `api/routers/chat.py`'s `chat_stream()` returns a stored hit before
`_enforce_quota()` and `consume_claude_reply()`. Those run only on the
Claude branch.

Tests: `test_drop_question_never_hits_the_llm` (anonymous, `peek() == 0`),
`test_anonymous_at_daily_limit_still_gets_stored_answer`,
`test_anonymous_claude_turn_still_spends_daily_quota`,
`test_signed_in_stored_answer_skips_daily_quota` (free, `peek() == 0`),
`test_paid_stored_hit_does_not_increment_claude_meter` (paid meter
untouched, `used == 0`) - all in `api/tests/test_stored_answers.py`.

Guest UI copy for that daily 3 is "in-depth responses" as of later Sep 16
(only Claude turns spend it). Stored (no-Claude) turns stay free of that
daily meter for every role, even after it is spent, but every `/chat/stream`
turn including those stored hits is burst-capped at 20/min guest and
60/min signed-in (`chat_burst_quota_for`). Player lookups are stored
(scrape + fact bullets, no Claude). The in-depth paywall modal opens every time a spent in-depth try 402s.
Later Claude 402s still keep the user message and pin leftover
suggestions above the input (guest: create an account; signed-in: RealmPal
Pro) until the user hides them.

## History
### Until Sep 16, 2026 (later same day)
The current-policy table said "Depletes the daily 3-message quota" for
anonymous Claude turns. Copy was then "AI-powered responses", then
"in-depth prompts". Depletion rules did not change. Stored answers after
the daily cap had no burst ceiling, and every 402 re-opened the paywall.
Later leftover suggestions after a 402 were injected into the chat
transcript instead of sitting above the input. Player lookups still called
Claude (or 402'd) after the cap. For a stretch the same day, the paywall
modal showed only on the first 402 per quota window.

### Until Sep 16, 2026
Quota/meter depletion policy, confirmed Sep 14, 2026:

Verified against live test runs (not just reading the code) that stored
answers (no Claude call) deplete quota differently by account type, and
that this is intentional, not a bug:

| Account type | Stored answer | Real Claude call |
|---|---|---|
| Anonymous (no account) | **Depletes** the daily 3-message quota - intentional, funnels guests to sign in | Depletes |
| Free (signed in) | Does not deplete | Depletes |
| Paid | Does not deplete the Claude included-reply meter | Depletes |

Logic: `api/routers/chat.py`'s `chat_stream()`, the `if stored:` block only
calls `_enforce_quota()` when `quota.is_anonymous` is true (resolved in
`api/services/rate_limit.py`'s `quota_for()` - anonymous only when there is
no verified user at all). `consume_claude_reply()` is only called in the
non-stored branch below, so it never runs for a stored hit regardless of
account type.

Tests (all passing as of Sep 14): `test_drop_question_never_hits_the_llm`
(anonymous depletes, `peek() == 1`), `test_signed_in_stored_answer_skips_daily_quota`
(free does not, `peek() == 0`), `test_paid_stored_hit_does_not_increment_claude_meter`
(paid meter untouched, `used == 0`) - all in `api/tests/test_stored_answers.py`.

## Production trace, Sep 14, 2026

| Prompt sequence | In / out | Cost | Notes |
|---|---|---|---|
| "What does Vampire Slayer Archer look like with Large/small Crown cloth?" then "Sorry I mean Mini Royal Crossbowman Archer" | 11,083/100, then 11,031/62 | $0.0116 + $0.0113 = **$0.0229** | The first message correctly hit the `kind: "skin"` stored path (code composite, no model). The follow-up correction ("Sorry I mean X", no cloth/dye/clothing/accessory keyword) fell through to two real `claude-haiku-4-5` calls with irrelevant RAG context (`query: "Archer quivers ability scaling"`) instead of re-rendering the same outfit with a corrected skin name. Root cause: `is_skin_visualize_query()` requires `_mentions_outfit_piece()` (cloth/dye/clothing/accessory) before treating a message as an outfit follow-up, and separately `_extract_outfit_from_text()`'s catch-all fallback stuffed the entire raw sentence into the `clothing` field instead of extracting the actual skin name. Fixed same day: see `CHANGELOG.md` `[2026.09.14]`, added a correction-phrase recognizer (`sorry i mean` / `i meant` / `actually` / `no i mean`) that bypasses the outfit-piece requirement and strips the correction cue before extraction. |
| "Best items for attack Kensei" then "Full shiny divine enforcer, ballistic star, straitjacket, and lean" | 9,605/1,169 for the build turn | $0.0464 (build turn only; the shiny-divine turn was a stored hit, $0) | Two separate bugs found in the same session, both fixed same day (see `CHANGELOG.md` `[2026.09.14]`): (1) the enchant brief recommended **Infernal Anger**, an Awakened Enchantment exclusive to Berserker's Breastplate, as a generic Attack option for an unrelated Kensei sheath - RealmEye's Awakened table has no eligible/slot column at all (each one only rolls on one or a few named items), and the scraper defaulted the missing cell to `ALL`. (2) the shiny-divine follow-up (a four-item list, no "with") matched the single-item shiny/divine regex instead of the set visualizer, so the whole comma list got sent to RealmEye as one bogus wiki slug (`/wiki/enforcer,-ballistic-star,-straitjacket,-and-lean`), 404ing after two 15s scrape retries per occurrence and leaving the set visualizer spinning. |
