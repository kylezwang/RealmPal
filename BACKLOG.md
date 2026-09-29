# Backlog

Last updated: Sep 22, 2026

Target platform: **Azure**. Chosen for portfolio reasons - it's screened for by the
enterprise half of the roles being targeted, and invisible to the startup half.
Container Apps for compute (the API needs a real container for Playwright, which
rules out serverless), Entra External ID for identity, Key Vault for secrets.
SQLite on a mounted volume until billing lands, then Azure Postgres.
**Claude via Microsoft Foundry**, not a generic Anthropic API key (see below).

**See** `.cursor/rules/development-workflow.mdc`**:** Completed work moves from here → CHANGELOG.md (technical details) → git history. BACKLOG looks forward only; don't keep stale copy.

Resume order when context is fresh:

1. **Not yet fixed - every chat message unconditionally scrapes+ingests the signed-in user's own IGN profile**, even for messages with nothing to do with the player (`api/routers/chat.py`, `if body.ign:` block, ~line 588 - "Player profiles change constantly, scrape on lookup" comment explains the *intent* but this fires on every uncached message regardless of whether the message needs it, e.g. a pure "how to do X dungeon" question). Confirmed Sep 14: asking about Moonlight Village still triggered a 14s `Scraping player profile {'username': 'Turbine'}` call. This adds unnecessary load to the shared Playwright semaphore. Worth reconsidering: only scrape when `player_only`/`buildish` is true for *this* message (the router already computes these flags for the RAG-skip logic right below it), not unconditionally whenever `body.ign` is set.
2. **Build/loadout quality - remaining after Sep 16 store work.** Ranking: general gameplay (class primary stat) is RealmShark first, then the player overlay, Umi in synergy, RealmEye class-page Maximum Achievable Stats last. Unique class+stat builds (asked stat is not the class's usual one) stack ability/armor/ring from Maximum Achievable Stats unless a RealmShark top 5 or matching Umi tab already has that full loadout. Overlay family cores stay general-play weapons/robes/leather and must not replace a dedicated unique set. CLASS_STAT_SLOT_OVERRIDES still win (Attack Bard Triangle + Vesture; Samurai/Kensei Dex or Vit: Tools of the Tarnished + Fungal Breastplate). That max-stats table is scraped (`scrape_class_max_stats`, `wiki:class-maxstats:v1:{class}`) and injected cache-only. `top_build_items()` majority-picks RealmShark slots (skips Limited Edition reskins) then applies the overlay. Closed-vocab typos work for classes (`brd` → Bard), dungeon names (`moonlite`/`shaters`), and nickname keys. Enchant/DPS comparison extracts every mentioned nickname (`cbow` vs `lbow`). In-depth Claude turns now use `run_slot_agents` plus SET VISUALIZER PICKS and one matching RealmShark top-5, not the old full Umi/wiki/max-stats dump.
  - **Family cores (player overlay, Sep 16):** weapon bases by first hub: Unholy Sacrifice (staves), Makakoyumi (bows), Fractal Blades + Phantom Sickle (daggers), Divinity + Damnation (swords), Lumiaire (wands), Enforcer + Valor + Tools of the Tarnished (katanas). Robe bases: Vesture of Duality, Diplomatic Robe, Flowering Kimono. Leather: Cackling Straitjacket, Centaur's Shielding, Ethereal Happi. Heavy: no forced list except Samurai/Kensei Dexterity and Vitality (Tools of the Tarnished + Fungal Breastplate). Rings always name Lean, Crown, Gemstone, Kage, and Snake Eye Ring. Abilities from RealmShark when a board exists, else the ability specialist. Family cores are brief bases for Claude, not forced `overlay_slot_picks` (Speed Wizard may still use Tideturner). Attack Bard still forces Triangle + Vesture.
  - **More class+stat overlays** in the same shape as Attack Bard: exact wiki titles for weapon / ability / armor / ring when a wiki row is the wrong playstyle. Next worth writing down: Dex Bard, Attack Archer.
  - **UmiEnjoyers**: in-depth turns now inject every BIS tab as the alternative list for weapon, ability, armor, and ring. Still not used for set-visualizer majority picks.
  - **Stored briefs vs visualizer** can still diverge (`wiki:build:v3:{class}:{stat}` vs `top_build_items()`). Until Sep 18, 2026 this key was `wiki:build:v2`.
  - **RealmShark** missing boards still fall back to a sister-class weapon family in text briefs (Attack Huntress → Archer bows). Document that fallback as sister-class, not the wrong ability slot.
  - **DPS specialist (Sep 17):** RealmShark leaderboard DPS, weapon/ability split, stats, and on-character enchants are the source of truth (`dps:top:v2`) for class ceilings. A named player's class ("What's the DPS for Turbine's bard?") scrapes that RealmEye profile, picks the character, and reconstructs dummy DPS from worn wiki pages plus sheet stats. Number asks route to the DPS slot only. Wiki shot data plus ATT/DEX, Damaging 1.25, Curse 1.25, Exposed x1.20 on the dummy, Vulnerable 115%, and enchanting-table weapon damage/RoF reconstruct the weapon half (within 1% of live Unholy Sacrifice rows). Wiki ability scaling times Stat Mod Multiplier reconstructs the ability half without Damaging. Every worn wiki page and on-character enchant is scanned for status grants and stat procs before reconstruct (no item-name special cases). Armor/ring swaps apply On Equip plus dummy-uptime procs. On Shoot combat deltas apply in the dummy window. Remaining: minion fire interval beyond the ability residual, MP Cost Reduction re-simulating ability-use count. Enemy DEF now works (`enemy_def`, subtracted per projectile behind a 10% floor, with Damaging before it and Curse/Exposed/Vulnerable after) and the brief carries both the RealmShark-style 0 DEF full-buff ceiling and the same set on a 15 DEF guild hall dummy with only the debuffs this set inflicts itself (named with the source item, never copied from an earlier class in the same chat). Working Attack/Dexterity lists every proc and its item. Still open:
    - **Percent-of-another-stat bonuses are not read** (`on_equip_bonuses`). Ring of Cubed Wisdom is `+15% ATT / +15% DEX ... Equal to bonus WIS`, Hivemind Circlet is `+10% WIS equal to ATT`, and 21 cached items have at least one. We correctly decline to read these as flat bonuses (a `%` is not matched), so a *player's* DPS is fine, since RealmEye's sheet already totals worn gear. It only bites hypothetical swaps, where we add On Equip ourselves and would understate a ring like Cubed Wisdom. Needs a second bonus bucket (share of another stat, resolved after flat bonuses) rather than an extra `_BONUS_PAT` entry. Do not "fix" this by letting `%` into the flat pattern.
    - **Burst-fire weapons use the wrong attack rate** (`attacks_per_second`). 28 cached weapons state Burst Count / Burst Delay in prose, where the real rate is `burstCount / burstDelay` interpolated by DEX and reduced 33% by Berserk, not the flat Rate of Fire we use. The parameters are in the description text, not their own infobox rows, so this needs text parsing before it can be modelled.
    - **A rate-of-fire list can use commas, not just semicolons** (`parse_shot_groups`). Hunter's Longbow and Shard Launcher state `Rate of Fire: 92, 96, 100%`. We split projectile groups on `;` only, so these collapse onto one rate. Check whether the comma form always pairs with a comma-separated Damage row before splitting on it, since prose commas are everywhere.
    - **Effect(s) boosts that scale with a stat are stored as the flat number only.** The Triangle is `ATT Boost: +5 (+1 per 8 WIS over 75)`. We add +5. The extra ATT from Wisdom over 75 is not applied. Harmless on a 67 WIS Bard. Needs the same per-over-threshold parse the ability Damage row already has, resolved after the flat combat sheet exists.
    - **Whether a shot actually lands is not modelled.** Arc gap, true range, amplitude/wavy paths, and piercing all decide how much of a stated volley connects. Every number we give assumes every projectile hits, which is the right ceiling but overstates a wide-arc weapon at range. Worth a note in the brief before it is worth a model.
  - Attack Bard overlay stays Triangle + Vesture. Doom Bow may stay in a top 5; briefs must also name Clockwork Repeater.
3. **Azure Static Web App for** `web/`**, in Static (not Hybrid) mode**: no
  frontend hosting existed yet, only the API backend is deployed. Chose
   Azure Static Web Apps over Vercel (Sep 13, decided to stay fully on
   Azure for the portfolio story) and over a second Container App (simpler
   free tier + built-in GitHub CI vs. hand-rolling ingress/scaling for a
   second container). Almost went with Hybrid (SSR) mode to match the app's
   `output: "standalone"` config, but checking *why* a live server was
   needed at all turned up that it wasn't - `web/app/api/chat/route.ts` was
   a dead-code proxy nothing called (the frontend already streams chat
   straight from the browser to the Container App), deleted it and switched
   to `output: "export"` (Sep 13, see Done below), so this deploys as a
   plain static site now, not the still-preview-labeled Hybrid Next.js
   hosting. Once live: set its `NEXT_PUBLIC_API_URL`/`API_URL` to the
   Container App's Application URL, and update the API's `app_url` setting
   (`Settings.cors_allowed_origins`) to the Static Web App's URL so CORS
   isn't stuck on `localhost:3000`.
   **Done as of Sep 14 - see CHANGELOG.md** `[2026.09.13]`**.** Kept here (not
   deleted) per `doc-history.mdc` since this was the original plan text,
   not just a status update.
4. **Key Vault**: move the env vars pasted into the Container App (JWT
  secret, Stripe key, `DATABASE_URL`, `REDIS_URL`) into Key Vault
   references instead of plaintext. Priority 5 in the deploy guide.
5. **Production secrets review**: the deployed Container App's log stream
  shows `PII_HASH_SECRET is unset` and `MAGIC_LINK_SECRET is unset`
   warnings (Sep 13) - both are silently falling back to `JWT_SECRET`. Set
   both explicitly and rotate `JWT_SECRET` off its local-dev value before
   real launch.
6. **Stripe live mode**: test-mode Checkout, Customer Portal, and the production webhook (`/payments/webhook` on the Container App, signing secret set Sep 16) are wired. Before taking real cards: flip the Stripe Dashboard to Live, paste `sk_live_` into `.env` and the Container App, rerun `python -m api.scripts.ensure_stripe_price` for the live-mode price, turn the Customer Portal on in Live (separate per mode), and run `python -m api.scripts.sync_prod_stripe_webhook` so the live account gets its own endpoint + secret.
7. **Entra External ID**: MSAL sign-in built on `feature/entra-auth` (Sep 13), but hit a "failed fetch" error in manual testing. Deprioritized for now (not blocking launch, decided Sep 13), come back to it after Container Apps.
8. Launch on a direct `ANTHROPIC_API_KEY` (decided Sep 13); swap to Foundry once the Azure billing review clears, don't hold deployment on it.

**Shipped live Sep 14 (late evening):** PR #14 + PR #15 merged to `master`, API redeployed, Static Web App live at realmpal.com. Webapp is fairly usable for core chat, item lookup, shiny/divine set visualizer, and build asks. Remaining rough edges (quota/paywall UX, quest timer, prompt mixing on delayed replies) and data-quality tuning tracked above.

**Done as of Sep 14 (later same day) - see CHANGELOG.md** `[2026.09.14]`**.** Item 8 (`parse_query` history-inheritance fragility) fixed at the root with `_has_own_topic()`; a matching frontend duplicate of the "with A, B, C" set-extraction bug (`web/lib/loadoutShowcase.ts`) was found and fixed too; real items missing a RealmEye wiki page now negative-cache instead of re-paying a ~30s scrape timeout every lookup; server-side chat history sync shipped for signed-in accounts (fixes chats appearing to vanish after an incognito session ends); the sidebar IGN/pet now falls back to the JWT's IGN so it prefills on any device; and the "item name glued to trailing free text" bug (multiple regex patches, same day) got a durable root fix - `resolve_item_query_with_trim` validates against the real item catalog with trailing-word trimming instead of ever handing a raw, unresolved capture to a scrape attempt. Two more variants of the same "build request read as an item name" bug turned up live in production right after: "set for full dexterity huntress" (bare preposition left behind after stripping "set") and "attack huntress" (a bare stat+class pair, no preposition or "set"/"build" left to catch) both went to doomed wiki scrapes before being fixed with a preposition check and a stat/class-vocabulary check in `_shiny_divine_item_name`. Once that stopped 404ing, "show me full shiny divine attack huntress" surfaced a follow-on gap: the message fell through to the generic weapon/ability/armor/ring text brief instead of the shiny/divine item-circle loadout the wording actually asked for, since that visual only existed for explicitly-named sets. Added `wiki_scaling.top_build_items()` (single best item per gear slot for a class+stat, reusing the same ranking the text briefs already compute) and `item_aliases.is_stat_class_shiny_divine_query()`, wired into `retrieve_set_visualizer`/`route_slots`/`retrieve_build_knowledge`/`routers/chat.py` everywhere the named-set check already gated routing - see CHANGELOG.md `[2026.09.14]`.

## History

### Until Sep 18, 2026
Stored briefs vs visualizer used `wiki:build:v1:{class}:{stat}`. Ability specialist only kept infobox `Damage: (+N per STAT)` rows.

### Until Sep 17, 2026 (7:05 PM)
Item 2 DPS specialist still used Vulnerable 1.10, applied Damaging to abilities, and listed relative/percentage weapon enchants beyond `debug.weaponEnchant` as remaining.

### Until Sep 17, 2026 (6:50 PM)
Item 2 DPS specialist still said ability damage stays on the board row. Remaining listed per-ability formulas (minions, MP reduction).

### Until Sep 17, 2026 (6:40 PM)
Item 2 still said "Full DPS formula agent is still later. This overlay/store work is not that agent."

### Until Sep 16, 2026 (1:20 PM)
Item 2 ranking read: RealmShark first, then the player overlay, Umi in synergy, RealmEye class-page Maximum Achievable Stats last for every class+stat. Unique Dex/Vit Samurai and Kensei did not name Tools of the Tarnished + Fungal Breastplate. Heavy armor had no forced list.

### Until Sep 16, 2026 (1:15 PM)
Item 2 overlay bullets read: "**More player overlays** in the same shape as Attack Bard: class + stat + exact wiki titles for weapon / ability / armor / ring. Next worth writing down: Dex Bard, Attack Archer, and any combo where the wiki row is the wrong playstyle. **UmiEnjoyers**: in-depth turns now inject the general-tab BIS page as the alternative list for weapon, ability, armor, and ring. Still not used for set-visualizer majority picks. Attack Bard overlay stays Triangle + Vesture. Doom Bow may stay in a top 5; briefs must also name Clockwork Repeater. Attack robes: Diplomatic Robe and Vesture of Duality, Flowering Kimono honorable mention. Ring briefs always name Kagenohikari with Lean, Crown, and Gemstone." Family cores (katanas Enforcer / Valor / Tools of the Tarnished, staves Unholy Sacrifice, etc.) were not in the overlay yet.

### Until Sep 16, 2026 (12:45 PM)
- **UmiEnjoyers**: still not used for weapon/ability/ring visualizer picks.

### Until Sep 16, 2026 (10:40 AM)

UI NOTE  
Get the app while you wait to get a notification when your request is ready should pop up if the AI is thinking... for more than 3 seconds, shouldnt actually be a modal popup but it should be a container within the AI's response above the Thinking... (which its rotations with other phrases needs to slow down slightly as well).





Item 2 read: "**Build/loadout quality - no single source is the best build.** Sep 16: class wiki pages (`/wiki/bard`, same pattern for every class) have a **Maximum Achievable Stats** table that names items for the highest possible number on each stat. That table is useful as a candidate list, not as "the best build." Example from the [Bard wiki](https://www.realmeye.com/wiki/bard): Attack row is Wavecrest Concertina + Diplomatic Robe (a potential ATT stack). Actual best Attack Bard (player-confirmed) is Triangle + Vesture of Duality. Same grain of salt for [UmiEnjoyers BIS](https://umienjoyers.com/guides/best-in-slot/bard?tab=general) and RealmShark DPS boards. Recommendation rule: items that show up across RealmEye class-page max-stats, RealmEye hub stat ranks, Umi general BIS, and RealmShark are the top candidates; when they disagree, do not let the wiki max-stat row win by default.

- **Not scraped yet:** `/wiki/{class}` Maximum Achievable Stats. We scrape ability/armor/ring hubs and item infoboxes, not the class page table.
- **RealmShark**: some class+stat combos have no dedicated board (e.g. Attack Huntress falls back to Archer bow loadouts in text briefs). `top_build_items()` does not consult RealmShark at all yet - only hub `_top_stat_items`. Wire `load_top_loadouts()` / graph edges into slot picks where a board exists; document honest fallback when it does not (sister-class weapon family, not wrong ability slot).
- **UmiEnjoyers**: `retrieve_umi_bis()` is scraped and injected for enchantment specialist + armor context, but not for weapon/ability/ring picks or the set-visualizer derived path.
- **Stored briefs vs visualizer**: minted `wiki:build:v1:{class}:{stat}` text briefs and `top_build_items()` can diverge (different code paths). Goal: one ranking source per slot, reused by text reply, set visualizer, and Claude context.
- **Confirmed ranking (Sep 16, player):** RealmShark first (top 5 sets plus on-character enchants; most accurate of the three). Then this player overlay. Umi in synergy. RealmEye class-page Maximum Achievable Stats last. Even RealmShark can miss a ceiling: Doom Bow showing in a top 5 is fine, but the brief must also name its upgrade Clockwork Repeater. Skip Limited Edition items when they are a reskin of a real item. Attack robe classes: Diplomatic Robe and Vesture of Duality, Flowering Kimono as honorable mention.
- **Player overlay (started Sep 16):** `api/services/community_knowledge.py` + aliases in `COMMUNITY_ALIASES`. Attack Bard weapon/armor forced to The Triangle + Vesture of Duality. Nicknames: triangle, cbow (Coral Bow), lbow (Leaf Bow), dbow (Doom Bow), lean crown (Chrysalis of Eternity). `top_build_items` applies the overlay. Weapon briefs mention upgrades when the base item is listed. `retrieve_umi_bis()` prompt now matches the ranking above (no longer "RealmEye is the source of truth"). Every ring brief always names Kagenohikari with Chrysalis of Eternity, The Forgotten Crown, and The Twilight Gemstone (`TOP_RINGS`) - Kage is usually missing from all three scrapers unless a RealmShark top 5 happens to wear it.
- Tests: Attack Bard overlay beats hub Concertina/Diplomatic; Doom Bow brief names Clockwork Repeater; triangle/cbow/lbow/dbow resolve; Attack Huntress picks include a Huntress-scaling trap (not Archer quiver)."



### Until Sep 16, 2026

Item 2 read: "**Build/loadout quality - feed responses from UmiEnjoyers + RealmShark, not just RealmEye hub rankings.** Live Sep 14 post-PR #15: shiny/divine full-build asks now render as a set visualizer (`wiki_scaling.top_build_items()`), but the four picks still come from warmed RealmEye hub stat sorting only. Gaps seen in playtesting:

- **RealmShark**: some class+stat combos have no dedicated board (e.g. Attack Huntress falls back to Archer bow loadouts in text briefs). `top_build_items()` does not consult RealmShark at all yet - only hub `_top_stat_items`. Wire `load_top_loadouts()` / graph edges into slot picks where a board exists; document honest fallback when it does not (sister-class weapon family, not wrong ability slot).
- **UmiEnjoyers**: `retrieve_umi_bis()` already scraped and injected for enchantment specialist + armor context, but not for weapon/ability/ring picks or the set-visualizer derived path. Umi general-tab BIS is community-curated and often names the items players actually wear - good tie-breaker when RealmEye hub order and RealmShark disagree.
- **Stored briefs vs visualizer**: minted `wiki:build:v1:{class}:{stat}` text briefs and `top_build_items()` can diverge (different code paths). Goal: one ranking source per slot, reused by text reply, set visualizer, and Claude context.
- **Claude synthesis**: even with good chunks, replies sometimes drop item names from tables (empty Weapon/Ability columns) or merge prior-turn context. Tighten set-visualizer header / stored-reply path so `[item:...]` tokens are emitted directly without relying on Claude to copy a table.
- Tests: assert Attack Huntress set-visualizer picks include a Huntress-scaling trap (not Archer quiver), and that Umi/RealmShark signals change the pick when hub data alone would differ."



### Until Sep 14, 2026 (later same day)

Item 8 read: "**Not yet fixed -** `realmshark.parse_query`**'s history-based
class/stat inheritance is still fragile.** Found live Sep 14 (see
CHANGELOG.md `[2026.09.14]`, the "snake eye ring" enchant trace): when the
*current* message has no class/stat of its own, `parse_query` scans
backward through the entire conversation history and glues in the first
class/stat it finds, from however many turns back, regardless of topic.
Patched three symptoms of this around the edges (`stored_answers. _build_reply`/`maybe_mint_brief` now refuse on `is_enchant_query`; `chat.py`
and `realmshark.retrieve_build_knowledge`'s `enchant_only` gates now check
`class_name and stat` instead of the coarser `buildish` flag), but the root
inheritance function itself is unchanged and could still misfire for a
*different* unrelated message that isn't an enchant question (e.g. a plain
item-lookup follow-up that happens to contain a weak slot noun). Worth
reconsidering: only inherit from the immediately-preceding turn, not the
whole history, and/or require the current message to look like a genuine
thin follow-up ("what other rings", "any other options") rather than
inheriting whenever the current message merely lacks its own class/stat."

### Until Sep 14, 2026, 10:15 AM (this revision)

Resume order's top items were, in this order: (1) embeddings backend
unreachable in production (CRITICAL, silently breaking all RAG), (2) a
frontend bug causing doomed item scrapes (already fixed same day), (3) Azure
Static Web App status confirmation, (4) CPU/semaphore contention causing
slow pet/dungeon/skin lookups, (5) unconditional IGN profile scrape on every
message, (6) skin/outfit visualizer scraper bug, (7) the original Static Web
App plan text. Superseded because all of items 1-4 and 6 got fixed and
deployed in this same session (Sep 14 morning): the embeddings backend was
switched to Voyage AI and both Qdrant collections re-seeded end to end; what
was diagnosed as "dungeon-guide retrieval leans on the same embeddings path"
turned out to be **wrong** on closer inspection - `dungeon_guide.py` never
touches Qdrant at all, the actual bug was a narrower regex gap
(`_GUIDE_RE` not recognizing "how to **do** X" phrasing), fixed separately;
the skin/outfit visualizer's selector bug was root-caused via live DOM
inspection (`.chooser-table` has a permanent zero-height box) and fixed; the
Container App was bumped to 1.0 vCPU/2 GiB. Full technical detail for all of
these moved to `CHANGELOG.md` `[2026.09.14]` per `development-workflow.mdc`.
Item 5 (unconditional IGN scrape) is carried forward unchanged, still not
fixed, now item 1 in the current list above.

### Until Sep 14, 2026, 12:21 AM (earlier same day)

Resume order was, in this order: (1) Azure Static Web App for `web/` in
Static mode, (2) Key Vault, (3) Production secrets review, (4) Stripe live
mode, (5) Entra External ID, (6) Launch on `ANTHROPIC_API_KEY`. Superseded
because a live post-deploy smoke test the same night found the embeddings
backend was broken in production (item 1 above, the most severe finding of
the night - silently blind RAG on every chat reply), a real frontend bug
causing doomed scrapes (item 2, fixed same session), and confirmed the
Static Web App item was actually already done. Items 4-6 (CPU contention,
unconditional IGN scrape, skin visualizer bug) are newly-found detail
underneath the CPU-contention item that already existed in the Sep 13
CHANGELOG.md "Internal" section ("Diagnosed: live scrapes queue behind
specialist warming in production") but hadn't been copied into BACKLOG.md's
forward-looking resume list yet.

### Until Sep 13, 2026 (later same day, second revision)

Resume order was:

1. Container Apps Step 2 onward: registry created and the API image is built + pushed; Qdrant Cloud also done. Still need: the Azure Managed Redis instance (Priority 4 Step 1.7 in `docs/DEPLOYMENT_GUIDE.md`), then the Container Apps Environment + Container App itself (Step 2 onward, same doc).
2. Provision the real Postgres server: code side done; Azure resource itself not created yet. `docs/DEPLOYMENT_GUIDE.md` Priority 6, before or alongside item 1's Container App env vars since `DATABASE_URL` needs a real value before that container can boot clean.
3. Key Vault, Stripe live mode, Entra External ID, `ANTHROPIC_API_KEY` launch: unchanged, see current list above.

**Superseded because:** Redis, the real Postgres server, and the Container
App itself all got provisioned and deployed in this same session (Sep 13,
later) - including hitting and fixing a real startup crash
(`ANTHROPIC_API_KEY` missing from the Container App's env vars) and a real
code bug (`scan_iter` unclassified in `api/redis_namespace.py`, raised in
every namespaced deployment; see `CHANGELOG.md` [2026.09.13] for detail).
That surfaced there was no plan yet for where the Next.js frontend itself
would live, which became its own resume-order item ahead of Key Vault.

**Qdrant Cloud is provisioned and seeded** (Sep 13): free-tier cluster `realmpal`
created (AWS us-east-1). `QDRANT_URL`/`QDRANT_API_KEY` written into `.env`.
Seeded with `python -m api.scripts.seed_wiki` (39 hubs) and `seed_dps` (36
RealmShark builds). Verified the real runtime path against it directly
(`ensure_collection`, `get_collections`, `query_points` with a live vector
search all confirmed working), not just that the seed scripts exited clean.
Known low-priority gap: local `qdrant-client` (1.13.0) is several minor
versions behind the cloud server (1.19.1) - only breaks the single-collection
`get_collection()` detail call, which nothing in the app actually uses
(everything goes through `get_collections`/`query_points`/`upsert`, all
confirmed fine), so not blocking, but worth bumping the pinned version
eventually so a future code path doesn't hit the same pydantic parsing gap.

**Postgres migration is done at the code level** (Sep 13): decided to do this
now instead of the SQLite-on-a-mounted-volume workaround (see the target-
platform note above, which said "until billing lands" - billing landed
Sep 13). `api/services/db.py` is a new shared backend behind one interface:
SQLite when `DATABASE_URL` is unset (local dev/tests, unchanged), Postgres
(asyncpg) when it's set. `accounts.py`, `entitlements.py`, `uploads.py`,
`billing_prefs.py` all run on either backend with no per-backend branching
at their call sites - `?` placeholders get rewritten to `$1, $2, ...` for
Postgres under the hood. Verified against a real local Postgres container
(all 4 stores: create/verify/lookup, upsert/RETURNING, column migration,
BYTEA blob round-trip). All 353 existing backend tests still pass unchanged
against the SQLite default. The actual Azure resource still needs
provisioning, see resume order item 2 above.

`api/Dockerfile` **created and the API image built + pushed** (Sep 13): there
was no Dockerfile at all before this (docker-compose referenced one that
didn't exist). Built on `mcr.microsoft.com/playwright/python` so Chromium +
every OS-level dep the scraper needs ships in the image. Registry created as
`realmpalacr` in a fresh `rg-realmpal` resource group (not the old, broken-
Foundry `rg-certio`). Also found and fixed local disk at 0.43 GB free
(Docker's storage went read-only mid-build) - cleared Temp, pruned Docker's
build cache and two unrelated old images, back to a healthy ~12 GB free.

**Forge specialist is done** (RealmEye `/wiki/forge` store, intent routing, shiny-forging grounding, Sep 22). See `CHANGELOG.md` [2026.09.22] for detail.

**Enchantment specialist is done** (wiring + implied-stat inference + tests, Sep 13). See `CHANGELOG.md` [2026.09.13] for detail.

**Stripe checkout → webhook → entitlement audit is done** (Sep 13): found and fixed a real bug (guest checkout emails only in `customer_details.email` were silently dropped) and shipped a self-service Stripe Customer Portal link. See `CHANGELOG.md` [2026.09.13] for detail.

**Stripe test mode fully verified working end to end** (Sep 13): `STRIPE_SECRET_KEY` and `STRIPE_PRICE_ID` in `.env` had never actually been filled in, both were still the literal `.env.example` placeholder text (`sk_test_...` / `price_...`), which `stripe_configured` correctly refused to treat as real. Real test secret key pasted in by hand; `api/scripts/ensure_stripe_price.py` auto-created the "RealmPal Pro" $7/mo test-mode price and wrote `STRIPE_PRICE_ID`. Confirmed via a real Checkout (test card `4242 4242 4242 4242`) that entitlement activation and the Customer Portal button both work. **Still test mode only**, see item 4 above for what live mode needs.

**Production branch is set up** (Sep 13): `master` is production (protected: PR required, no force-push/delete, enforced for admins too), `dev` is the normal working branch with no protection. `master` was fast-forwarded to `dev`'s tip so it's not stale anymore. Promote a deploy by opening a PR `dev` → `master` and merging it, there's no more direct-push path.

**Azure infra provisioned and the API is fully live** (Sep 13): Azure Managed Redis (`realmpal-cache`), Azure Database for PostgreSQL Flexible Server (`realmpal-db`), and the Container Apps Environment + Container App (`realmpal-api`) all created in `rg-realmpal`, East US 2. Took 7 revisions to get clean: a missing `ANTHROPIC_API_KEY` (crashed on startup with a clear pydantic error), `scan_iter` not being classified in `api/redis_namespace.py` (a real code bug, raised in every namespaced deployment since local dev's default namespace is empty and never exercised this path until `DEPLOYMENT_NAMESPACE=prod` was actually set), then four straight `DATABASE_URL` connection-string issues in a row (password's `@` breaking DSN parsing, missing firewall rule for the Container App's outbound IP, missing `:5432/realmpal?sslmode=require` suffix, and the `realmpal` database itself never having been created). `/health` returns `200`, Postgres/Redis/Qdrant all connect clean, specialist warming is scraping RealmEye and populating stores in the background. See `CHANGELOG.md` [2026.09.13] for full technical detail on each bug.

`web/` **simplified to a pure static export before its first deploy** (Sep 13): found and deleted two dead-code server dependencies (`app/api/chat/route.ts` proxy, `/api/sprite` rewrite) that were the only reason `output: "standalone"` (hybrid hosting) looked necessary; the frontend already calls the Container App directly for everything, including chat streaming. Switched to `output: "export"`. See `CHANGELOG.md` [2026.09.13] for detail.

## History



### Until Sep 13, 2026 (later same day, fifth revision)

Resume order was: (1) Container Apps + Key Vault for the actual Azure
deploy, exact portal steps already in `docs/DEPLOYMENT_GUIDE.md` Priority
4/5; (2) Stripe live mode repeat-setup before real launch; (3) Entra
External ID MSAL sign-in, deprioritized after a "failed fetch" error in
manual testing; (4) launch on a direct `ANTHROPIC_API_KEY`, swap to
Foundry once the Azure billing review clears.

**Superseded because:** starting the actual Container Apps click-through
(Sep 13, later) surfaced two real gaps this resume order didn't account
for - no `Dockerfile` existed at all, and there was no plan for where
Redis/Qdrant/SQLite live once the API isn't running via docker-compose
anymore. Those turned into their own resume-order items above.

### Until Sep 13, 2026 (later same day, fourth revision)

Resume order was:

1. Entra External ID - MSAL sign-in built (Sep 13) on `feature/entra-auth` (branched off `master`, `dev` untouched). Next: manually test the real redirect round-trip with real `.env.local` values, build IGN collection for a first-time Entra sign-up, then merge.
2. Launch on a direct `ANTHROPIC_API_KEY` now (decided Sep 13); swap to Foundry once the Azure billing review clears, don't hold deployment on it.
3. Enable the Stripe Customer Portal in the Dashboard (Settings → Billing → Customer portal), one-time toggle, so the new "Manage subscription" button in `BillingModal.tsx` works outside test mocks.
4. Container Apps + Key Vault for the actual Azure deploy, once Entra sign-in is merged.



### Until Sep 13, 2026 (later same day, third revision)

Resume order was:

1. Entra External ID - portal setup done (Sep 13): tenant, both app registrations, user flow, `.env` values all in place. Next: MSAL SPA sign-in code + swap (or complement) local email+password with Entra tokens.
2. Foundry - blocked, see Blocked section below. Don't retry deployment until billing clears.
3. Enable the Stripe Customer Portal in the Dashboard (Settings → Billing → Customer portal), one-time toggle, so the new "Manage subscription" button in `BillingModal.tsx` works outside test mocks.
4. Container Apps + Key Vault for the actual Azure deploy, once Entra code integration lands.



### Until Sep 13, 2026 (later same day)

Resume order was:

1. Entra External ID - portal values collected (Sep 13). Next: MSAL SPA + swap local email+password for Entra tokens.
2. Foundry - blocked, see Blocked section below. Don't retry deployment until billing clears.
3. Audit the Stripe checkout → webhook → entitlement flow end to end (no known bug, just unverified since Link was added).

---



## Blocked



### Azure Foundry - code done, blocked on Azure billing account review

Chat client is finished in `api/services/llm.py` and doesn't need more work. `_stream_response` picks Foundry when `FOUNDRY_RESOURCE`/`FOUNDRY_BASE_URL` is set (endpoint allowlisted to `https://<resource>.services.ai.azure.com/anthropic`, Entra or a Foundry key, never both), otherwise falls back to `ANTHROPIC_API_KEY`. CCU-aware spend logging, `/health` reporting `provider`, startup warnings on a raw key in prod - all in.

**Deployment fails in the portal**: both `claude-sonnet-4-6` and `claude-sonnet-4-5` deployments show `Provisioning state: Failed`, with "This purchase cannot be completed" from Azure Marketplace. Root cause found: **the Azure billing account is "Under Review" / inactive** - Cost Management + Billing → Billing scopes → that account shows "Your account is under review... buying new products and services... will be restricted until the review is complete." Marketplace can't fulfill any paid model purchase while that's true. This is Microsoft-side, not a RealmPal config problem - resource providers, region (confirm East US 2 / Sweden Central), and subscription type are all fine; the account itself is locked.

Do not keep retrying deployments - each attempt just fails the same way. Resume when:

1. Billing account review clears (check Cost Management + Billing → Billing scopes → account status), or
2. Support resolves it directly.

Then: subscribe the `claude-sonnet-4-6-ccu-plan` Marketplace offer (not `-plan-new`), deploy, paste resource name into `.env`, confirm one live stream logs `provider=foundry` and a `cost_ccu` value.

---



## Next Up



### Entra External ID - portal done, MSAL sign-in built on a side branch, not merged yet

**Portal (done Sep 13):** External tenant `RealmPal`, apps `RealmPal API` + `RealmPal Web` (SPA, single-tenant), user flow email+password collecting email only. Values in `.env`: tenant ID, SPA client ID, API client ID, `AUTH_JWKS_URL`, `AUTH_ISSUER`, `AUTH_AUDIENCE`, `ENTRA_USER_FLOW`. Backend `api/identity.py` already verifies JWKS tokens when `auth_configured` is true, and already tried first (before the local session JWT) in `api/dependencies.py`'s `get_optional_user` - no backend changes were needed for any of this.

**Built on** `feature/entra-auth` **(branched off** `master`**, Sep 13), not merged into** `dev` **or** `master` **yet:**

1. `web/lib/msal.ts`: MSAL (PKCE) `PublicClientApplication` against the SPA client + `ciamlogin.com` authority + user flow. Lazy singleton, only touches `window` client-side, no-ops if `NEXT_PUBLIC_ENTRA_*` env vars are unset
2. `web/app/auth/callback/page.tsx`: handles the redirect back from Entra, stores the Entra access token under the same `AUTH_TOKEN_KEY` the local session JWT uses (so every existing `authHeaders()` call site needs zero changes)
3. `web/app/auth/signin/page.tsx`: "Continue with Microsoft" now triggers a real `loginRedirect()` when Entra is configured, instead of always hitting the old 501 stub. Google is untouched (deferred, silent-renewal bug)
4. `AccountMenu.tsx`: sign-out also clears the MSAL session, but only if MSAL actually has a cached account (a local email+password user signing out never touches Entra at all)
5. `web/.env.local.example`: documents the `NEXT_PUBLIC_ENTRA_*` values needed (same non-secret IDs already in the root `.env`, just re-exposed for the browser bundle)

**Still to build before merging:**

1. **Manual test against the real tenant**: fill in `web/.env.local` with the real (non-secret) tenant ID / SPA client ID / API scope, run `npm run dev`, click "Continue with Microsoft", confirm the redirect round-trip and that `/chat` calls succeed with the Entra token
2. **IGN collection after first Entra sign-up**: the user flow only collects email, so a brand-new Entra account has no IGN and `decodeAuthIgn()` correctly returns `null` for it (no crash), but there's no UI yet prompting for one and no backend endpoint to attach it to that Entra `sub`. Local email+password's `registerAccount` collects IGN inline; Entra's hosted page can't, so this needs its own small flow post-redirect
3. Defer Google (silent-renewal bug); add later if wanted

**Findings kept:**

- Two app registrations (API + SPA), not one
- Authority: `ciamlogin.com` (not `login.microsoftonline.com`) for CIAM
- No SPA client secret (public client + PKCE)
- `@azure/msal-browser` 5.21.0's `CacheOptions` no longer has `storeAuthStateInCookie` (that was an IE11-era option); only `cacheLocation` and `cacheRetentionDays` remain



#### History



##### Until Sep 13, 2026 - Entra External ID

Researched, not yet built. User will provide portal values (tenant ID, client IDs, JWKS URL). Sign-in methods: **Google + email OTP** (known Google bug; decision to make: keep Google and force `prompt=select_account`, or use email OTP only).

What's needed from you: portal setup in `docs/DEPLOYMENT_GUIDE.md`, copy 7 values into `.env`, code integration once values are in place.

Backend prepared: `api/identity.py` verifies JWKS-signed tokens. Frontend holds session in httpOnly cookies and forwards Bearer token.

Findings: two app registrations; `ciamlogin.com` authority; Google silent-renewal bug 12-24h after first sign-in.

Portal values to collect: tenant ID, SPA client ID, API client ID / Application ID URI, JWKS URL, issuer, audience.

---



## Done (Sep 13, 2026) - See CHANGELOG.md for Technical Details

The following were completed and archived:

**Enchantment specialist** - LangGraph slot next to weapon/ability/armor/ring. Reads RealmEye `/wiki/enchanting` tables + Umi BIS notes. Infers the implied stat from an item's own base stat (or a class's dominant scaling stat for stat-less full builds) when the user doesn't name one.

**Stored answers** - Redis caching of drops, builds, dungeon guides, shiny items. Specialist warming system. 70/30 stored/Claude as success metric.

**Daily quests** - Rotating dungeon/player/shiny item, persistent per-user, grant +1 message/day via `POST /chat/quests/claim`.

**Pay-as-you-go billing** - 68 included Claude/mo (~$2.50), $0.08 overage, user spend cap, Stripe Link payment method.

**Stripe audit + Customer Portal** - Full checkout → webhook → entitlement review. Fixed a real bug: guest-checkout emails only present in `customer_details.email` were silently dropped, no entitlement created. Added self-service "Manage subscription or cancel" via `stripe.billing_portal.Session` (`POST /payments/portal`), gated on enabling the Portal once in the Stripe Dashboard.

**Email+password auth** - Local SQLite (PBKDF2-SHA256), fallback to magic-link. Primary sign-in method until Entra.

**Account-scoped history** - Chats & quests keyed per email, separate from guest sessions. LocalStorage persistence.

**Card zoom** - Sprites & full cards clickable → centered modal with RealmEye link.

**Top pet detection** - Highest RealmEye ability sum, not first slot.

**Sidebar improvements** - Collapsible quick-suggestion prompts, daily quests progress bar.

**Lookup rate limiting** - 12/min anon, 40/min signed-in on `/players`, `/items`, `/dungeons`, `/skins/render`, `/sprite`.

**Magic-link hardening** - Separate `MAGIC_LINK_SECRET`, single-use via Redis `SET NX`, no link logging.

**CORS hardening** - Only `app_url` unless `DEBUG=true`.

**What's new changelog** - User-facing UI with first-load popup, wired to settings page.

**Multi-tenancy foundation** - `DEPLOYMENT_NAMESPACE` for Redis & Qdrant scoping; entitlements SQLite store; subscription lookup on every JWT; fails open for unknown emails.

**Security hardening** - Server-issued JWTs, real entitlement checks, lookup rate limits, input sanitization, CORS/CSURF, cost budgets.

See `CHANGELOG.md` [2026.09.13] for commits, migrations, tests, and technical detail.

---



## Future (Planned, Lower Priority)



### DPS specialist (in progress)

Weapon and ability halves are in CHANGELOG.md `[2026.09.17]`. RealmShark boards are source of truth. Still open:

- Minion extra volleys beyond the ability residual (wiki lists summon lifetime, not fire interval)
- MP Cost Reduction re-simulating ability-use count (currently copies `debug.effectiveAbilityCount`)
- Live combat vs the 0 DEF / full-buff dummy (wiki Exposed is -20 DEF, min hit 10%)
- Incoming damage with enemy DEF (not potential DPS)
- **Set-conditional procs are not read, so a real Berserk source can be missed.** `api/scripts/audit_item_parsing.py` still reports 106 items with a trigger phrase we do not parse and 53 with an unparsed status word. The largest group is companion-item wording: Winter Boots and Gjallarhorn both say "With Blood Axe: Berserk for 5 seconds on ability use", which is a genuine Berserk source for `set_grants_berserk` and we return nothing for it. The rest are effects phrased inside `Effect(s)` rather than `Reactive Proc` (Ship's Wheel Shield's "Damage Reduction: On ability use ...") and statuses we do not model (Energized, Armored, Inspired). Needs a companion-item condition (only fire when the named piece is in the same set) plus `Effect(s)` trigger parsing. Re-run the audit after.
- **Stat-granting enchants may not reach the stat sheet, and adding them risks double counting.** Enchants are already applied for rate of fire and weapon damage (`weapon_enchant_multipliers`), for ability stat mod (`stat_mod_multiplier`), and as a Berserk source (`set_grants_berserk` reads enchant text). What is not verified is a plain `+N ATT` style enchant reaching `combat_stat_sheet`: `inspect_worn_set` only lifts enchant text into status grants and triggered procs, so an untriggered stat enchant is not in either delta bucket. Do not just add it. A RealmShark row's `stats` already has on-character enchants applied (so adding again would double count), and it is unconfirmed whether a scraped RealmEye sheet does. Establish which sheets already include them first, then apply only to the ones that do not.
- **Pattern B firing-mode semantics are inferred, not confirmed.** A weapon whose `Rate of Fire` row is a list is now summed per projectile group, each at its own rate (see CHANGELOG `[2026.09.17]`). That is clearly better than collapsing them onto one rate, and it puts Makakoyumi above Warmonger as expected, but it assumes all groups fire concurrently for the whole window. If a weapon actually alternates modes, or the second group is a summon with its own lifetime (Makakoyumi has a `Summon Effect(s)` row), the sum overstates it. 36 cached weapons are affected. Worth checking a Pattern B weapon against a RealmShark row that uses one.
- **A residual ~9% sits on each half, and the two halves lean opposite ways.** With the Sep 17 buff-model corrections in (CHANGELOG `[2026.09.17]`), `api/scripts/calibrate_dps_buffs.py` reports, on its PRODUCTION row (the real reconstructors over 133 cached rows), a median **+9.3% weapon**, **-8.4% ability**, **+10.3% total**. Board rows read RealmShark's own buff flags out of `row.debug`, so this residual is not the Berserk sourcing; the player-set path, which has no `debug`, is the one relying on `set_grants_berserk`. The two known unmodeled levers are ability-use count (we copy `debug.effectiveAbilityCount` rather than re-simulating MP) and the minion/tick volleys above. Do not "fix" this by re-tuning a multiplier: the multipliers are now pinned by 133 rows, and the earlier unconditional Berserk was exactly such a fudge, hiding a -11.8% weapon bias behind a +25% APS.
- **Unresolved: whether RealmShark feeds on-ability stat procs into ability damage scaling.** Turbine's Bard is the case that exposes it. His RealmEye sheet is ATT 76; The Triangle's on-use `ATT Boost +5` and Vesture's on-ability `ATT Boost +15` take it to 96, and his ability (`Damage: 300-450 (+25 per ATT over 55)`) is one of the few that scale off Attack rather than Wisdom, so the choice swings that half by +55% (900 vs 1,400 per shot). Including the procs puts the set at 23,980.5 vs RealmShark's 21,381.1 (+12.2%); excluding them lands 17,235 (-19.4%); including them for the weapon multiplier but not the ability scaling gives 18,805 (-12%). None match, so at least one other factor is in play for this row. The board rows cannot arbitrate because nearly all of them scale off Wisdom, which the procs do not touch (measured: including procs moves the board ability half by 0.0% and the weapon half only +8.9% to +10.0%). Needs either a RealmShark row for an Attack-scaling ability whose gear has on-ability ATT procs, or a direct answer on the convention.
- **Summon/tick abilities have no reconstructable wiki `Damage` row.** Genesis Spell is "Summons 4 portals which zap enemies and deal 350 damage in a radius of 6 squares every 0.4 seconds", so `parse_ability_formula` finds nothing and a player-set reconstruct reports `weapon-only DPS` with the ability named as excluded (honest, but not the ceiling). A full number needs a tick model: summon count x tick damage x ticks over the duration, capped by the 5s window. Same shape as the minion item above. Verify with `api/scripts/probe_player_dps.py Turbine wizard`.
- **The English-word guard in `fuzzy_closed_vocab` is a hand-maintained list.** `_ENGLISH_FILLER` stops "like" being typo-corrected into the HP alias "life" (see CHANGELOG `[2026.09.17]`), but it only covers the common words we thought of. The principled version is a frequency dictionary or a "is this a real English word" check, so any ordinary word is refused without us enumerating it. Low priority: exact aliases are matched before the guard, so the failure mode is a missed typo correction, not a wrong stat.
- **A DPS follow-up chain breaks if an unrelated turn interrupts it.** `is_dps_follow_up` walks history backwards and stops at the first turn with its own topic, so "what's the DPS for X" then a Shatters question then "explain that" is deliberately not a DPS turn. That is the safe default, but it also means a genuine return to the DPS topic after a detour needs the user to re-name the subject. Revisit if it comes up in real conversations; the fix would be tracking the active subject per session instead of re-deriving it from message text.

Until Sep 17, 2026 (8:00 PM) this section did not list summon/tick abilities. An ability with no `Damage` row silently contributed 0 and the total was still labeled "potential DPS".

Until Sep 17, 2026 resume-order item 2 still treated RealmShark boards as the only DPS source. A player's class DPS ask did not scrape that IGN or reconstruct from the worn set.

Until Sep 17, 2026 resume-order item 2 still said armor/ring swaps apply On Equip plus On Ability procs, and named Warmonger for On Shoot, without walking every worn wiki page for status grants.

Until Sep 17, 2026 (7:05 PM) this section still listed relative/percentage enchants beyond `debug.weaponEnchant` as open. Vulnerable was 1.10.

Until Sep 17, 2026 (6:40 PM) this section read: Wiki formula + RealmShark loadouts as reference. Files exist; same wiring pattern the Enchantment specialist used (warm store, build-knowledge injection, chat RAG skip, tests).

### Per-user Qdrant filtering

Add `user_email` metadata when per-user documents arrive. Currently Qdrant holds only public scraped data.

### Container Apps + Key Vault deployment

See `docs/DEPLOYMENT_GUIDE.md` for exact Azure portal steps.

### PostgreSQL migration

After Foundry + Entra. Replace SQLite.

### Flutter mobile app (iOS + Android)

Lower priority, not blocking.

### Guild page lookups

Lower priority.

### Real email provider for magic-link (Resend)

Magic-link is fallback only; email+password is primary. Can defer.

### Sidebar polish

Section titles (Your IGN, Chats, Suggested), slightly larger font, lighter text.

### Live scrapes queue behind specialist warming (single Chromium semaphore)

Found Sep 13 in production: a player/pet lookup took 43s because it queued
behind a chain of specialist-warming scrapes (UmiEnjoyers BIS for all 19
classes, hub pages, etc.) via `api/services/scraper.py`'s
`_PW_SEM = asyncio.Semaphore(1)`. That's not an arbitrary limit, the
comment above it says parallel Chromium launches crash the driver (almost
certainly a `/dev/shm` constraint with more than one Chromium process in
one container), so just bumping the semaphore's count is not a safe
one-line fix, it needs real testing (e.g. `--disable-dev-shm-usage`,
larger container memory, or genuinely separate low-weight browser
contexts) before trusting it in production.

Compounding factor tonight specifically: ~8 container redeploys in a row
each restart the process, killing specialist warming's in-progress task
before its multi-minute queue finishes, so it resumes from scratch each
time rather than ever completing cleanly. Should settle down once
redeploys stop for the night (wiki data has a 7-day TTL once fully warmed).

Real fix, for whenever there's time to test it properly: give live/
interactive scrape requests priority over background warming for the
semaphore (e.g. a small queue that lets an interactive request cut ahead
of a pending warming scrape, or pause warming entirely while a live
request is waiting), so a user-facing lookup never queues behind a bulk
wiki refresh.

Related, smaller fix already shipped same night: `web/lib/api.ts`'s
`postAuth` (sign-in/register) had no client-side timeout, so if the
backend queued for minutes behind that same lock, the UI just spun
forever instead of showing an error. Added a 20s `AbortController` timeout
with a clear retryable message. Same gap found and fixed in
`fetchPlayer`/`fetchDungeon`/`fetchItem` (45s allowance, scrape-backed so
slower than auth) via a shared `fetchWithTimeout` helper.

**Confirmed same night, not yet applied**: `/health` (pure static JSON,
zero I/O) took 37s to respond while warming was mid-run. Ruled out a
Python-side blocking bug in the scraper (retries use `asyncio.sleep`, page
extraction runs as JS via `page.evaluate()`, not synchronous Python
parsing). Real cause is almost certainly the Container App's CPU
allocation, `rg-realmpal` → `realmpal-api` is on 0.5 vCPU / 1 GiB
(Azure's small default), too little to run headless Chromium and
FastAPI's event loop at once without one starving the other. Next action:
bump to 1.0 vCPU / 2 GiB via Containers → Edit and deploy (roughly doubles
compute cost while the replica is running, a few dollars/month at this
traffic level). Also consider bumping min replicas to 2 at the same time
so warming and live traffic aren't sharing the only replica, holding off
on that until CPU/memory alone is tested first.

### Pre-existing ESLint errors (`react-hooks/set-state-in-effect`)

Found Sep 13 while checking `web/`'s build for the Static Web Apps deploy, not caused by that session's changes (confirmed via `git diff --stat`). Not a build blocker (`next build` doesn't gate on ESLint in this Next.js version), but should get fixed: `components/chat/SpriteZoom.tsx` (2 instances), `components/chat/SkinPortrait.tsx`, `components/chat/PlayerCard.tsx`, `components/player/PlayerCard.tsx`. Each is a `setState` call directly in a `useEffect` body instead of a callback/derived-state pattern.

---



## Documentation & Rules

**Changelog structure:**

- `CHANGELOG.md` - Developer changelog (technical, breaking changes, migrations)
- `web/lib/changelog.ts` - User-facing changelog (app UI only)
- `.cursor/rules/changelog.mdc` - Enforce user-facing entries on every deploy
- `.cursor/rules/development-workflow.mdc` - NEW: Separates BACKLOG (forward), CHANGELOG (completed), UI changelog

**Doc history:**

- `.cursor/rules/doc-history.mdc` - Keep dated prior text when updating BACKLOG, CHANGELOG, README, or docs/

**Project structure:**

- `BACKLOG.md`, `README.md` at root (high-level, visible)
- All other docs in `docs/` folder
- `docs/pricing.md` and `docs/business.md` gitignored (business logic)

**Related references:**

- `docs/DEPLOYMENT_GUIDE.md` - Exact Azure portal steps
- `docs/DEPLOYMENT_QUICK_REFERENCE.md` - Commands & timeline
- `docs/DEPLOYMENT_ARCHITECTURE.md` - Infrastructure diagrams
- `docs/chat-quality-benchmarks.md` - Traces & stored-answer map
- `docs/pricing.md` (gitignored) - Unit-econ, hosting costs, break-even
- `docs/README.md` - Doc structure & audience guide

---



## Historical Notes

**Last session decisions:**

- Chat sidebar ordering: Don't re-order on view; only move to top when message count increases
- Cost model: $7/mo + PAYG at $0.08/reply; included pool 68 (~$2.50), daily fuse 50 msgs
- Free tier: Guest 3/24h, signed-in 5/24h (metered, not token-based)
- Stored answers: 70/30 stored/Claude success metric, not a hard quota
- Stripe: Use Link payment method (saved cards)
- Auth: Email+password now, Entra + Google + email OTP later
- Deploy: Azure Container Apps + Key Vault + Postgres (after Foundry)

**Known issues:**

- Google SSO silent renewal bug in Entra (12-24h after first sign-in). Decision pending.
- Infrastructure lockdown pending (Redis/Qdrant credentials, docker-compose → Container Apps)
- Prompt-injection defense weak (regex denylist; should be stronger)
- Entra MSAL sign-in on `feature/entra-auth` (Sep 13) throws a "failed to fetch" error on the redirect callback when manually tested; not diagnosed yet, deprioritized behind Container Apps. Likely candidates whenever this gets picked back up: `knownAuthorities` mismatch, the JWKS/token endpoint not actually reachable at the `ciamlogin.com` path MSAL is calling, or a redirect URI that doesn't exactly match what's registered on the SPA app

---



## Running Locally

```bash
pip install -r api/requirements-dev.txt
npm install --prefix web

# Terminal 1: API
cd api && python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2: Web
cd web && npm run dev

# Tests
pytest api/tests/ -v

# Warm specialist stores
python -m api.scripts.warm_specialists --status
python -m api.scripts.refresh_wiki
```

API: `http://localhost:8001`, Web: `http://localhost:3000`