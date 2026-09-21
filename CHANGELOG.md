# Changelog

All notable changes to RealmPal are documented here. This is the **developer changelog** (technical details, internal changes, breaking changes, migrations). 

**Related files:**
- **User-facing changelog:** `web/lib/changelog.ts` — rendered in the app UI ("What's new" modal, first-load popup, settings page)
- **Product decisions:** `BACKLOG.md` — high-level roadmap, current priorities, research notes
- **Deployment guide:** `docs/DEPLOYMENT_GUIDE.md` — exact Azure portal steps

Format: each version has technical notes, linked commits, migration guides (if needed), and internal changes not exposed to users.

---

## [2026.09.21-4] - Sep 21, 2026

### Fixed
- **Dungeon portal droppers come from the RealmEye lead** (`extract_portal_source_query`, `parse_portal_droppers`, `_portal_drop_reply`). Found live: "What enemy does ocean trench drop from" listed Thessal loot, and the follow-up "which enemies found in realm can drop ocean trench" said the store had no portal sources. "What enemy drops X" / "what enemy does X drop from" / "enemies in the realm can drop X" now read the dungeon page lead (`The portal to Ocean Trench has a chance to drop from Abyssal Squid, Sea Dragon and Ice Giant. It is also guaranteed to drop from Hermit God and Eye of the Storm`). Loot-inside stays on "what enemies in X drop" / "what does X drop". `where does ocean trench drop from` uses the dungeon index before treating the name as an item. Retrieve injects that lead so a Claude follow-up does not only see dungeon loot.

### Tests
- `test_extract_portal_source_query_live_phrasings`
- `test_parse_portal_droppers_ocean_trench_lead`
- `test_ocean_trench_portal_drops_from_realm_enemies`

---

## [2026.09.21-3] - Sep 21, 2026

### Fixed
- **Hub new-item retrieve no longer cites last season's dated cards** (`ensure_motmg_post`, `_scan_cards`, `_score_post`, `retrieve_rotmg_hub`). Found live after 2026.09.21-2: the Hub index already had Season 29 Part 2: Alien Overdrive and Season 28 Part 2: The Return of Stromwell, so `seed_motmg_if_empty` skipped the living MOTMG URL (Season 30 Part 2). Scoring then returned those two titles, which never mention Rectangular Prism / Cube Deity. Retrieve now always upserts MOTMG, scans MOTMG plus the latest 5 cards, scores +200 only when the asked token is in items/event whites, and on a new-item miss uses MOTMG alone rather than dumping unrelated season notes.
- **Wiki awakened enchant lives in its own table** (`parse_awakened_from_wiki_html`, `_ITEM_PAGE_JS`, `GET /items` `_with_wearable`). Found live: Snake Eye Ring infobox is Tier / On Equip; Awakened Enchantment is a later table (`th` + sprite `td` + effects `td`). Playwright copies the last cell; cached profiles with On Equip but no awakened row HTTP-backfill once (miss key `wiki:awakened-miss:v1:{name}`) and persist. Loadout hover reads any stats key matching `/awakened/i`.

### Tests
- `test_new_prism_uses_motmg_not_old_season_cards`
- `test_ensure_motmg_fetches_when_index_is_older_seasons`
- `test_parse_awakened_from_wiki_html_snake_eye`
- `test_get_item_backfills_awakened_from_wiki_table`

---

## [2026.09.21-2] - Sep 21, 2026

### Fixed
- **New-item asks read official Hub notes before RealmEye** (`extract_hub_query`, `_drop_reply`, `retrieve_build_knowledge`, `api/routers/chat.py`). "Where does the new prism drop?" still hit the RealmEye Prisms ability hub: `prism` is a Trickster class alias, Hub-only routing skipped wiki when the store was empty, and `_drop_reply` preferred a wiki page with no loot. Slot-noun class aliases are skipped on drop / new-item turns. Hub is tried first (with an HTTP MOTMG seed if the Playwright index is empty). A Hub miss falls through to RealmEye. Inherited IGN from an earlier lookup no longer steals the Hub path.
- **Shiny/divine loadout hover shows On Equip plus the awakened enchant** (`awakened_enchant_for_item`, `GET /items`, `LoadoutRow`). RealmEye's Awakened table lists Draconic Gaze with label tokens, not "Snake Eye Ring", so hover never attached. Wiki infobox `Awakened Enchantment` is now the source of truth, and the tooltip includes On Equip the same way the set preview does. A second `fetchItem` for the same slot merges those fields instead of keeping the first empty card.

### Tests
- `test_new_prism_drop_is_not_a_trickster_build`
- `test_new_prism_drop_prefers_hub_over_wiki_prisms`
- `test_new_item_hub_miss_returns_empty_so_wiki_can_run`
- `test_snake_eye_awakened_comes_from_wiki_infobox_when_rolls_omit_the_item`
- `test_get_item_attaches_awakened_from_wiki_infobox`

---

## [2026.09.21] - Sep 21, 2026

### Added
- **Official RotMG Hub patch notes (fourth knowledge pillar)** (`api/services/rotmg_hub.py`, `api/services/scraper.py`): Playwright scrapes the Updates index at `hub.realmofthemadgod.com/news0/updates0` (Load More pagination); httpx fetches SSR article bodies. Redis keys `rotmg-hub:index:v1`, `rotmg-hub:post:v1:{slug}`, `rotmg-hub:sprites:v1`, `rotmg-hub:names:v1` with 24h TTL. `retrieve_rotmg_hub` injects official patch context; `matching_hub_excerpt` appends on builds/dungeons that name new-season items. Hub patch notes are patch truth for what shipped; RealmShark / Umi / RealmEye still rank BIS. `GET /sprite` and `GET /items` fall back to Aghanim CDN art when RealmEye has no page yet. Wired into `specialist_warm`, `retrieve_build_knowledge`, `build_system_prompt`, `store_ranking_brief`, chat RAG skip, and suggest index. Found live Sep 21: "Where does the new prism drop?" missed Hub because routing only matched MOTMG/patch keywords; `extract_hub_query` now matches new-item drop asks and event-white rows keep `from` sources (Rectangular Prism from the Cube Deity).
- **Shiny/divine + awakened visualize** (`is_enchant_query`, `_shiny_divine_item_name`): "Shiny divine awakened snake eye ring" was stolen as an enchant-only turn (no `[loadout]` chunk). `awakened` as an adjective on a shiny/divine show-me is a visualizer flag; strip it from the item name. Real enchant asks that name `enchantment`/`rolls` still route to the specialist.
- **Uploaded sprite rarity frames** (`web/lib/uploadedSprites.ts`, `inferUploadedSpriteShowcase`): an attached PNG (fan-made shiny, custom item art) plus "make this shiny divine" / "make this legendary" / Unc, Rare, Leg, Div overlays the same `slots.png` diamond frame, glow, and shiny star the set visualizer uses. Follow-ups reuse the last framed upload and keep shiny when only the tier changes. Local reply, no Claude turn.

### Fixed
- **Chat prompt hardening** (`api/models/chat.py`, `api/routers/chat.py`, `api/services/validation.py`, `api/services/rag.py`): `ChatMessage.role` is `Literal["user", "assistant"]` only (422 on `system`/`tool`). Sidebar IGN is sanitized to `[A-Za-z0-9_]{1,20}` before it reaches the system prompt; junk is omitted, not a 400. IGN is wrapped as untrusted data in `<ign>` tags. System prompt refuses instructions from user text, history, IGN, images, or `<context>`. PDF attachments are rejected; images only.
- **Rate limits fail closed** (`api/routers/chat.py`, `api/dependencies.py`): chat burst, daily quota, paid ceiling, and lookup window counters return 503 when Redis errors instead of allowing unbounded Claude or Playwright use.
- **Same-set visualizer** (`_set_visualize_reply`, `character_equipment_names`): "same set but all divine" after a player's class card copies that character's weapon/ability/armor/ring. Named comma lists (no `with`) emit `[loadout]` plus `[item:]` tokens from the store so the four slots are not empty. Awakened unique lines attach on `GET /items` for loadout hover.
- **Enemy loot store** (`extract_drop_source_query`, `group_drops_by_enemy`): "what enemy drops ocean trench" no longer treats the word enemy as the source. Dungeon loot is grouped by `drops_from` (Hardmode Shatters boss sections).

### Tests
- `test_parse_rarity_picks_the_highest_tier`: `unc` / `leg` / `div` aliases
- `test_chat_message_rejects_system_role`, `test_claude_history_only_allows_user_and_assistant`: history role Literal
- `test_sanitize_ign_strips_injection`, `test_system_prompt_omits_raw_injection_ign`, `test_system_prompt_treats_user_content_as_untrusted`: IGN and untrusted-data prompt block
- `test_pdf_attachment_is_rejected`: images only
- `test_chat_burst_redis_failure_is_503`, `test_lookup_rate_limit_redis_failure_is_503`: Redis down is 503
- `test_same_set_followup_reuses_character_equipment`, `test_named_comma_set_is_a_stored_loadout`, `test_dungeon_loot_is_grouped_by_enemy`, `test_awakened_enchant_for_item_is_named_in_the_hover_line`
- `test_parse_index_cards`, `test_parse_article_html_extracts_sections_and_sprites`, `test_extract_hub_query`, `test_retrieve_rotmg_hub_cache_only`, `test_matching_hub_excerpt_exact_new_item_only`, `test_hub_sprite_map_lookup`, `test_system_prompt_mentions_hub_patch_truth`, `test_missing_work_includes_empty_rotmg_hub`, `test_new_prism_drop_uses_hub_event_white`, `test_shiny_divine_awakened_ring_never_hits_the_llm`

---

## [2026.09.18] - Sep 18, 2026

### Added
- **DPS specialist ships to production.** Player-set reconstruct, guild-hall dummy, four-slot breakdown, on-character enchant channels, and the named-class character card are the live path for class ceilings and `IGN's {class}` asks.

### Fixed
- **8/8-stat enchants were treated as fire rate** (`classify_enchant`, `weapon_enchant_multipliers`, `format_enchant_channel`, `format_slot_contributions`). A live Bard breakdown blamed `Vitality -Speed Tradeoff III` for APS 8.87 vs an invented `DEX × RoF / 8 = 10.2`. That enchant (and every other 8/8 pair: ATT/DEF, DEX/SPD, WIS/HP, Life/Mana, ...) is a sheet-stat channel: already inside the RealmEye totals, never a RoF multiplier. Fire Rate Tradeoff / Damage Tradeoff / Flurry stay `weapon_shot`. Projectile Speed is `projectile_travel`. APS is `(1.5 + 6.5 × DEX/75) × item Rate of Fire`. A sheet-stat still counts when Attack, Dexterity, or the ability's wiki scaling stat is that sheet value, so a Speed-scaling ability is not starved of Speed. Breakdowns must walk weapon, ability, armor, and ring from `HOW EACH WORN PIECE`. Found live: Turbine's Bard.
- **Board-row brief still taught the old APS shorthand and "Damaging is weapons-only"** (`format_reconstruction`). A live Archer breakdown copied `APS(DEX × Rate of Fire)` into the heading while the step-by-step used the real formula, and said Damaging was weapon-only while the ability half already included it. The board reconstruct copy now matches `format_dps_derivation`. Found live: Turbine's Archer.
- **Signed-in chat sync 500ed on Postgres INTEGER** (`api/services/db.py` `postgres_ddl`, `widen_existing_integers`). The browser sends `Date.now()` milliseconds (`1789716549690`) as `updated_at`. SQLite INTEGER is 64-bit so local tests passed; Postgres INTEGER is int32. `POST /chat/sessions/sync` and `PUT /chat/sessions/{id}` raised `asyncpg.exceptions.DataError: value out of int32 range`. All SQLite INTEGER DDL is now BIGINT on Postgres, and existing int32 columns are ALTERed on startup. Found live: revision `realmpal-api--0000052`.
- **DPS follow-up picked Haiku** (`pick_chat_model`). `is_dps_query` already takes history, but the model picker did not pass it, so "Break it down" after a Bard DPS turn was treated as a short stored-context ask. History is now passed through.
- **Class ability scaling missed Effect(s) formulas and hub-table boosts** (`scaling_from_item`, `scaling_from_text`, `load_class_wiki_scaling`, `_ITEM_PAGE_JS`, `_ABILITY_HUB_JS`). The store only kept a `Damage: (+N per STAT)` infobox row, so Volcanic Sheath (`Effect(s): Area Damage: 400 (+10 per WIS over 50)`) and Elegant Parasol (flat trail `Damage: 200-300`, VIT on Effect(s) / hub "scaling with VIT") never entered `wiki:ability-scaling`. Wis/Vit Kensei then told Claude the class had no such ability. Every class hub now treats Effect(s) formulas, `scaling with STAT`, and `N% STAT Boost` as scaling, keeps hub `rowText` when the item page is thin, reads sprite `alt` when the name link has no text, and finds an infobox by any Tier/MP Cost/On Equip row. Formula evidence ranks above boost-only so Parasol beats Paper Machete on Vitality. Cache `wiki:ability-scaling:v7`; minted essays move to `wiki:build:v2` / `wiki:ability-brief:v2` so the old "no ability" replies are not replayed. Found live: Wis Kensei / Vit Kensei.
- **Hardmode Shatters told Claude the indexes have no page** (`get_or_scrape_index`, `CORE_DUNGEON_PAGES`, `retrieve_dungeon_guide`). Chat is cache-only. After an API restart the dungeon index key is empty, so the matcher only saw biomes + Keyper. Hardmode Shatters is a Hard Mode section on `/wiki/the-shatters`, not its own index row, so `match_index_pages` returned nothing and the specialist said "The RealmEye dungeon indexes have no page that matches this dungeon." Core dungeon pages (The Shatters, Moonlight Village, Oryx's Sanctuary, Nest, Cultist Hideout) are always merged, same as Keyper/biomes. A matched slug whose wiki page is not in Redis is scraped once instead of telling Claude to give up. Found live: Guide to complete Hardmode Shatters.
- **Unique-stat weapon briefs ranked T7 by On Equip** (`retrieve_weapon_brief`). Wis Kensei visualized `Buster Katana` because `_top_stat_items(..., include_t7=True)` put the T7 with +WIS first, and `_first_visualizer_item` skips the "Overall base katanas" family-core line. Armor already dropped T7. Weapons now drop T7, unique class+stat asks do not emit hub On Equip ranks, and an empty ability store scrapes instead of returning a blank specialist chunk. Found live: wis kensei build.
- **Minted class briefs froze the empty-store miss** (`maybe_mint_brief`, `try_stored_reply`, `retrieve_ability_brief`). Found live Sep 18: Wis Kensei was asked while sheaths were still scraping on the v7 deploy warm. That essay minted to `wiki:build:v2:kensei:wisdom`, so "Give me a different wisdom kensei" replayed the same loadout after the store filled. Vit Kensei on the same store was fine because that key was not minted. Minted essays move to `wiki:build:v3` / `wiki:ability-brief:v3`. `try again` / `different` drops the matching brief and streams. A class+stat essay is not minted until the ability store lists that stat and the reply names one of those abilities. Chat cache-only force-scrapes when the asked stat is missing from a filled class payload, with a one-day miss key so a class that truly has no such ability is not re-scraped every turn. SET VISUALIZER tells Claude not to copy a weapon into an empty ability slot.
- **Paywall DPS demo slide** (`PaywallModal`). A third value slide sits between set-building and the visualizer, playing `/videos/paywall/dps-demo.mp4` with the same `PaywallDemoVideo` player, SWA `video/mp4` route, autoplay-once, and pause-the-others behavior. Signup/pricing stay the last step. Found live: testers on other devices never saw the first two demos when the MP4s were not in `web/public` or were Clipchamp exports with `moov` after `mdat`.

### Tests
- `test_hardmode_shatters_matches_core_pages_when_index_is_empty`
- `test_hardmode_shatters_guide_does_not_claim_missing_index`
- `test_weapon_brief_never_names_a_t7_katana`
- `test_retry_drops_the_minted_build_brief`
- `test_does_not_mint_while_ability_store_is_empty`
- `test_does_not_mint_when_reply_omits_the_scaling_ability`
- `test_ability_brief_reloads_when_asked_stat_is_missing`
- `test_ability_brief_does_not_loop_scrape_when_stat_has_no_ability`
- `test_retry_build_stays_on_sonnet`
- `test_effect_area_damage_per_wis_is_scaling`
- `test_effect_scaling_with_vit_is_scaling`
- `test_stat_multiplier_percent_boost_is_scaling`
- `test_hub_row_scaling_with_vit_does_not_tag_on_equip_att`
- `test_kensei_store_keeps_wis_and_vit_sheaths_from_hub_or_effects`
- `test_wis_kensei_ability_brief_names_volcanic_sheath`
- `test_sheet_stat_tradeoffs_are_not_fire_rate_enchants`
- `test_fire_rate_and_damage_tradeoffs_still_change_the_weapon_shot`
- `test_projectile_speed_is_not_damage_or_fire_rate`
- `test_an_ability_that_scales_with_speed_uses_the_sheet_speed`
- `test_sheet_stat_channel_names_every_reconstruct_feed`
- `test_slot_contributions_name_all_four_pieces`
- `test_board_reconstruction_copy_matches_the_real_formulas`
- `test_postgres_ddl_widens_integer_to_bigint`
- `test_upsert_accepts_a_javascript_millisecond_timestamp`
- `test_dps_breakdown_follow_up_stays_on_sonnet`

## [2026.09.17] - Sep 17, 2026

### Added
- **DPS specialist, RealmShark as source of truth** (`api/services/dps_specialist.py`, `loadouts_from_rows`, cache `dps:top:v2`): leaderboard rows now keep `weaponDamage` / `abilityDamage` / `totalDamage`, per-slot on-character enchants, stats, and calculator `debug` (Flurry damage/RoF multipliers, `abilityStatModMult` / `effectiveAbilityStatModMult`, ability-use count, full-buff flags). Number asks ("What's the max defense for necromancer?", "how much DPS", "only numbers") route to the DPS slot only (`is_stat_number_query`) so they no longer get SET VISUALIZER PICKS or a cached loadout brief. Wiki Damage/Shots/Rate of Fire plus ATT/DEX reconstruct the 5s weapon half. Wiki ability Damage rows (`565 (+2 for every ATT above 55)`) reconstruct the ability half: `(avg + per * max(0, stat * StatMod - threshold)) * shots * uses * buffs`. Stat Mod Multiplier I-IV is +6/9/12/15% of the scaling stat (`debug` wins when it is not 1). Ideal ability enchants are Stat Mod plus Flat or Percentage Mana Regen unless the wiki formula has no scaling (then skip Stat Mod). Stat Mod and MP Cost Reduction cannot roll together. Armor/ring swaps apply On Equip plus On Ability procs (Vesture +15 ATT / -6 DEF is 100% uptime in the 5s / 8-use dummy). A swap scales both stored RealmShark weapon and ability numbers by reconstruct_new / reconstruct_old. No Defense Necro board still answers from other Necro boards' stats plus the class-page wiki total when scraped (`total` on `wiki:class-maxstats:v1`). Found live in guild chat: max DEF Necro always returned a set with no numbers.
- **Worn-set effect inspect** (`inspect_worn_set` in `api/services/dps_specialist.py`): `retrieve_dps_brief` walks the worn weapon, ability, armor, and ring wiki pages plus on-character enchants first, then parses Effect(s) / Reactive Proc / On Equip for status grants (berserk, damaging, curse, expose, vulnerable, healing, slow, armor broken) and stat procs. No item names are special-cased. Chance and On Hit are listed but not treated as 100% dummy uptime. On Shoot combat deltas still apply to reconstruct. RealmShark board numbers keep party buffs; a swap that removes the set's only self-buff should drop it. Item lookup uses `read_cached_item` (v3 then v2).
- **Player-set DPS** (`extract_player_ign` possessives, `format_player_set_dps`): any `IGN's {class}` DPS or max-stat ask scrapes that RealmEye profile, picks the matching character, and reconstructs dummy DPS from worn wiki pages plus sheet stats. Stored fame/guild lookups, `player_only` Haiku routing, and inferred class-primary-stat loadouts no longer steal these turns, so they cannot dump SET VISUALIZER PICKS or a tiered-wiki "best set". Tooltip lines like `Flurry of Blows IV` count as on-character enchants. On Ability procs add to the player sheet (RealmEye totals are On Equip only). No class board still copies the player reconstruct instead of refusing a number. Found live: a Bard DPS ask with an IGN in the message never reached the DPS specialist.
- **DPS reconstruct accuracy** (`api/services/dps_specialist.py`): calibrated against live RealmShark Attack Necro / Wizard / Archer rows, RealmEye wiki shot/status pages, and the enchanting table. Vulnerable is 115% (Quiver of Thunder wiki). Exposed stays x1.20 on the 0 DEF dummy (wiki Exposed is -20 DEF for live combat later). Damaging is weapons-only. Wiki en-dashes parse as ranges. Bolt Thrower two-burst shots (`1; 4` with two damage groups) sum into one burst. `weaponEnchant` debug still wins; otherwise Flurry / Overwhelming Strikes / Damage Tradeoff I-IV come from the enchanting wiki. On Shoot combat deltas (DEX/ATT) are up for the dummy window. Weapon reconstruct now sits within 1% of the stored shark weapon half (Attack Necro 123,869 vs 123,643).
- **Chat screenshot attachments** (`ChatInterface`, `ComposerImages`, `ChatRequest.attachments`): the composer takes PNG/JPEG/WebP/GIF screenshots (character stats, vault, inventory) via the paperclip, paste, or drag-and-drop. Up to 4 images render as thumbnails inside the input, the same shape as the Cursor composer. `streamChat` sends them as Claude vision blocks. `_user_content` was previously unused, so an attached file never reached the model. Clicking a thumbnail opens `SpriteZoomTrigger` `preview="image"` with the full encoded picture.
- **Veteran biomes** (`api/services/biomes.py`): RealmEye pages for Floral Escape, Carboniferous, Sanguine Forest, Runic Tundra, and Deep Sea Abyss are merged into the dungeon index, warmed on boot, and served as stored answers. `carniferous` maps to Carboniferous. Potion sentences stay on biome pages (dungeon drop lists still skip potions). Daily quest rotation includes the other veteran biomes. Found live Sep 17: "What veteran biomes drop what potions" had no biome store and fell through to generic weapon/ability RAG.
- **Item drop locations** (`_ITEM_PAGE_JS`): infobox rows `Drops from` / `Obtained through` / `Dropped by` / `Obtained from` are collected even when they are not the first table header. Item cards show `Drops from ...`.
- **Composer name suggest** (`GET /items/suggest`, `ComposerSuggest`): grey remainder + Tab from `wiki:suggest:v2`. The index is one harvest of the scrape cache: hub lists, every `item:profile:v3`, dungeon index + `wiki:guide:v6` titles/drops/`drops_from` bosses, biomes, community nicknames, generated aliases, and place-slot nicks. First miss rebuilds it. Shiny typing skips ST. Overlay is painted on top of the input.
- **Farm TLDR cards** (`api/services/farm_guides.py`, `web/components/chat/FarmTldr.tsx`): "how to farm Ogmur / Scythe" is a stored reply with `[farm:ogmur]` / `[farm:scythe]`. The UI paints a sprite panel (swap arrows, prohibition marks, short labels) using wiki item sprites plus simple pixel enemies. Ogmur: Lord of the Lost Lands in Runic Tundra, stun on last crystal, skip add-chasing. Scythe: Spectral Jailer in veteran biomes, loot under the Penitentiary portal, Skeletal Centipede as the easier source.
- **Site Feedback modal** (`api/services/product_feedback.py`, `POST /chat/site-feedback`): the header/sidebar "N free in-depth responses left" chip is a Feedback button. Answers (rating, what works, what to fix, anything else, optional IGN, signed-in email) insert into `product_feedback`. Same Azure Postgres database as accounts/chat_sessions when `DATABASE_URL` is set. Scan with `SELECT created_at, rating, what_works, what_to_improve, anything_else, email FROM product_feedback ORDER BY created_at DESC LIMIT 100;`. Local SQLite is `data/product_feedback.db`. Capped at 5 submits/hour per IP or signed-in subject.
- **Free in-depth remaining in the account menu** (`AccountMenu`): the old top-right / sidebar quota chip copy (`freeInDepthPromptsLeft`) is a menu item under Register (guest) or Billing (signed-in free). Clicking it opens `PaywallModal` the same way the chip did. Hidden for paid.
- **Admin notifications** (`api/services/admin_access.py`, `api/services/admin_events.py`, `GET /admin/notifications`, `AdminNotificationsModal`): the account-menu bell is admin-only. `ADMIN_IGNS` (default `Turbine`) and `ADMIN_EMAILS` are checked on every call via `is_admin`; a JWT `role` claim is convenience only and a forged `role=admin` still 403s. The modal is a Billing/Paywall overlay (the old `/account/notifications` client route froze the static export). Feed merges Claude-turn costs (`admin_chat_events`, from this deploy), `product_feedback` with a mailto reply template filled from the submitter's answers, new `accounts` rows, and Stripe `entitlements`. Header also shows today's spend from `budget_state`. `UsageResponse.is_admin` is what the UI keys off. Chat transcripts are not stored.

### Changed
- **Admin notifications overlay** (`AdminNotificationsModal`): the feed is portaled to `document.body` at `z-[80]` so it is not trapped in the header stacking context. `/account/notifications` is a static back-to-chat page with no `useRouter`, which froze the static export. Unknown feed kinds are ignored instead of throwing while counting.
- **Paywall demo player on phones** (`PaywallDemoVideo`): production already serves `/videos/paywall/*.mp4` as `video/mp4` with byte ranges (H.264 Main 4.1, AAC, moov-first). Testers still saw a blank frame when autoplay was blocked or Safari clipped an `overflow-hidden` / absolutely-positioned video. The file is now `src` on `<video>` plus `<source type="video/mp4">`, `autoPlay` + muted `playsInline`, a tap-to-play overlay until `playing`, `translateZ(0)`, and no overflow clip on the video chrome. SWA also sets `Content-Type` on `/videos/*`. Deploy workflow sets `IS_STATIC_EXPORT=true` so Oryx keeps the `out/` export.
- **Source loot stays in the wiki store** (`extract_drop_source_query`, `cached_drops_from_source`, `_source_drop_reply`): loot asks for any dungeon, boss, or NPC read `drops_from` on cached dungeon pages plus item `drop_locations`. "what Nox the wild shadow and the twilight archmage drops" splits into two sources and only lists that boss's rows. Empty store says so rather than guessing. `the-keyper` is still merged into the dungeon index. Claude prompt: never invent item names or turn a source into a made-up title.
- **Item scrape loot rows** (`_ITEM_PAGE_JS`): drop places also come from `Drop location` / `Loot table` keys, two-cell infobox rows, and `Loot table` / `Drop locations` headings with wiki links. Dungeon pages also read `Loot table` / `Loot` / `Drops` headings. Ingested RAG text includes `Shiny sprite: yes/no`.
- **Place-slot nicknames** (`resolve_place_slot`): `fungal star` / `crystal star` resolve from cached `drop_locations` plus item type/hub. Sister weapon hubs share a meaning (staff/spellblade, sword/flail, dagger/dual-blade, bow/longbow, wand/morning-star, katana/tachi). Shiny asks skip ST (set pieces cannot be shiny) and prefer UT, so `shiny fungal star` is Star of Enlightenment, not Crystalline Kunai.
- **Limited Edition originals** (`original_name`, `prefer_original_name`): item scrape keeps `Reskin of` / `Original`. Resolve and shiny stored replies swap the clone for the original unless the user asked for LE. LE pages are not ingested into Qdrant. Claude prompt: name the original, not the LE title.
- **Slot rarity frames** (`parse_rarity`, `LoadoutRarity`): Uncommon / Rare / Legendary use `slots.png` x=0 / 48 / 96 the same way Divine uses x=144. Stored `[loadout shiny legendary]` tokens, `make it {tier}` follow-ups reuse the last visualized item and keep shiny, and the Claude prompt lists all four enchantment slot tiers so it does not deny Legendary.
- **What's new timeline** (`web/lib/changelog.ts`, `ChangelogModal.tsx`): the oldest user-facing block (`2026.09.13`) keeps the first third of its bullets as the Sep 13 ship. The rest sit under a `phase` entry titled "Development phases before going live", with no version badge or timestamp.

### Fixed
- **Every button in the app was dead, and it had nothing to do with the button being clicked** (`web/app/global-error.tsx`, new file). Reported as "all buttons not working currently" while chasing the notifications modal. The page rendered fine and then threw `ChunkLoadError: Failed to load chunk /_next/static/chunks/web_app_layout_tsx_<hash>._.js` before React hydrated, so nothing was wired to any handler and the only symptom was "Application error: a client-side exception has occurred" in the console. The tab was holding HTML from a previous dev server (`web/.next/dev/cache` had been deleted out from under a running server, and `start_services.ps1` then started a new one), so the hashed chunk names it asked for no longer matched. Loading the same URL with a cache-busting query string rendered and clicked normally, which is what confirmed the source was fine. There was no `global-error.tsx`, and since `next.config.ts` uses `output: "export"` the same total blackout can hit production for anyone whose tab is open across a deploy. Added a global error boundary that reloads once (60s cooldown recorded in `sessionStorage`, so a genuinely broken build shows a card instead of looping) on `ChunkLoadError` / "Loading chunk" / "Failed to load chunk" / "dynamically imported module" / "importing a module script failed", and otherwise renders a Reload plus Try again card. `sessionStorage` access is wrapped because private-mode denial would otherwise throw inside the error boundary itself.
- **An ability's damage was read from whichever wiki line matched first, which for The Triangle was a stat-boost row** (`parse_ability_formula`, `_damage_formula_match`). `parse_ability_formula` joined every stat into one blob and took the first `N (+M per STAT over T)` match. RealmEye orders `Effect(s)` before `Damage`, and boost lines have the identical shape, so The Triangle parsed as `ATT Boost: +5 (+1 per 8 WIS over 75)` instead of its real `Damage: 300-450 (+25 per ATT over 55)`. Turbine's Bard reconstructed to `ability 662.4` and reported Wisdom as the scaling stat, which is exactly the "it claimed Triangle scaled off WIS" complaint: the falsehood came from our own brief, not the model. The formula now reads the item's `Damage` row (skipping `Total Damage`, which is shots x damage and would double-count `Shots`), and only falls back to other rows when the matched line itself says "damage". Same character now reconstructs `ability 57,960.0`, and the cross-check line against the live RealmShark Attack Bard rank 1 row went from nonsense to `39,330.0` reconstructed vs `42,941.3` stored.
- **`+1 per 8 WIS over 75` was read as +1 per point** (`_ABILITY_FORMULA`). The step count was matched and discarded by a bare `(?:\d+\s+)?`, inflating any such rate by the step (8x here). It is now captured as a named `div` group and divides `per`.
- **One un-warmed worn piece dropped a named player's whole reconstruct to "no numbers"** (`worn_item_profiles` in `api/services/dps_specialist.py`). `format_player_set_dps` scrapes the RealmEye profile live but read every worn item through cache-only `_cached_item`, so a piece missing from the warm store produced "No stored wiki profile for [item:X]" and then "Not enough stored wiki shot/ability data to reconstruct this set", leaving the model with nothing to copy. Worn gear now fills gaps through `wiki_scaling._profiles_for_names` (capped at the equipped slots, since that turn already pays a live profile scrape), and a piece with no wiki page is negative-cached for an hour via `mark_item_missing` / `is_item_marked_missing` so the next turn fails fast instead of re-paying the Playwright timeout. A dead scraper keeps the pieces already in the store.
- **The model disowned its own correct DPS numbers on the very next question** (`is_dps_follow_up`, `dps_subject_from_history`, `route_slots`, `retrieve_build_knowledge`, `_dps_agent`). Turn 1 "What's the DPS for Turbine's bard?" was right: `is_dps_query=True`, `extract_player_ign='Turbine'`, `slots=['dps']`, 15,257 chars of context with the `PLAYER SET DPS` block and the reconstruct. Turn 2 "What do the numbers look like?" named no class, stat, IGN, or the word DPS, so `is_dps_query` returned False, `extract_player_ign` returned None, and it routed to `['weapon','ability','armor','ring','enchantment']` with no reconstruct anywhere in context. Claude then apologised and called its own figures made up, which reads as the whole feature being wrong rather than one dropped turn. `is_dps_query` / `is_stat_number_query` now take `history`, and `is_dps_follow_up` recognises breakdown ("give me a breakdown", "show the math", "how did you get that number", "walk me through it", "prove it"), what-if ("what if he swapped to a Doom Bow?", "instead of the Triangle", "how about"), and comparison ("how does that compare", "better than", "is that any good") phrasings. It is gated on conversation history and walks the chain backwards, so bare follow-ups keep it alive across many turns, an explicit DPS ask closes it as a match, and a turn with its own topic ends it (a Shatters question followed by "explain that" is not a DPS turn). `dps_subject_from_history` recovers the (IGN, class) of the most recent DPS turn, applied both in `retrieve_build_knowledge` and again in `_dps_agent` so the recovery holds no matter which caller reached the slot. Replaying the five-turn conversation: every follow-up now carries `PLAYER_SET_DPS=True` with the identical `weapon 59,315.7 / ability 57,960.0 / 23,455.1 potential DPS`. Repro tool: `api/scripts/probe_dps_followup.py`.
- **A what-if weapon swap was answered by the dye previewer** (`route_slots`, `retrieve_build_knowledge`). "What if he swapped to a Doom Bow?" matched `is_skin_visualize_query`, which is checked before the DPS branches, so it routed to `['skin']` and the DPS slot never ran on the exact "what-ifs/potentials" turn the specialist exists for. `set_visualize`, `skin_visualize`, and `enchant_only` are now suppressed on a DPS follow-up in both the router and `retrieve_build_knowledge`, and the swapped-in piece's own slot rides along (`['dps', 'weapon']`) so its wiki page is available to rescale the reconstruct.
- **The brief carried the finished DPS number but none of the arithmetic** (`format_dps_derivation`, `steps` on `reconstruct_weapon_damage` / `reconstruct_ability_damage`). Even with the reconstruct in context, "what do the numbers look like?" had nothing to show: the block ended at `weapon 59,315.7, ability 57,960.0, potential DPS 23,455.1`, so a breakdown could only be re-derived or guessed. Both reconstructors now optionally record every intermediate factor (burst, APS, rate of fire, attack multiplier, enchant and buff multipliers, per-shot, per-use, use count, window) and the brief prints a `HOW THIS RECONSTRUCT WAS BUILT` section spelling out each multiplication down to the total and the divide by 5s. For Turbine's Bard that is `205.0 per volley x 11.09 attacks/sec x 2.420 attack multiplier x 2.156 party buffs x 5s = 59,315.7` and `Attack 96 -> per shot 375.0 + 25.0 over 55 = 1400.0, x3 shots = 4200.0 per use, x8 uses, x1.725 buffs = 57,960.0`.
- **The prompt had no rule against disowning a number it was handed** (`build_system_prompt`). Nothing stopped the model from apologising for its own specialist-sourced figures. It is now told that numbers from earlier turns came from these same chunks, never to say it invented, made up, or cannot support one, to walk through the `HOW THIS RECONSTRUCT WAS BUILT` steps on a breakdown ask, to say it needs to recalculate if those steps are absent rather than disowning the earlier answer, and to rescale from the reconstruct in context on a what-if instead of restarting from an empty sheet.
- **The word "like" was read as the HP stat** (`_ENGLISH_FILLER` in `api/services/fuzzy_match.py`). The closed-vocab typo matcher 1-edit-corrected the token `like` onto the HP alias `life`, so `parse_query("What do the numbers look like?")` returned stat `HP` with no history at all, and any sentence containing "like", "look like", or "I'd like" dragged an HP build onto the turn and flipped `buildish` True. `item_aliases.py` had already hit this class of bug locally and worked around it with `min_len=4` to stop "get" becoming "gem". The guard now lives in `fuzzy_closed_vocab` itself, so classes, stats, dungeon nicknames, and item nicknames are all covered: a token that is an ordinary English word is never typo-corrected, since a real typo is almost always a non-word. Exact aliases are matched before the guard, so `life`, `health`, `hp`, and `knight` still resolve, and `brd` -> Bard / `atack` -> Attack still snap.
- **Every reply containing an item threw two hydration errors** (`web/components/chat/SpriteZoom.tsx`). `SpriteZoomTrigger` wrapped its anchor in a `<div>` and `MessageBubble` renders markdown paragraphs as `<p>`, so an inline `[item:...]` token nested a div inside a p. That is invalid HTML the browser reparents, and React reported it from both sides: "In HTML, `<div>` cannot be a descendant of `<p>`" against `SpriteZoom.tsx:375` and "`<p>` cannot contain a nested `<div>`" against `MessageBubble.tsx:218`. The anchor and its popover menu are now `<span>` with `useRef<HTMLSpanElement>`; display stays `inline-block` / `block` / `flex` by class, so layout is unchanged. The full-size overlay is `createPortal`ed out of the paragraph and stays a div. Dev overlay went from 2 issues to none with item sprites rendering unchanged.
- **The highest-DPS bow in the game reconstructed as a 30-damage bow** (`parse_shot_groups`, `estimate_weapon_dps`, `reconstruct_weapon_damage`). Reported live: Turbine's Huntress showed a Makakoyumi weapon half of 3,063.3 damage over 5s. RealmEye separates a weapon's projectile definitions with `;` in every row, and two different things wear that shape. Pattern A is one Rate of Fire with several damage groups forming one volley, where `Shots` covers all of them (Aspirant's Bow, `110-120; 35-45` with `Shots: 3`); averaging across shots is right and 72 of 479 cached weapons are this. Pattern B is a Rate of Fire that is itself a list, so each group is a separate firing mode at its own rate (Makakoyumi, `Damage: 800; 20-40` at `Rate of Fire: 33%; 200%`); 36 of 479. We handled only Pattern A, and worse, `_RANGE.findall` skipped the bare `800` group entirely (10 cached groups are a bare number), so Makakoyumi was modelled as a 30-damage bow fired at the first listed rate. Groups are now split on `;` first, each carries its own rate of fire and shot count, and a Pattern B weapon is summed per group instead of collapsed onto one blended rate. Makakoyumi's weapon half went 3,063.3 to 80,202.2 over 5s, which puts it above Warmonger on the same character as expected. A weapon with a single rate is arithmetically unchanged (`per_second == burst * aps`), which the 133-row calibration confirms: production error moved from `+9.3% / -8.4% / +10.3%` to `+7.9% / -7.1% / +2.5%`.
- **A four-digit damage value was truncated at the comma** (`_THOUSANDS`, `_digits`). `\d+` stops at `,`, so `Venerable Doom Bow: Damage: 900-1,100 (average: 1,000)` parsed as the range 900 to 1. Damage, shots, rate of fire, and the ability formula now strip a separator that sits between two digits, which leaves prose commas ("Drops from X, Y") alone. Found by the audit's new plausibility check rather than by a wrong answer reaching a user.
- **A multi-rate weapon's breakdown did not add up to its own total** (`format_dps_derivation`). With the per-group fix in, the derivation still printed the legacy blended pair, claiming "830.0 damage per volley x 3.16 attacks/sec" next to a total of 100,252.7 when that arithmetic reaches about 84,800. A breakdown that cannot reproduce its own total is precisely what the derivation block exists to prevent, so a Pattern B weapon now prints one line per projectile group with its own rate and per-second contribution, then the sum.
- **The model quoted two stats out of eight** (`build_system_prompt`). The brief already carried the full sheet (`HP 810, MP 440, Attack 122, Defense 57, Speed 58, Dexterity 68, Vitality 47, Wisdom 67`), but the reply mentioned only the ATT and DEX that appear in the arithmetic, so a reader could not confirm which character had been priced. The prompt now requires stating all eight stats for a named character's DPS, and calling out when the working Attack or Dexterity differs from the sheet because of a proc.
- **Every stat penalty in the game was invisible** (`_BONUS_PAT`, `on_equip_bonuses` in `api/services/wiki_scaling.py`). The On Equip patterns hard-required a literal `+`, so `Mad Javelin: +10 ATT, -3 DEX` parsed as `{"Attack": 10}` with no Dexterity entry at all, and a reconstruct kept attack speed the character does not have. `Cobra Serpentis Scroll: -20 HP, +2 ATT, +2 DEF, +4 DEX, -5 VIT` lost both of its penalties. 78 of 1,444 cached items state at least one negative modifier. The sign is now captured, and the per-stat pick is `max(hits, key=abs)` so a line mentioning a stat twice still resolves while a lone penalty is not read as a gain. This sheet also feeds enchant and build advice, not just DPS.
- **An ability that does not scale contributed nothing at all** (`_flat_damage_row`, `parse_ability_formula`). `_ABILITY_FORMULA` requires the `(+N per STAT over T)` clause, and there was no fallback, so `Noble Mandolin (Rehearsal): Damage: 320-400 (average: 360)` returned `None`, the ability half was dropped, and the set came out labelled `weapon-only DPS` as though the wiki page were unreadable. 58 of 1,444 cached items have a flat Damage row. A flat row now yields a formula with `per: 0.0` and `scales: False`, so it reconstructs at its stated damage and cannot gain from a high stat. Ability gaps in the audit went 58 to 0.
- **A player ask and a board ask disagreed about the same gear** (`combat_stat_sheet`). The player-set reconstruct applied `ability_deltas` and `shoot_deltas` across every stat; the board-row rescale applied only `shoot_deltas`, only for Attack and Dexterity, and then passed the ability reconstructor the untouched row stats. So Vesture's `On Ability Use: ATT Boost (+15 ATT)` counted when the question named a player and not when it named a class, and a Wisdom proc moved a player's ability half but never a board row's. Both paths now build the in-combat sheet through one `combat_stat_sheet(sheet, catalog)`, which applies both proc buckets to every stat and does not mutate the caller's sheet.
- **Every player-set reconstruct silently assumed a party Berserk, then blamed a random item for it** (`_debug_mults`, `set_grants_berserk`). `_debug_mults` read its flags from `debug["buffs"]`, a key nothing ever wrote, so every `buffs.get(name, True)` fell through to `True` and Berserk's x1.25 APS was applied to every set unconditionally. Turbine's 8/8 Bard came out at 23,455.1 against RealmShark's own 21,381.1 for the same character, and because the brief asserted Berserk was in effect without naming a source, the model went looking for one and picked the nearest proc line, reporting "Berserk multiplier (from Vesture of Duality on-ability proc): x1.25". Vesture grants `ATT Boost (+15 ATT)` and `DEF Decrease (-6 DEF)`, not Berserk. Berserk is now an explicit `berserk_source` argument to `reconstruct_weapon_damage`, defaulting to off, and `set_grants_berserk` decides it from the worn pieces' own `parse_status_grants` output plus any `OnHit Berserk` enchant text. Confirmed weapon-only against the official calculator, which applies it as `aps * (Berserk ? 1.25 : 1)` and nowhere else (`getAttacksPerSecond` in `rotmg-mirror/rotmg-dps-calculator`).
- **Damaging was withheld from the ability half** (`_debug_mults`). The code applied Damaging to the weapon only, citing the RealmEye status-effects page ("Increases damage from weapons by 25%"). The official calculator disagrees: `getAverageDamage` multiplies *any* projectile's base by 1.25 before DEF, weapon or ability. RealmShark's own stored halves settle it. Across the 133 cached board rows that carry both a `weaponDamage` and an `abilityDamage`, weapon-only Damaging left the ability half a median **26.7% under** RealmShark; applying it to both halves brings that to **8.4% under**. Damaging, Curse, Exposed, and Vulnerable now all apply to both halves and Berserk is the only weapon-only multiplier, since it buys attack speed rather than damage.
- **Two candidate "corrections" were rejected by the same data** (`api/scripts/calibrate_dps_buffs.py`, new file). The calculator source implies Exposed is `def -= 20` (a flat DEF reduction, which on a 0 DEF dummy is a flat +20 per projectile, not the x1.20 we use) and has no Vulnerable in its `EnemyEffects` list at all. Both changes make the fit dramatically worse against RealmShark: Exposed as flat DEF moves the weapon half from +8.9% to -23.3%, and dropping Vulnerable takes it to -33.3%. RealmShark evidently models Exposed as a multiplier and does include Vulnerable, so both stay as they were. Recorded here because the calculator source is otherwise the better reference and the next reader will be tempted by exactly these two edits.
- **5s damage totals were labeled DPS, so a breakdown reported figures 5x too large** (`format_dps_derivation`, `reconstruct_*`). Both halves are damage summed over the 5s window, but the brief printed them beside the word DPS, and the model faithfully echoed "Weapon half: Warmonger -> 59,315.7 DPS" and "Ability Half: The Triangle -> 57,960.0 DPS". Each half is now written as "total damage, NOT per second", the derivation says which single number is per second, and the buff lines name where each multiplier comes from (and, when Berserk is absent, say "no Berserk (nothing in this set grants it)") so a multiplier cannot be re-attributed to the wrong item.
- **A half-reconstructed set was still labeled "potential DPS"** (`format_player_set_dps`). A summon/tick ability has no reconstructable `Damage` row (Genesis Spell is "Summons 4 portals which zap enemies and deal 350 damage ... every 0.4 seconds"), so Turbine's Wizard summed the weapon half alone and presented it as the full ceiling. The label is now `weapon-only DPS` (or `ability-only DPS`), plus an explicit line naming the missing piece and telling the model to say the damage is not included rather than call it the full potential DPS.
- **Average shot damage was half a point high on every ranged weapon** (`parse_shot_groups`). We used `(min + max) / 2`, but the RealmEye Weapon Attributes page states that the maximum shown in-game is one higher than the value a shot can actually roll, so the true average is half a point lower: Warmonger's `95-110` averages 102.0, not the 102.5 the infobox prints. A fixed-damage group (Makakoyumi's bare `800`) is left alone since it has no range to correct. Small on its own, and it moved the 133-row calibration the right way, but it shifted six test expectations that had encoded the old value.
- **Enemy defense was not modelled at all, so no number could be checked against the game** (`reconstruct_weapon_damage`, `_MIN_HIT_FRACTION`). Every figure assumed a 0 DEF target. DEF cannot be applied to a total afterwards because it is subtracted from *each projectile*, which is why it punishes a fast multi-shot weapon far harder than a slow one, and it can never take a hit below 10% of its pre-DEF damage. `enemy_def` now subtracts per projectile behind that floor. This also forced the buff order to be correct: the official calculator applies Damaging *before* the subtraction and Curse, Exposed and Vulnerable *after*, so `_debug_mults` returns the two groups separately instead of one blended multiplier. At 0 DEF the result is identical, which is what keeps the RealmShark calibration stable.
- **A summon's armor piercing exempted the wielder's own shots from defense** (`armor_piercing`, `summon_pierces`, `tag_group_piercing`). "Ignores defense of target" was read from anywhere on the page, but RealmEye keeps `Effect(s)` and `Summon Effect(s)` as separate rows precisely because they describe different projectiles. Makakoyumi is the case in point: its `Damage: 800; 20-40` at `Rate of Fire: 33%; 200%` is the bow's own shot followed by the summon's, and only the summon pierces. Scanning every row would have exempted **96 of 479 cached weapons** from enemy DEF entirely, while attributing the piercing to the weapon would have wrongly charged the summon. Piercing is now tagged per projectile group: the wielder's shot pays DEF in full and the trailing summon group ignores it.
- **The only number in the brief was an unreachable ceiling** (`format_practice_dummy`, `set_inflicted_debuffs`). Every figure was priced the way RealmShark prices its boards: 0 DEF and party Damaging, Curse, Exposed and Vulnerable all up. A player testing alone on the guild hall dummy has none of that and 15 DEF to chew through, so the headline read as absurd next to what they measured, and the reply had no way to acknowledge their number without appearing to contradict itself. The brief now carries the same set priced against the practice dummy alongside the ceiling, and tells the model to compare a reported measurement against that figure and never to call a lower measurement wrong. The debuffs counted are only the ones the set can put up by itself, read off the worn pieces rather than assumed: Trap of the Vile Spirit's "On enemies: Inflicts Curse" earns Curse and nothing else. A resistance line ("Cannot be Cursed") is explicitly not a debuff the set inflicts. Turbine's Huntress reconstructs to 124,183.6 over 5s at the ceiling and 71,753.7 on the dummy, against roughly 80,000 measured in game.
- **One item's cooldown suppressed a different item's debuff** (`set_inflicted_debuffs`). Sustainability was judged against the whole set's combined text, so Amulet of Restoration's `Soul Concentration Cooldown: 1800 seconds` vetoed the Curse that Trap of the Vile Spirit inflicts on a different item, cutting the dummy figure by 25%. The check is now per line.
- **A Huntress trap's Curse leaked onto the next class in the same chat** (`set_inflicted_debuff_sources`, `_ENEMY_CONTEXT`, `build_system_prompt`). Turn 1 priced Turbine's Huntress dummy with Curse from Trap of the Vile Spirit. Turn 3 priced Turbine's Bard (Warmonger / Triangle / Vesture / Twilight Gemstone), none of which inflict Curse, and the first Bard reply correctly said "no party buffs". The follow-up "Show me the numbers" then wrote "except Curse from your own procs" because Haiku copied the Huntress dummy sentence. Two root causes: `\bcursed?\b` would also have treated Vesture's flavor ("This cursed robe") as the Curse status, and the dummy paragraph did not name the source item or forbid copying from earlier turns. Enemy debuffs now require the noun Curse (not the adjective cursed) plus inflict-on-enemy language ("Inflicts Curse", "On enemies"), the dummy line names the item (`Curse from [item:Trap of the Vile Spirit]`) or says this set inflicts none and must not reuse a previous class's dummy, SET EFFECTS lists the missing debuffs, and the system prompt says guild hall assumptions come from this turn's chunk only.
- **Working Attack was 96 but the brief did not make both ATT procs obvious** (`format_working_stats`). Sheet 76 + The Triangle's Effect(s) ATT Boost +5 + Vesture of Duality's On Ability +15 is 96, and Warmonger's On Shoot -5 DEX is why DEX is 68 not 73. Those were already in `combat_stat_sheet`. The reply still left a reader unsure whether Vesture had been counted. The brief now prints the arithmetic per stat with the item, and the prompt requires naming every item that moved Attack or Dexterity.
- **An ability whose Damage row is 0 dropped the real hit** (`_flat_damage_row`). Trap of the Vile Spirit's live infobox is `Damage: 0` with `Sticky Bomb Damage: 1300 (+16 per ATT over 46)`. A zero pair is no longer treated as a finished formula, so the named damage row is the one that reconstructs.
- **Named-character DPS did not attach the player-lookup Characters card** (`extractPlayerLookup`, `ChatInterface`, `format_player_set_dps`). "What's the DPS for Turbine's bard?" scraped the profile for math but the UI regex only caught `/player` and exalt phrasings, so the reply had to generate gear, 8/8, and enchants in prose. Possessive IGN + class now fetches the same card lookups already use (sprites, 8/8 hover, item tooltips). The DPS brief tells the model not to reprint that card, while still feeding on-character enchants into reconstruct. Follow-ups like "what do the numbers look like?" reuse the last card.
- **On-character enchants on that card never reached the reconstruct** (`enchants_from_tooltip`, scraper tooltip). RealmEye/Bootstrap often stores the hover in `data-original-title` as one flattened line or `<br>` HTML (`Divine Warmonger UT Flurry of Blows IV`), and the parser required a whole line that ended in I-IV, so Flurry/Stat Mod dropped to 1.000x. Tooltips now read `data-original-title` then `title`, split `<br>`, and match known combat enchants inside the string. User-named enchants in the prompt are merged onto the matching slot.
- **Chat session OPTIONS preflight returned 400** (`CORSMiddleware` in `api/main.py`). The browser sends OPTIONS before PUT/DELETE `/chat/sessions/{id}`, and `allow_methods` was only GET/POST/PATCH, so renaming or deleting a chat logged a 400. PUT, DELETE, and OPTIONS are now allowed.
- **Pet Yard scrape timed out on ads** (`scrape_player_pet`). Sidebar pet lookup loaded `/player/{ign}` and clicked the "Pet Yard" tab, and an ads iframe intercepted the click. It now opens `/pets-of/{ign}` directly and only force-clicks the tab as a fallback.

### Tests
- `test_a_weapon_with_two_firing_rates_counts_both_projectiles`
- `test_a_thousands_separator_does_not_truncate_damage`
- `test_one_rate_of_fire_with_side_shots_is_still_a_single_volley`
- `test_single_projectile_weapons_take_the_simple_path` (renamed from `..._are_numerically_unchanged`: the average correction legitimately moves the number, so the guard is now that one rate of fire still takes the `burst * aps` path rather than the per-group sum)
- `test_a_multi_rate_derivation_reproduces_its_own_total`
- `test_a_summons_piercing_does_not_exempt_the_wielders_own_shot`
- `test_enemy_def_comes_off_each_projectile_not_the_total`
- `test_def_can_never_take_a_hit_below_ten_percent`
- `test_damaging_applies_before_def_and_curse_after`
- `test_one_items_long_cooldown_does_not_veto_another_items_curse`
- `test_a_resistance_line_is_not_a_debuff_the_set_inflicts`
- `test_the_dummy_figure_is_lower_than_the_ceiling_and_says_why`
- `test_flavor_cursed_is_not_the_curse_status`
- `test_working_stats_name_both_ability_attack_procs`
- `test_a_zero_damage_row_does_not_hide_the_real_ability_hit`
- `test_on_equip_penalties_are_parsed_not_discarded`
- `test_a_flat_damage_ability_still_reconstructs`
- `test_both_dps_paths_build_the_same_stat_sheet`
- `test_damaging_lifts_the_ability_half_not_just_the_weapon`
- `test_berserk_needs_a_source_in_the_worn_set`
- `test_set_grants_berserk_reads_the_set_not_a_guess`
- `test_the_brief_never_calls_a_five_second_total_a_dps_number`
- `test_set_effects_no_longer_claims_berserk_is_a_party_assumption`
- `test_max_defense_necro_is_a_number_query_not_a_set_ask`
- `test_best_dps_set_still_counts_as_a_set_ask`
- `test_route_slots_max_defense_necro_is_dps_only`
- `test_max_defense_necro_brief_leads_with_numbers`
- `test_numbers_only_build_knowledge_skips_set_visualizer`
- `test_loadouts_from_rows_keeps_enchants_and_damage_split`
- `test_reconstruct_weapon_damage_uses_shark_debug_multipliers`
- `test_scale_shark_weapon_preserves_board_baseline`
- `test_parse_ability_formula_reads_per_stat_over_threshold`
- `test_stat_mod_iv_multiplies_the_scaling_stat`
- `test_ideal_ability_enchants_skip_stat_mod_when_no_scaling`
- `test_vesture_on_ability_proc_counts_as_plus_15_attack`
- `test_losing_vesture_attack_proc_drops_ability_reconstruct`
- `test_swap_vesture_for_diplomatic_scales_weapon_and_ability`
- `test_en_dash_wiki_damage_range`
- `test_weapon_enchant_from_damage_tradeoff_when_debug_missing`
- `test_bolt_thrower_counts_both_shot_groups`
- `test_warmonger_on_shoot_dex_penalty`
- `test_inspect_worn_set_reads_grants_and_procs_from_every_slot`
- `test_parse_status_grants_is_name_agnostic`
- `test_screenshot_player_dps_prompts_are_numbers_only`
- `test_player_class_dps_extracts_ign_and_routes_dps`
- `test_player_bard_dps_uses_scraped_character_gear`
- `test_build_knowledge_player_bard_dps_does_not_hide_gear`
- `test_tooltip_enchants_parse_flattened_html_and_unique_lines`
- `test_named_enchants_in_the_message_land_on_the_weapon`
- `test_cors_allows_put_and_delete_for_chat_sessions`
- `test_scrape_player_pet_opens_pets_of_instead_of_clicking_the_tab`
- `test_player_class_dps_keeps_the_named_class`
- `test_player_dps_ask_does_not_use_stored_player_lookup`
- `test_player_dps_ask_stays_on_sonnet_even_if_flagged_player_only`
- `test_user_content_sends_image_blocks`
- `test_user_content_image_only_uses_rotmg_caption`
- `test_legacy_single_attachment_still_counts`
- `test_too_many_attachments_are_rejected`
- `test_screenshot_turns_stay_on_sonnet`
- `test_composer_wires_screenshot_thumbnails` (also asserts `preview="image"` and `ChatImageThumb` on sent bubbles)
- `test_extract_biome_survey_from_live_question`
- `test_named_biome_and_carniferous_typo`
- `test_potions_from_wiki_leads`
- `test_stored_biome_survey_lists_floral_potions`
- `test_item_scraper_reads_infobox_drop_rows`
- `test_extract_farm_ogmur_and_scythe`
- `test_stored_ogmur_farm_skips_claude`
- `test_insert_roundtrips_a_row`
- `test_site_feedback_persists_for_a_guest`
- `test_site_feedback_attaches_signed_in_email`
- `test_empty_answers_are_rejected`
- `test_rate_limit_caps_repeat_submits`
- `test_header_feedback_replaces_quota_chip`
- `test_mobile_hides_skin_look_suggestion`
- `test_static_web_app_video_route_sets_mp4_type`
- `test_extract_drop_source_query_keyper_shinies`
- `test_keyper_shinies_uses_wiki_loot_not_invented_item`
- `test_keyper_shinies_honest_miss_does_not_invent_a_name`
- `test_system_prompt_never_invents_item_names_or_loot`
- `test_extract_drop_source_query_bosses_and_missing_does`
- `test_mentions_drop_source_matches_boss_cells`
- `test_nox_and_archmage_use_drops_from_not_dungeon_title`
- `test_fungal_star_resolves_from_drop_place`
- `test_limited_clone_resolves_to_original`
- `test_suggest_matches_place_slot_alias`
- `test_shiny_fungal_star_uses_ut_not_st_kunai`
- `test_shiny_fungal_star_prefers_ut_not_st`
- `test_shiny_place_slot_skips_st_only`
- `test_staff_synonym_resolves_spellblade`
- `test_suggest_skips_st_when_query_is_shiny`
- `test_warm_suggest_index_covers_scraped_stores`
- `test_suggest_continues_last_word_in_a_sentence`
- `test_parse_rarity_picks_the_highest_tier`
- `test_legendary_item_extracts_like_divine`
- `test_make_it_legendary_keeps_shiny_from_history`
- `test_retrieve_set_visualizer_legendary_flags`
- `test_system_prompt_names_all_slot_rarities`
- `test_turbine_ign_is_admin`
- `test_other_ign_is_not_admin`
- `test_admin_email_grants_access_without_ign`
- `test_jwt_role_is_admin_for_turbine`
- `test_guest_cannot_read_notifications`
- `test_non_admin_cannot_read_notifications`
- `test_usage_sets_is_admin_for_turbine`
- `test_usage_hides_admin_for_other_accounts`
- `test_feedback_reply_template_fills_submitter`
- `test_admin_feed_merges_existing_stores`
- `test_register_turbine_session_includes_admin_role`
- `test_oldest_changelog_block_splits_into_prelaunch_phase`
- `test_ability_damage_comes_from_the_damage_row_not_an_effect_boost`
- `test_per_n_stat_scaling_divides_by_the_step`
- `test_total_damage_row_is_never_used_as_the_ability_formula`
- `test_worn_gear_missing_from_the_store_is_scraped_for_the_reconstruct`
- `test_worn_gear_with_no_wiki_page_is_remembered_not_rescraped`
- `test_worn_gear_scrape_failure_still_returns_the_scraped_profile`
- `test_unreconstructable_ability_is_not_called_potential_dps`
- `test_stale_chunk_error_boundary_exists_and_self_heals`
- `test_breakdown_follow_up_only_counts_as_dps_after_a_dps_turn` (also asserts the same words in a dungeon conversation, and with no history, are not DPS)
- `test_what_if_and_comparison_follow_ups_are_dps_turns`
- `test_dps_follow_up_chain_survives_a_long_conversation`
- `test_an_unrelated_turn_breaks_the_dps_follow_up_chain`
- `test_dps_subject_recovers_the_player_and_class_from_history` (most recent DPS turn wins when the subject changes mid-conversation)
- `test_breakdown_follow_up_routes_to_the_dps_slot`
- `test_what_if_weapon_swap_stays_on_dps_not_the_skin_visualizer`
- `test_reconstruct_derivation_spells_out_the_arithmetic` (asserts each printed factor is the one actually multiplied in)
- `test_ordinary_english_words_are_not_typo_corrected_into_game_vocab`
- `test_the_guard_does_not_block_real_stat_words_or_real_typos`
- `test_system_prompt_forbids_disowning_numbers_it_was_given`
- `test_markdown_paragraph_children_are_inline_elements`

### Dev scripts
- `api/scripts/probe_player_dps.py IGN bard necro`: prints the DPS specialist's brief for a named player's class against live Redis, with no Claude call. This is how the Triangle mis-parse above was caught.
- `api/scripts/probe_dps_followup.py`: replays a multi-turn DPS conversation through the real routing chain (`parse_query`, `extract_player_ign`, `is_dps_query`, `route_slots`, `retrieve_build_knowledge`) and prints, per turn, the slots chosen and whether the reconstruct survived. This is how the dropped follow-up context and the skin-visualizer misroute were both measured rather than guessed.
- `api/scripts/dev_admin_token.py IGN`: mints a local session for an account that already exists, so an admin-only screen can be exercised without the account password. Local dev only.
- `api/scripts/audit_item_parsing.py`: walks every cached item profile and reports where the wiki text plainly states something we did not extract, in five buckets (procs / equip / status / weapon / ability). This is what found the dropped stat penalties and the flat-damage abilities rather than waiting for a wrong DPS number to surface them. `--item "Vesture of Duality"` dumps one item's rows next to every parser's output, and `--kind weapon` narrows to one bucket. The weapon bucket does not just check that a number came back: it compares the largest damage figure stated in the row (ignoring the derived `total:` and `average:`) against the largest group actually parsed, and flags a `Rate of Fire` list that did not produce per-projectile rates. That check is what found the Venerable Doom Bow comma truncation. Locally: 1,444 items, gaps went from 254 items to 0.
- `api/scripts/calibrate_dps_buffs.py`: scores candidate buff models against every cached RealmShark row that carries both a stored `weaponDamage` and `abilityDamage` (133 of 162 rows locally), printing median signed error per half. This is what decided the Damaging question and what rejected the Exposed-as-flat-DEF and no-Vulnerable variants. Run it before touching a multiplier in `_debug_mults`.

## History
### Until Sep 17, 2026 (10:25 PM)
`parse_shot_groups` took `_RANGE.findall` across the whole Damage row, so a projectile group written as a bare number was skipped and groups never carried their own rate of fire. `estimate_weapon_dps` parsed a single `Rate of Fire` for the whole weapon and returned `dps` as `burst * aps * att_mult`. `_RANGE` and `_NUM` matched `\d+(?:\.\d+)?`, which truncated `1,100` to `1`. The weapon derivation line always printed `avg shot N x M shot(s) = B damage per volley; x A attacks/sec`. The system prompt did not ask for the character's eight stats.

### Until Sep 17, 2026 (10:00 PM)
`_BONUS_PAT` matched `\+(\d+)` per stat, so `on_equip_bonuses` reported only positive On Equip modifiers and picked `max(hits)`. `parse_ability_formula` returned `None` for any Damage row without a `(+N per STAT over T)` clause, and the returned dict had no `scales` key. The player-set reconstruct built its in-combat sheet inline (`for bucket in ("ability_deltas", "shoot_deltas")`), while the board-row rescale did `att += catalog["shoot_deltas"].get("Attack", 0)` / same for Dexterity and passed `top.stats` straight to `reconstruct_ability_damage`.

### Until Sep 17, 2026 (9:40 PM)
The buff model applied Damaging (x1.25) to the weapon half only, on the strength of the RealmEye status-effects wording "Increases damage from weapons by 25%", so ability damage carried only Curse x1.25, Exposed x1.20, and Vulnerable x1.15 for a 1.725 multiplier against the weapon's 2.156. Berserk's x1.25 attack speed was applied to every set unconditionally, because `_debug_mults` read `debug["buffs"]`, a key no caller ever populated, and every flag defaulted True. `format_set_effects` told the model the reconstruct "assumes party Damaging, Berserk, Curse, Exposed, Vulnerable". Both 5s damage totals were printed next to the word DPS.

### Until Sep 17, 2026 (8:00 PM)
`parse_ability_formula` searched all stats as one blob and took the first `N (+M per STAT over T)` match, so an `Effect(s)` boost line could stand in for the `Damage` row. A `per N STAT` step count was discarded, reading `+1 per 8 WIS over 75` as +1 per point. Worn gear in `format_player_set_dps` was cache-only, so an un-warmed piece produced no reconstruct at all. A set with only one reconstructable half was still labeled "potential DPS". The app had no `global-error.tsx`, so a stale chunk after a deploy or dev restart left every button dead with only a console message.

### Until Sep 17, 2026 (7:05 PM)
DPS reconstruct used Vulnerable 1.10 and treated wiki en-dash damage rows as a single number. Weapon enchants other than `debug.weaponEnchant` were ignored. Damaging was applied to abilities. Warmonger On Shoot -5 DEX was not in the dummy window.

### Until Sep 17, 2026 (6:50 PM)
DPS specialist first slice reconstructed the weapon half only. A swap scaled the stored RealmShark weapon number and kept the stored ability number. Ability formulas, Stat Mod Multiplier, mana regen, and armor/ring On Ability procs were still later.

### Until Sep 17, 2026
Only Divine had a loadout diamond frame. "make it legendary" fell through to Claude, which said Legendary was not a rarity.

### Until Sep 17, 2026
Composer suggest matched the whole input as one prefix. After a space, mid-sentence words like `shiny strait` dropped the grey remainder.

### Until Sep 17, 2026
Suggest index `wiki:suggest:v1` only stored catalog titles, dungeon-index titles, and place-slot aliases when the item had a known slot. Cached hub rows, item profiles, boss `drops_from` names, biomes, and single-word aliases were left out.

### Until Sep 17, 2026
Composer suggest was a row of Tab chips above the input. It did not grey in the rest of the typed name.

### Until Sep 17, 2026
Shiny `fungal star` resolved to the first matching drop (Crystalline Kunai, ST). Place-slot kinds were only star/kunai, so `fungal staff` missed a spellblade.

### Until Sep 17, 2026
Source loot stored path only matched dungeon-index titles (Keyper as an event page). Boss names like Nox the Wild Shadow and Twilight Archmage missed the store and returned "no loot table".

## [2026.09.16] - Sep 16, 2026

### Added
- **Samurai/Kensei Vit-Dex combo** (`combo_note`, `CLASS_STAT_SLOT_OVERRIDES`): Tools of the Tarnished + Fungal Breastplate is one of the strongest vitality/dexterity weapon/armor pairs. Forced overlay on Samurai and Kensei for Dexterity and Vitality (not Ninja). Named in ranking briefs, heavy-armor notes, and the Claude system prompt.
- **Unique class+stat ranking** (`is_unique_stat_build`, `resolve_source_rank`): when the asked stat is not the class's primary, ability/armor/ring follow RealmEye Maximum Achievable Stats unless a RealmShark top 5 or matching Umi `?tab=` (not General) already has that full loadout. Injected into `store_ranking_brief`, slot-graph headers, `_in_depth_build_extras`, and `format_class_max_stats`. Overlay family cores stay general gameplay.
- **Weapon / armor family cores** (`WEAPON_FAMILY_CORES`, `ROBE_CORE`, `LEATHER_CORE` in `community_knowledge.py`): player-confirmed bases injected via `weapon_core_note` / `armor_core_note` / `ability_source_note` into store ranking, slot alternatives, weapon/armor/ability briefs, and the Claude system prompt. Staves: Staff of Unholy Sacrifice. Bows: Makakoyumi. Daggers: Fractal Blades + Phantom Sickle. Swords: Divinity + Damnation. Wands: Lumiaire. Katanas: Enforcer, Valor, Tools of the Tarnished. Robes: Vesture of Duality, Diplomatic Robe, Flowering Kimono. Leather: Cackling Straitjacket, Centaur's Shielding, Ethereal Happi. Heavy: no forced list except the Samurai/Kensei combo above. Abilities: RealmShark board if present, else ability specialist. Not `overlay_slot_picks` (does not force Speed Wizard onto Unholy Sacrifice). Attack Bard still forces Triangle + Vesture.
- **Player overlay for build picks** (`api/services/community_knowledge.py`): confirmed Attack Bard BIS is The Triangle + Vesture of Duality (wiki Maximum Achievable Stats row is Concertina + Diplomatic, which is a max-stat stack, not the playstyle best). `top_build_items` applies `CLASS_STAT_SLOT_OVERRIDES` after hub ranking. Source ranking recorded: RealmShark first, overlay second, Umi in synergy, RealmEye class-page max-stats last.
- **Item upgrade notes**: if a weapon brief lists Doom Bow, it also names Clockwork Repeater.
- **Community nicknames**: `triangle`/`the triangle` → The Triangle, `cbow` → Coral Bow, `lbow` → Leaf Bow, `dbow` → Doom Bow, `lean crown` → Chrysalis of Eternity (`COMMUNITY_ALIASES`). Enchant extraction only consults this map, not the hub catalog.
- **Always-mention rings** (`TOP_RINGS`): every ring brief names Kagenohikari and Snake Eye Ring with Chrysalis of Eternity, The Forgotten Crown, and The Twilight Gemstone *after* the ranked table (so the set visualizer still picks T7 first, not Kage as the only ring). Kage and Snake Eye are usually missing from RealmEye / Umi / RealmShark unless a top-5 set happens to wear them.
- **Closed-vocab typos** (`api/services/fuzzy_match.py`): unique 1-edit on classes (`brd` → Bard), dungeon names (`moonlite` / `shaters`), and nickname keys. Ability-slot nouns stay exact so `spel` does not become Wizard.
- **Multi-item enchant/DPS extract** (`extract_mentioned_items`): `cbow` vs `lbow` (and `awakening` as an enchant cue) resolves both Coral Bow and Leaf Bow. Enchant-only turns with 2+ nicknames also route the DPS slot.
- **RealmShark set-visualizer picks** (`shark_slot_picks` / `picks_from_loadouts`): majority item per slot across the top 5, Limited Edition reskins skipped, then the player overlay still wins.
- **Class wiki Maximum Achievable Stats** (`scrape_class_max_stats`, cache `wiki:class-maxstats:v1:{class}`): warmed with class abilities, injected cache-only into build context, labeled as a max-stat stack ranked last.

### Changed
- **Paywall demo videos play on mobile** (`web/public/staticwebapp.config.json`, `PaywallModal`, remuxed MP4s): production was serving `/videos/paywall/*.mp4` as `application/octet-stream` with `X-Content-Type-Options: nosniff`, so Safari and other phones refused to treat the files as video. SWA now maps `.mp4` to `video/mp4`. Both Clipchamp exports also had `moov` after `mdat`, so the player could not start until the whole file arrived; they are remuxed with `-movflags +faststart`. The player uses a `type="video/mp4"` source and `preload="metadata"`.
- **Class progression briefs** (`api/services/progression.py`): "best early/mid/end game items for {class}" (and "X progression") is a stored three-band farm route with `[item:]` cards. Sorcerer is the hand-verified ratchet (Mad Lab / Cemetery / Snake Pit, Parasite + Cnidarian + Draconis, MV / O3 / Shadows). Other classes keep the same shape but use that family's dungeons and store cores (bows get Coral / Leaf / Maka + leather, staves get Unholy + Water Dragon Silk, and so on). Generic T0–T6 Nexus copy only remains when no class is named. Claude does not mint over these.
- **Ability asks mint and replay** (`maybe_mint_brief`, `_ability_reply`, `chat.py` `_mint`): "Best druid abilities" has a class and the word ability, but no stat, so it never wrote `wiki:build:v1:{class}:{stat}`. Haiku replies were also skipped (`model != claude_model`). Live Sep 16: the same guest ask burned two in-depth turns. Class-only ability essays now store at `wiki:ability-brief:v1:{class}` (or `:{stat}` when named). The second identical ask is a stored hit. Haiku and Sonnet both mint. Constrained / dungeon / enchant asks still do not.
- **Slot lists rank Umi + RealmShark, not hub T0 order** (`stored_answers._slot_reply`, `community_knowledge.rank_community_slot_names`, `realmshark.shark_name_counts`): "Best bows in the game" took the first six `wiki:hub-index:v8:bows` rows (Shortbow, Reinforced Bow, ...). RealmEye hubs are T0-first. Lists now seed family cores (Makakoyumi / Divinity+Damnation / robe+leather cores / TOP_RINGS), then cached RealmShark top-5 frequency, then UmiEnjoyers BIS names. Same path for swords, armor, rings, and other mapped slots. "Best equipment/gear/items for {stat}" (no class) aims to maximize that stat. Class+stat asks still defer to the build brief.
- **Stored build briefs only match this turn's class+stat** (`stored_answers._build_reply`, `maybe_mint_brief`): `parse_query(..., history=...)` used to inherit Huntress/Dexterity (and `buildish`) from earlier turns, so an LLM-bound follow-up after a minted `wiki:build:v1:huntress:dexterity` brief streamed that same loadout instead of falling through to `_enforce_quota`. Live Sep 16 prod: a guest at 0 in-depth left sent a Claude-activating test prompt and got the prior Dexterity Huntress essay. Briefs now parse this message only. Asking the same class+stat again is still a cache hit. History inheritance stays on the Claude path for thin follow-ups.
- **Guest Register opens the paywall signup slide** (`AccountMenu`, `PaywallModal` `reason=create_account`): the guest profile Register item used to `router.push("/auth/signin?mode=register")`, which left chat and did not show a modal. It now opens the same create-account slide as paywall step 3, prefills the sidebar IGN, and writes the IGN to account profile storage before and after `registerAccount` so the pet restore survives the auth-changed event.
- **Composer footer attribution moved to About** (`AccountMenu`): "Data via realmeye.com..." no longer sits under the message box. Account menu About (guest and signed-in) opens a small modal with RealmEye, RealmShark, UmiEnjoyers, and the DECA disclaimer.
- **Tab icon is the sword, then the saved pet** (`GET /sprite/crop`, `TabIcon.tsx`): default Next.js triangle `favicon.ico` replaced with `public/sprites/sword.png`. After a pet lookup, the tab icon points at a cropped PNG from the API (RealmEye sheets have no CORS, so an in-browser canvas crop stays tainted and never swaps). Account profile restore is case-insensitive, writes a last-used backup so JWT padding misses still reload the IGN/pet, and a silent pet refetch no longer wipes a cached pet.
- **Production Stripe webhook** (`STRIPE_WEBHOOK_SECRET` on `realmpal-api`): Checkout already returned through `/payments/confirm`, but cancel / past_due never reached the API because no webhook endpoint existed and the Container App had no signing secret. `GET /payments/webhook` is now registered in the test-mode Stripe account for the production Container App URL. Live mode is still a separate dashboard toggle plus `sk_live_` key.
- **Paywall demo videos** (`web/components/chat/PaywallModal.tsx`): first two slides play `/videos/paywall/set-building-demo.mp4` and `/videos/paywall/visualizer.mp4`. Slide 1 autoplays on open. Slide 2 pauses slide 1 if it is still playing and autoplays the visualizer once. Finished videos do not replay. Video slides use `max-w-3xl` and `object-cover`; signup/pricing stay `max-w-sm`.
- **Named set visualizer uses catalog slot kinds and RealmEye URLs** (`item_aliases.retrieve_set_visualizer`, `chat.py`): Crown aliases to The Forgotten Crown; leftover "all" after a comma list is stripped; tokens order by real catalog slot (weapon/ability/armor/ring) not list order; each item gets a hub kind (Warmonger is a bow) plus RealmEye wiki URL. Chat no longer stamps the RealmShark leaderboard citation on set, skin, dungeon, player, or enchant turns.
- **User-facing copy says overall, not overlay** (`community_knowledge.py`, `wiki_scaling.py`, `rag.py`, `slot_graph.py`, `realmshark.py`): Claude was copying "Player overlay" into leftover Why columns (Attack Bard Vesture). Prompt strings now say Overall / overall pick. `_first_visualizer_item` still skips those core lines (legacy "Player overlay" prefix too). System prompt: never say overlay to the user.
- **Family cores in briefs and Umi prompt**: `retrieve_weapon_brief` / `retrieve_armor_brief` / `retrieve_ability_brief` prepend `weapon_core_note` / `armor_core_note` / `ability_source_note`. `retrieve_umi_bis()` now names Vesture, Diplomatic, and Flowering Kimono as the robe base (Kimono is not only an honorable mention). Ring briefs always include Snake Eye Ring with Kage / Lean / Crown / Gemstone.
- **`retrieve_umi_bis()` prompt** no longer calls RealmEye the source of truth. Matches the ranking above. Attack robe classes: Diplomatic Robe and Vesture of Duality, Flowering Kimono as honorable mention.
- **Anonymous stored answers no longer spend the daily guest quota** (`api/routers/chat.py`): the stored-hit branch used to call `_enforce_quota()` only for `quota.is_anonymous` so guests would hit the sign-in wall after 3 no-model replies. Guest, free, and Pro now all skip the meter when the turn never calls Claude. A real Claude turn still consumes. A guest who already spent their Claude turns can still get stored replies.
- **Claude uses the same store ranking as stored answers** (`api/services/rag.py`, `store_ranking_brief`): in-depth model turns were still told RealmEye hub tables were the source of truth. System prompt + injected chunk now rank RealmShark first, then the player overlay, Umi in synergy, class-page max-stats last. Weapon/armor briefs prepend overlay picks (Attack Bard Triangle + Vesture).
- **In-depth Claude builds use slot agents instead of the wiki dump** (`retrieve_build_knowledge`): generic class+stat turns now call `run_slot_agents` (weapon / ability / armor / ring / enchantment), then compact extras from `top_build_items` (SET VISUALIZER PICKS), UmiEnjoyers general-tab BIS as the **only** source for weapon/ability/armor/ring alternatives (`slot_alternatives_note` + `retrieve_umi_bis` cache-only), and one matching RealmShark top-5 table (`format_loadouts`). Attack robe classes always name Diplomatic Robe and Vesture of Duality (Kimono honorable); T7 robes are dropped from armor hub lists. Attack Bard overlay puts The Triangle on **ability**, not weapon. Skips extra wiki RAG on those turns. Infer the class primary stat before the fan-out so "best kensei build" still gets Dexterity enchants.
- **Umi BIS scraper reads every build tab** (`scrape_umi_bis`): Umi pages hide gear behind `?tab=speed-wizard` / `?tab=attack-wizard` / `?tab=general`. The old scrape only opened general and took `inner_text` of `main` before the panel hydrated. Now it follows each `?tab=` link (and `[role=tab]` labels), clicks if needed, waits for "Main build", and stores labeled sections in `umi:bis:v2:`. Claude prefers the tab matching the asked stat.
- **Warm/refresh CLI uses the same Redis prefix as the API** (`api/scripts/warm_specialists.py`, `refresh_wiki.py`): wrap with `namespaced(..., settings.redis_key_prefix)`. `warm_specialists --drop-briefs` deletes minted `wiki:build:v1:*` essays so the next in-depth ask regenerates.
- **Guest/free counter copy** (`web/lib/usageCopy.ts`): "in-depth responses" (only Claude turns spend this). Paywall and 402 copy match.
- **Chat burst limiter** (`chat_burst_quota_for`, `_enforce_chat_burst`): every `/chat/stream` turn, including stored answers, counts against a 60s window (20/min guest, 60/min signed-in). 429 when exceeded. Separate Redis key from the daily in-depth quota and from lookup scrape limits.
- **In-depth paywall on every spent in-depth try** (`web/components/chat/ChatInterface.tsx`): a 402 for the daily free quota opens the paywall every time, not only the first time in the window. The user message stays. Leftover suggestions still pin above the input (guest: create an account; signed-in: RealmPal Pro). Same chevron as the sidebar hides the strip until the quota refreshes.
- **Skin follow-ups stay on the stored visualizer** (`is_skin_visualize_query`, `route_slots`, `retrieve_build_knowledge`): history plus "and ... too" / a named cloth or dye (e.g. "And small sentinel cloth too") is the same outfit turn. Does not inherit a class+stat build or spend Claude.
- **Player lookups are stored, not Claude** (`try_stored_reply` `_player_reply`): `Look up player X` scrapes/caches the RealmEye row and streams the fact bullets. No daily in-depth spend. After the cap this still 200s instead of 402.

### Tests
- `test_static_web_app_serves_mp4_as_video`
- `test_paywall_mp4s_are_faststart`
- `test_paywall_player_declares_mp4_type`
- `test_community_nicknames_for_bows_and_triangle`
- `test_extract_mentioned_items_returns_cbow_and_lbow`
- `test_one_letter_class_typo_still_resolves`
- `test_one_letter_dungeon_typos_still_match_the_index`
- `test_enchant_comparison_of_two_nicknames_also_routes_dps`
- `test_retrieve_enchanting_brief_compares_cbow_and_lbow`
- `test_top_build_items_attack_bard_uses_player_overlay`
- `test_top_build_items_shark_majority_then_overlay`
- `test_picks_from_loadouts_majority_skips_limited_edition`
- `test_class_max_stats_table_is_a_candidate_list_not_bis`
- `test_weapon_brief_names_doom_bow_upgrade`
- `test_drop_question_never_hits_the_llm` now asserts `peek() == 0`
- `test_anonymous_at_daily_limit_still_gets_stored_answer`
- `test_anonymous_claude_turn_still_spends_daily_quota`
- `test_system_prompt_ranks_realmshark_first`
- `test_store_ranking_brief_attack_bard_names_triangle`
- `test_in_depth_build_uses_slot_agents_set_picks_and_one_shark_top5`
- `test_armor_brief_attack_robes_name_vesture_not_t7`
- `test_umi_bis_url_uses_speed_wizard_tab`
- `test_parse_umi_tab_links_keeps_build_tabs_not_class_nav`
- `test_retrieve_umi_bis_prefers_matching_stat_tab`
- `test_stored_answers_are_burst_limited_even_after_daily_in_depth_is_spent`
- `test_claude_turn_at_daily_limit_still_returns_402`
- `test_cached_build_does_not_resurface_on_an_unrelated_follow_up`
- `test_guest_at_limit_gets_paywall_not_a_prior_build_brief`
- `test_best_bows_uses_cores_not_hub_t0`
- `test_best_swords_and_rings_use_community_cores`
- `test_best_equipment_for_dexterity_aims_at_that_stat`
- `test_best_items_for_dex_huntress_is_not_a_slot_list`
- `test_ability_ask_matches_best_druid_abilities_not_a_full_build`
- `test_second_druid_ability_ask_uses_the_minted_brief`
- `test_second_druid_ability_stream_does_not_call_claude`
- `test_parse_progression_query_needs_class_and_band_words`
- `test_sorcerer_progression_uses_the_verified_route`
- `test_huntress_progression_is_bows_not_scepters`
- `test_stored_sorcerer_early_game_skips_generic_t6_blurb`
- `test_rank_community_slot_names_cores_beat_hub_order`
- `test_chat_burst_bucket_is_not_daily_quota_or_lookup`
- `test_followup_and_small_sentinel_cloth_too_is_skin_query`
- `test_skin_followup_with_history_routes_to_skin_agent`
- `test_player_lookup_at_daily_limit_is_stored_not_claude`
- `test_store_ranking_brief_weapon_family_and_leather_cores`
- `test_community_nicknames_for_bows_and_triangle` also asserts enforcer / valor / tarnished / snake ring
- `test_store_ranking_brief_unique_without_community_uses_max_stats`
- `test_store_ranking_brief_unique_with_umi_keeps_community_first`
- `test_class_max_stats_unique_without_community_is_priority`
- `test_umi_has_matching_stat_tab_ignores_general`
- `test_overlay_slot_picks_kensei_dex_uses_tools_and_fungal`
- `test_trailing_all_shiny_divine_does_not_stick_to_crown`
- `test_named_bard_set_uses_realmeye_bow_kind_and_forgotten_crown`
- `test_sprite_crop_endpoint_returns_png`
- `test_sprite_crop_rejects_unknown_host`

### History
#### Until Sep 16, 2026 (tab icon, unshipped)
Tab icon used a client canvas crop with `crossOrigin=anonymous`. RealmEye taints that canvas, so `toDataURL` failed and the tab stayed on the sword after a pet was set.

#### Until Sep 16, 2026 (1:20 PM)
Source ranking treated Maximum Achievable Stats as last for every class+stat. Unique Dex/Vit Samurai and Kensei did not overlay Tools of the Tarnished + Fungal Breastplate. Heavy armor had no forced list.

#### Until Sep 16, 2026 (1:15 PM)
`TOP_RINGS` was Chrysalis of Eternity, The Forgotten Crown, The Twilight Gemstone, and Kagenohikari (no Snake Eye Ring). Attack robe copy treated Flowering Kimono as an honorable mention next to Diplomatic Robe and Vesture of Duality, not a robe base. Weapon family cores (katanas Enforcer / Valor / Tools of the Tarnished, and the other slot bases) were not in the overlay.

#### Until Sep 16, 2026 (same day, unshipped)
The in-depth paywall opened only on the first daily 402; later spent in-depth tries kept leftover suggestions above the input without the modal. Guest/free UI copy said "AI-powered responses", then "in-depth prompts". Generic Claude builds dumped `format_graph`, up to 4 RealmShark boards, stored wiki scaling, the armor hub, the full Umi page, class max-stats, and the enchant brief, plus extra wiki RAG. Later the same day, leftover suggestions after a 402 were injected as an assistant bubble in the transcript (which split them from player character cards). Player lookups skipped the stored path (`try_stored_reply` returned None whenever `extract_player_ign` matched) and 402'd after the in-depth cap even though the frontend scrape still attached a card. Skin follow-ups like "And small sentinel cloth too" were not classified as the same visualize turn, so they spent Sonnet.

---



### Changed
- **Mobile sidebar suggestions start collapsed** (`web/components/chat/ChatInterface.tsx`): on viewports below `md`, the sidebar example prompts default hidden. `realm_pal_suggestions_hidden` still stores an explicit hide (`1`) or show (`0`) so a later session reuses that choice on any device. No stored key: phones stay collapsed, desktop stays open.
- **New chat control above the chat list** (`web/components/chat/ChatSidebar.tsx`): a filled, centered "New chat" control with a plus icon on the left (same border as the IGN field, fill `#3a3a3a` so it reads lighter than the `#262626` inputs) sits above an always-visible `Chats` label and calls `goHome`. Disabled while already on an empty landing.
- **IGN field label** (`web/components/chat/ChatSidebar.tsx`): "Your IGN" is now "Find your pet by entering your IGN".
- **Compact pet lookup for sidebar IGN** (`GET /players/{username}/pet`, `scrape_player_pet()`): sidebar "Find your pet" now opens only the RealmEye Pet Yard tab (via `_read_top_pet_from_page`), skips characters/exaltations/summary scraping, caches under `player:pet:v1:`, and hard-caps at 20s with `Sorry, I wasn't able to find a pet. Please try again later.` when the tab is missing, empty, or slow. Full profile scrape (`GET /players/{username}`) is unchanged for chat player cards and explicit lookups.
- **Chat no longer scrapes full player profile on every message** (`api/routers/chat.py`): removed the unconditional `body.ign` → `get_or_scrape_player()` block; full profiles are fetched only when the user asks about a player in chat (frontend `fetchPlayer` on lookup patterns) or via the player endpoint directly.

### Fixed
- **A "Look up player X" chat turn could silently drop the Characters card** (`web/components/chat/ChatInterface.tsx`, `MessageBubble.tsx`). Reported live Sep 15: asking to look up the same player twice in one session showed the rich card (portraits, gear, PlayerSummary bullets) the first time, but the second time showed only Claude's raw text bullets with no card at all, no error, nothing. Root cause: two independent code paths scrape the same player on the same turn and race for the single shared Playwright browser - the backend's `_player_agent` (`api/services/slot_graph.py`, feeds the text summary Claude copies verbatim) and the frontend's own `fetchPlayer()` call (populates `playerProfile`, which is what actually renders `PlayerCard`/`PlayerSummary` and strips the raw text bullets via `stripRestatedPlayerSummary`). Both read/write the same `player:profile:v3:` Redis key with the same ~120s TTL (`PLAYER_SCRAPE_TTL_SECONDS`), so this is normally a fast cache hit for whichever one runs second - but when the frontend's request lost the race and the shared browser was still busy, its `fetchPlayer()` call rejected and the `.catch(() => {})` swallowed it entirely, leaving `playerProfile` unset (so the raw, unstripped brief text rendered instead, with no card, no heading, no error). Added one delayed retry (2.5s, enough time for the backend's own scrape to finish and cache) before giving up; a still-visible fallback (`playerLookupFailed`) now shows "Couldn't load the character card for this lookup. Ask again to retry." instead of failing silently.
  - This is a symptom of the known single-Chromium-semaphore contention noted in `BACKLOG.md`; the retry reduces how often it's user-visible but does not remove the underlying serialization.
- **Confirmed (not a bug): player lookups are not stale.** `MAX_PLAYER_CACHE_SECONDS` caps every player cache entry (chat card and the `_player_agent` brief) at 15 minutes, and the actual configured TTL is 120s (`PLAYER_SCRAPE_TTL_SECONDS=120`) - just long enough that the two same-turn scrapes above share one RealmEye fetch instead of paying for it twice. Any lookup more than 2 minutes after the last one re-scrapes live. Recorded cost for a player-only lookup: **$0.0138**/message (`docs/chat-quality-benchmarks.md`, "Look up player Turbine" row), well under the ~$0.04 ceiling discussed for this feature.
- **A shiny-only (no "divine") comma-separated item list with no explicit "set"/"loadout"/"visualize" verb fell through to generic chat instead of the set visualizer** (`api/services/item_aliases.py`'s `is_set_visualize_query`). Found live Sep 15: "Rare Shiny bogwood croak, rare shiny genesis spell, rare diplomatic robe, shiny rare, the twilight gemstone" (a literal 4-item loadout, only "shiny," no "divine," no intent verb) got `{context: ""}`'d and answered "I don't have the item data for those specific items in my current context." `is_set_visualize_query` previously required `("set"|"loadout"|"build me"|"show me"|"visualize"|"equip(ped)")` OR both shiny AND divine together before it would trust a shiny-only or divine-only item list - `extract_set_item_names` already succeeding (finding a shiny/divine trigger word immediately followed by 2+ clean 3-60 char comma-separated names) is itself sufficient signal; dropped the extra verb/both-flags requirement and removed the now-unused `_SET_INTENT` regex.
- **Same bug, second half: a stray comma could split a bare rarity word off its own item and silently displace a real item from the result** (`api/services/item_aliases.py`'s `extract_set_item_names`). In the message above, "...rare diplomatic robe, shiny rare, the twilight gemstone" splits into a bare `"rare"` segment once `"shiny"` is stripped - that 4-character token passed the `3 <= len <= 60` check and consumed one of the 4 `SET_SLOT_COUNT` slots, pushing "the twilight gemstone" (the actual ring) out of the returned list entirely. Added `_BARE_QUALITY_WORDS` (`rare`/`epic`/`legendary`/`mythic`/`godly`/`common`/`uncommon`/`fabled`) and skip any comma-split segment that, after stripping shiny/divine, is nothing but one of those words.
  - Tests: `test_shiny_only_item_list_with_no_set_intent_verb_routes_to_set_visualizer` (`api/tests/test_item_aliases.py`)
- **Rarity words other than shiny/divine stayed glued to the item name and broke resolution, and misspelled item names failed outright** (`api/services/item_aliases.py`). Found live Sep 15 testing the fix above: "rare genesis spell" and "rare diplomatic robe" kept their "rare" prefix (only `_SHINY_DIVINE_WORDS` stripped shiny/divine; a fully-bare "rare" segment was dropped, but "rare" glued to a real name was not), so neither resolved against the catalog ("Genesis Spell"/"Diplomatic Robe" have no "rare" in their wiki titles). Separately, the user intentionally misspelled "Bogwood Crook" as "bogwood croak" (one substituted letter) to test resilience, and `score_nickname` had no typo tolerance at all - it failed to resolve, so the set visualizer asked for clarification on all three malformed names instead of rendering. Two fixes:
  - Added `_QUALITY_WORDS_RE` (same word list as `_BARE_QUALITY_WORDS`: rare/epic/legendary/mythic/godly/common/uncommon/fabled) to strip these words from anywhere inside a comma-split segment, not just when the whole segment is nothing else.
  - Added `_levenshtein`/`_fuzzy_word_match` (plain Python edit-distance, no new dependency) and wired it into `score_nickname`'s exact-token branch: a single-letter typo on a 4+ letter word (length delta ≤1, ≤1 edit for words ≤7 chars, ≤2 for longer) now scores the same high tier as an exact token match, clearing `resolve_against_catalog`'s 40-point cutoff. Gated to 4+ letter words so short coincidental collisions (e.g. "org" vs "orb") don't misfire.
  - Tests: `test_rarity_word_stripped_from_inside_a_segment_not_just_when_bare`, `test_single_letter_typo_still_resolves_to_the_real_item`, `test_short_word_typos_do_not_fuzzy_match_unrelated_items` (`api/tests/test_item_aliases.py`)

### History
#### Until Sep 15, 2026 (later same day)
Compact pet lookup timeout (`PET_LOOKUP_TIMEOUT_SECONDS`, `PET_LOOKUP_TIMEOUT_MS`) was 10s. Raised to 20s the same day after production testing showed 10s was too tight for a cold (uncached) Pet Yard load.

## [2026.09.14] - Sep 14, 2026

### Fixed
- **Embeddings backend was unreachable in production, silently breaking all RAG** (`api/services/embeddings.py`). `EMBEDDING_BACKEND` defaulted to `"ollama"` pointing at `OLLAMA_URL=http://localhost:11434`, but no Ollama server exists on the Container App - every embed call threw `httpx`'s generic `All connection attempts failed`, caught by a broad `except Exception` in `api/routers/chat.py` and logged as "RAG context retrieval failed, answering without retrieved context". Every non-specialist chat reply was running with zero retrieved wiki context, silently, since the app's first production deploy.
  - **Decision: Voyage AI over self-hosted Ollama.** Self-hosting `nomic-embed-text` on Container Apps would need to stay warm 24/7 (chat needs embeddings synchronously, no scale-to-zero), realistically ~$25-70/mo. Voyage's `voyage-4-lite` is free for this project's scale (200M free tokens, one-time grant, never expires) and needs zero infra.
  - Fixed a real bug in the switch-over code itself: it called `voyage-3-lite` (fixed 512 dims, predates Voyage's free-token grant) and wrongly assumed 768-dim compatibility with Ollama. Switched to `voyage-4-lite` (1024 dims by default, covered by the free grant) and made `VECTOR_SIZE` derive from the active backend instead of a hardcoded `768` duplicated across `embeddings.py` and `ingestion.py`.
  - Both the local Qdrant Cloud collection (`realm_pal`, used for local dev/testing) and the production one (`realm_pal_prod`, namespaced via `DEPLOYMENT_NAMESPACE=prod`) were seeded with Ollama's 768-dim vectors. Deleted both (confirmed empty/reproducible-from-source before deleting) and re-seeded from scratch with Voyage: `python -m api.scripts.seed_wiki` (39 wiki hubs) and `python -m api.scripts.seed_dps` (36 RealmShark DPS builds), landing 513 points in `realm_pal_prod` at 1024 dims.
  - Hit Voyage's free-tier rate limit (3 RPM) mid-seed; adding a payment method unlocked Tier 1 (2,000 RPM) without spending past the free grant (confirmed: `$0.00` monthly spend after re-seeding + a manual 5-call rate-limit probe, all instant with no 429s).
  - Verified with a real semantic query post-re-seed (`"how to do moonlight village"` embedded via `voyage-4-lite`, searched against the fresh collection) - returned sensible top-3 matches from the wiki hub content (Helms/Morning Stars/Skulls, all real item-category pages), confirming the vector space is coherent, not garbage.
  - Set `EMBEDDING_BACKEND=voyage` + `VOYAGE_API_KEY` as Container App environment variables (new revision `realmpal-api--0000011`).
- **Dungeon guide specialist did not recognize "how to do X" phrasing** (`api/services/dungeon_guide.py`'s `_GUIDE_RE`). This turned out to be the *real* root cause of last night's "I don't have dungeon guide data... in the context provided" replies for "How to do moonlight village?" and "Battle for the Nexus" - a same-day BACKLOG.md note had guessed this was downstream of the embeddings bug above, but that guess was wrong: `dungeon_guide.py` never touches Qdrant/embeddings at all, it's pure regex + token-overlap matching against a Redis-cached scrape of RealmEye's dungeon indexes. The actual bug was narrower and simpler - `_GUIDE_RE` only recognized `complete`/`beat`/`clear`/`finish` as guide-request verbs after "how to"/"how do i", so "how **to do** X" (arguably the single most common phrasing for this) fell through to generic chat every time, which then answered from Claude's own general knowledge with a self-written hedge disclaimer instead of the real scraped wiki page. Added `do`/`run`/`solo` to the recognized verb list. Verified live post-deploy: both previously-failing phrasings now log `Chat served from stored answer {kind: 'guide', ...}` and return grounded, wiki-sourced content.
  - Tests: `test_extract_dungeon_query_recognizes_how_to_do_phrasing`, `test_extract_dungeon_query_recognizes_run_and_solo_phrasing`, `test_extract_dungeon_query_still_recognizes_original_verbs` (`api/tests/test_dungeon_guide.py`)
- **Skin/outfit visualizer scraper timed out on a permanently zero-height container** (`api/services/scraper.py`'s `_open_outfit_page`). `_goto_with_retry(..., ready_selector=".chooser-table, #class")` waited for either selector to become Playwright-`visible` (non-empty bounding box) before proceeding. Live DOM inspection of `realmeye.com/top-characters-with-outfit` found `.chooser-table` has a permanent zero-height box (a CSS layout quirk, not a transient loading state - its child buttons render fine, the container itself just collapses), and since a comma-OR selector deterministically locks onto whichever matches first in DOM order, every call locked onto the broken element and timed out twice at 20s each, 100% failure rate, fully breaking the "what does skin X look like with clothing Y" feature. `#class` (the "Choose a class" button) is a real always-visible element already used as the actual data-readiness signal one line later (`_OUTFIT_SCRIPTS_READY_JS` checks `window.classInfos`/`items`/`sheetOffsets`/`drawCharacters`), so the selector wait only needs to confirm we're past Cloudflare's interstitial - dropped `.chooser-table` from it. Verified against live RealmEye: `scrape_outfit_catalog()` now returns in under 10s with 19 classes; confirmed the specific failing report (Vampire Slayer Archer, skin id 30920) is a real skin name, this was purely the scraper bug.
- **`extractItemNames()` treated Claude's generic wiki-referral fallback text as real item/dungeon names** (`web/lib/itemLookup.ts`), e.g. `[RealmEye wiki dungeon page](.../wiki/realmeye-wiki-dungeon-page)` - a symptom of the embeddings bug above (Claude falls back to this phrasing more when it has no retrieved context to cite). This fired a doomed `fetchItem()` for a name that could never exist, burning 15-30s of the single shared Playwright semaphore per occurrence and worsening scrape contention for every concurrent user. Filtered out generic referral words (`wiki`/`page`/`guide`/`directly`/`article`) since no real item/dungeon/set name contains them.
  - Commits: `9ceb1de` (fix), `b2ee73a` (dungeon guide regex), `b524cc7` (skin visualizer) on `dev`, all in [PR #9](https://github.com/kylezwang/RealmPal/pull/9) (`dev` → `master`)
- **Skin name corrections without cloth/dye keywords fell to real Claude calls** (`api/services/skin_visualizer.py`). "Sorry I mean Mini Royal Crossbowman Archer" mentions no cloth/dye/clothing/accessory keyword, so `is_skin_visualize_query()` never recognized it as an outfit follow-up, and `_extract_outfit_from_text()`'s fallback then stuffed the whole sentence into the clothing field. Added a `_CORRECTION_CUE` recognizer ("sorry i mean" / "i meant" / "actually i mean" / "no i mean" / "meant to say"), stripped before extraction, that both routes the message to the specialist and keeps the real skin name clean. Recorded the live production trace in `docs/chat-quality-benchmarks.md` before fixing.
- **Single-item shiny-only or divine-only visualization fell through to Claude** (`api/services/stored_answers.py`). `_shiny_divine_item_name` only recognized "shiny divine X" / "divine shiny X" together, so a plain "what does shiny X look like" (shiny and divine are independent flags in-game) never matched. Broadened the regex to match either alone and strip a trailing "look(s) like", added `_shiny_divine_flags()` to build `[loadout shiny]` / `[loadout divine]` / `[loadout shiny divine]` dynamically instead of hardcoding the combo.
- **Free/anonymous message quota reset 24h after each caller's own first message, not at a shared time** (`api/services/rate_limit.py`). `consume()` did `INCR` + `EXPIRE 86400` on a caller's first hit of the window, so two users got completely different reset times depending purely on when they happened to send their first message that day - reported live Sep 14 as confusing ("it should just reset at the same time every day"). Added `seconds_until_daily_reset()`: every free/anonymous quota now expires at the next 5pm Pacific (`America/Los_Angeles`, so it tracks PST/PDT automatically) instead of a flat 24h from first use. `daily_quests.claim_daily_bonus()`'s fallback TTL (used only when the quota key doesn't exist yet) now matches the same 5pm-Pacific instant instead of a flat 24h, so the quest bonus can't drift out of sync with the quota it boosts. Added `tzdata` to `requirements.txt` since `zoneinfo` needs an IANA database on disk and not every base image ships one.
  - Tests: `test_seconds_until_daily_reset_counts_down_to_5pm_pacific_same_day`, `test_seconds_until_daily_reset_rolls_to_tomorrow_once_past_5pm`, `test_seconds_until_daily_reset_exactly_at_5pm_rolls_to_tomorrow`, `test_seconds_until_daily_reset_is_timezone_independent_input` (`api/tests/test_rate_limit.py`)
- **`DEBUG_UNLIMITED_IGNS` (named test-account quota bypass) required `DEBUG=true`** (`api/config.py`, `api/services/dev_access.py`). Unlocking it in production meant also accepting `DEBUG`'s other side effects: a publicly exposed `/docs` Swagger UI (`docs_url="/docs" if settings.debug else None` in `api/main.py`) and muted JWT-secret/Anthropic-key rotation warnings at boot. Decoupled `Settings.debug_unlimited_ign_set` from `settings.debug` entirely - naming an IGN in `DEBUG_UNLIMITED_IGNS` is now sufficient on its own, in any environment.
  - Tests: `test_turbine_is_unlimited_regardless_of_debug`, `test_unnamed_ign_stays_metered_even_with_debug_off` (`api/tests/test_dev_access.py`)
- **Enchanting agent recommended Awakened Enchantments (e.g. Infernal Anger) as generic stat options** (`api/services/enchanting.py`). RealmEye's Awakened Enchantments table has no Eligible/slot column at all - unlike Basic/Unique enchants, each one only rolls on one or a few specific named items (Infernal Anger is exclusive to Berserker's Breastplate, not "any heavy armor"). `_normalize_row` defaulted the missing cell to `ALL`, so every awakened enchant looked generically eligible for any weapon/armor/ability/ring. Found live Sep 14: recommended for a generic "Attack Kensei" build with no connection to Berserker's Breastplate. Awakened rows now get a marker (`AWAKENED_ITEM_LOCKED`) that `_eligible_ok()` never treats as slot-generic, even when the caller doesn't know the slot yet (previously `not slot` short-circuited to "always allowed"). Also added an explicit instruction in the brief telling Claude not to invent awakened-enchant eligibility from its own training knowledge.
  - Tests: `test_awakened_row_without_eligible_cell_is_never_slot_generic`, `test_basic_enchant_row_missing_eligible_cell_still_defaults_to_all`, `test_awakened_enchant_excluded_from_a_generic_attack_build_query` (`api/tests/test_enchanting.py`)
- **Multi-item "full shiny divine A, B, C, and D" set requests fell to the single-item shiny/divine path** (`api/services/item_aliases.py`'s `extract_set_item_names`). This only matched a `with X, Y, Z` phrasing; a message like "Full shiny divine enforcer, ballistic star, straitjacket, and lean" (no "with") returned `[]`, so `stored_answers._shiny_divine_item_name`'s guard (`if extract_set_item_names(...): return None`) never tripped and the entire comma-separated list got swallowed as one bogus "item name," sent to RealmEye as a doomed wiki slug (`/wiki/enforcer,-ballistic-star,-straitjacket,-and-lean`), 404ing after two 15s scrape retries and leaving the set visualizer spinning indefinitely on the frontend. Added a fallback that captures the list directly after `shiny`/`divine` when there's no "with," but only treats it as a set when it actually splits into 2+ real names (a single name stays the single-item path's job).
  - Tests: `test_full_shiny_divine_list_without_with_is_recognized_as_a_set`, `test_single_item_shiny_request_is_not_treated_as_a_set`, `test_full_shiny_divine_list_without_with_routes_to_set_visualizer` (`api/tests/test_item_aliases.py`, new file)
- **A follow-up naming a specific item plus an unrelated question got served a stale cached build brief from several turns earlier, and also 404'd a bogus wiki scrape** - found live post-deploy asking "Shiny divine snake eye ring. Is it insane with the awakened enchantment?" right after a prior "Attack Ninja" build question in the same session; the response repeated the old Ninja/Attack answer verbatim, and the logs showed a doomed scrape of `/wiki/the-awakened-enchantment`. Three compounding bugs, all in the same request:
  - `item_aliases.extract_set_item_names`'s `>=2 names` sanity guard only applied to its `_AFTER_SHINY_DIVINE` fallback branch, not to `_WITH_ITEMS` itself - so "...insane **with** the awakened enchantment?" matched `_WITH_ITEMS` and returned a one-item list (`["the awakened enchantment"]`), which was then scraped as a literal wiki page (404). Applied the guard unconditionally.
  - `stored_answers._SHINY_DIVINE_ITEM`'s capture group was anchored to a bare `$`, so with no "look(s) like" tail to strip, it swallowed the *entire rest of the message* as the "item name" (a second sentence asking a real question, glued onto "snake eye ring"). That made `read_cached_item`/`resolve_item_query` miss, `_shiny_divine_item_name` return the garbled name instead of a clean one - the fix above already forced this function to return `None` for this message (deferring to `extract_set_item_names`'s now-empty result), but the regex itself was still wrong for any future case with a trailing sentence. Changed the capture to stop at the first `.`/`!`/`?`, " look(s) like", or end of string via a lookahead instead of consuming to `$`.
  - With both of the above still broken, this message fell through to `stored_answers._build_reply`, which calls `realmshark.parse_query(message, history=...)` - and that function inherits `class_name`/`stat` from *any* prior turn in history whenever the current message doesn't name its own class/stat. Since "ring" alone flips the module's `buildish` regex True (it's in the weak slot-noun list alongside armor/robe/weapon/ability), this message looked "buildish" purely from mentioning "ring," which was enough to pull `Ninja`/`Attack` in from several turns back and match `wiki:build:v1:ninja:attack` in the brief cache - a completely unrelated topic. `_build_reply` and `maybe_mint_brief` now both refuse outright when `is_enchant_query(message)` is true (enchant questions have their own specialist and must never be intercepted by, or overwrite, the generic class+stat build-brief cache).
  - The same `buildish`-instead-of-`(class_name and stat)` mistake for gating `enchant_only` existed independently in two more places that would have hit the identical failure mode even without the two bugs above: `api/routers/chat.py` (decides whether to skip RAG for the enchant specialist) and `api/services/realmshark.py`'s `retrieve_build_knowledge` (decides whether to inject the enchant brief vs. the DPS-graph context). Both now gate on `not (class_name and stat)` instead of `not buildish`, so a bare slot noun with no real class+stat pair no longer disqualifies the enchant-only path - only a genuine combined build+enchant ask (both class *and* stat present) still gets the full build context.
  - Tests: `test_with_phrasing_naming_only_one_item_is_not_a_set` (`api/tests/test_item_aliases.py`), `test_shiny_item_followed_by_a_new_sentence_stops_at_the_period`, `test_enchant_question_about_a_ring_does_not_reuse_a_cached_build_brief` (`api/tests/test_stored_answers.py`)
- **`realmshark.parse_query`'s history inheritance fixed at the root, not just patched at each call site.** The three edge-case gates above (`_build_reply`/`maybe_mint_brief`/`chat.py`/`retrieve_build_knowledge` all special-casing `is_enchant_query`) were symptom patches around a function that, whenever the *current* message lacked its own class/stat, still scanned backward through the *entire* history and glued in the first class/stat it found from however many turns back - which could just as easily misfire for a dungeon guide, a player lookup, or a skin/set visualization follow-up as for an enchant question, none of which were covered by the enchant-specific patches. Added `_has_own_topic()`: before inheriting, check whether the current message already matches one of the other specialist detectors this same file already imports for routing (`is_enchant_query`, `is_skin_visualize_query`, `is_set_visualize_query`, `extract_dungeon_query`, `extract_player_ign`) - if so, skip inheritance entirely, since the message is about something else regardless of whether it happens to also contain a weak slot noun. A thin, topic-less follow-up ("what other rings are good") still inherits normally. Resolves BACKLOG.md item 8.
  - Tests: `test_thin_build_followup_still_inherits_class_and_stat`, `test_enchant_question_does_not_inherit_stale_class_and_stat`, `test_dungeon_guide_followup_does_not_inherit_stale_class_and_stat`, `test_player_lookup_does_not_inherit_stale_class_and_stat`, `test_message_with_its_own_class_and_stat_ignores_history_entirely` (`api/tests/test_realmshark_parse_query.py`, new file)
- **The frontend had its own, unsynced copy of the "with A, B, C" set-name-extraction bug** (`web/lib/loadoutShowcase.ts`'s `extractNamedSetItems`) - fixed on the backend (`item_aliases.extract_set_item_names`) above, but this client-side duplicate (used to speculatively prefetch item cards while a message streams in) had the identical missing `>=2 names` guard. For "Shiny divine snake eye ring. Is it insane with the awakened enchantment?" this independently fired its own `GET /items/the awakened enchantment` in parallel with the chat request itself (visible in logs as an `OPTIONS`/scrape at the same timestamp as `/chat/stream`, well before the reply streamed back), regardless of what the backend's now-fixed reply contained. Added the same `>=2 names` guard.
- **A real item with no RealmEye wiki page yet re-paid a full ~30s scrape timeout on every single lookup** (`api/routers/items.py`, `api/routers/sprite.py`). Some correctly-named items (e.g. Rift Rippers, a RealmShark leaderboard entry that predates its own wiki page) will never resolve no matter how many times they're scraped, but a failed scrape was never remembered - every lookup paid the same two-attempt, ~15s-each Playwright timeout as the first. Added `api/services/wiki_scaling.mark_item_missing`/`is_item_marked_missing`: a scrape failure now writes a short-TTL (`Settings.missing_item_ttl_seconds`, default 1h) negative-cache entry, checked before scraping and skipped (no lookup quota charged) if present. Short TTL means the item starts resolving on its own within an hour or so of RealmEye actually publishing the page, rather than needing a manual cache-bust.
  - Tests: `test_scrape_failure_marks_the_item_missing`, `test_item_marked_missing_fails_fast_without_scraping_again` (`api/tests/test_item_slug.py`)

- **`_SHINY_DIVINE_ITEM` still over-captured when the item name and a follow-up question ran on as one sentence with no punctuation at all** (`api/services/stored_answers.py`). The same-day fix above stopped the capture at a sentence break (`.`/`!`/`?`) or "look(s) like," but found live again a few minutes later: "Shiny divine snake eye ring is the awakened enchantment good?" has no sentence break before the item name and its trailing question, they run on as one grammatical sentence ("...ring **is** the awakened enchantment good?"). Extended the stop-lookahead to also match a bare auxiliary/modal verb (`is`/`does`/`has`/`can`/`will`/`should`/`would`) as a whole word - no real item name contains one.
  - Tests: `test_shiny_item_with_no_sentence_break_stops_at_the_auxiliary_verb` (`api/tests/test_stored_answers.py`)
- **The sidebar's "Your IGN" field and pet companion never prefilled from the account's actual registered IGN on a browser that hadn't run the local signup flow.** `web/components/chat/ChatInterface.tsx`'s `applyAuthState()` only checked `loadSavedAccountProfile()` (a per-browser `localStorage` cache written once, during `PaywallModal.tsx`'s account-creation step, on whichever browser the account was created on) and left the field blank if that cache was empty - even though the account's IGN is registered server-side at signup and already travels in every JWT this account is issued (`api/routers/auth.py`'s `create_jwt({..., "ign": ...})`, already decoded elsewhere via `web/lib/api.ts`'s `decodeAuthIgn()` for the account-menu display, just never consulted here). Signing in on a different browser/device, or an account created before this local cache existed, showed a permanently blank IGN box and "No pet found yet." even though the account has a real registered IGN the whole time. Now falls back to `decodeAuthIgn()` when the local cache is empty, same account-not-browser fix pattern as the chat history sync above.
- **Durable fix for "item name glued to trailing free text" - `resolve_item_query_with_trim`** (`api/services/item_aliases.py`, `api/services/stored_answers.py`, `api/routers/items.py`). Found live Sep 14, repeatedly, across multiple distinct phrasings: any regex-based extractor that pulls an "item name" out of free chat text knows where the name *starts* but not reliably where a punctuation-less trailing question *ends* - "snake eye ring is the awakened enchantment good" kept getting handed to RealmEye as a literal wiki slug no matter how many specific stop-words (`.`/`!`/`?`, "look(s) like", then `is`/`does`/`has`/`can`/`will`/`should`/`would`) got added to `_SHINY_DIVINE_ITEM` one incident at a time - each fix closed one phrasing and left the next one open, and a production revision one fix behind `dev` reproduced the exact bug the auxiliary-verb fix (same day) had already closed in source.
  - Root fix instead of another regex iteration: real item names are a closed, known set (the item catalog already built from RealmEye's own hub/listing pages for nickname resolution). `resolve_item_query_with_trim()` retries a failed whole-string catalog match against progressively shorter prefixes (drop one trailing word at a time) before giving up, so "snake eye ring is the awakened enchantment good" resolves to "Snake Eye Ring" by testing "...good" → "...enchantment" → ... → "snake eye ring" (matches) without needing to know in advance which trailing words were never part of the name. `min_words=2` floor keeps a single incidental leading word (e.g. "ring") from producing a coincidental low-confidence match.
  - Wired into both places that previously fell back to the raw, unresolved name: `stored_answers._shiny_divine_reply` (so the chat reply itself embeds `[item:Snake Eye Ring]`, the correct title, not the garbled capture) and `routers/items.get_item` (the universal endpoint every item lookup goes through, including ones triggered by the frontend rendering `[item:...]` tokens from a chat reply) - the router is the real backstop, since it protects every caller, not just this one extractor.
  - Added `MAX_PLAUSIBLE_ITEM_NAME_WORDS = 6` (no real item name runs longer) as a final sanity ceiling: if trimming also finds nothing, a too-long candidate is rejected immediately (404, no lookup quota charged, no ~30s scrape timeout) instead of ever calling `scrape_item()` with obvious extraction garbage. A short, unresolved candidate still gets a live scrape attempt, since it may just be a real item not yet in the warmed catalog.
  - Tests: `test_trim_resolves_a_real_item_glued_to_a_trailing_question`, `test_trim_prefers_the_longest_resolving_prefix`, `test_trim_returns_none_when_no_prefix_resolves`, `test_trim_does_not_resolve_below_min_words` (`api/tests/test_item_aliases.py`); `test_shiny_divine_reply_resolves_a_still_glued_run_on_via_the_catalog`, `test_shiny_divine_reply_gives_up_cleanly_on_pure_extraction_garbage` (`api/tests/test_stored_answers.py`); `test_glued_free_text_resolves_via_catalog_trim_instead_of_scraping_garbage`, `test_implausibly_long_name_is_rejected_without_a_scrape_attempt` (`api/tests/test_item_slug.py`)
- **"Best shiny divine set for full dexterity huntress" was misread as an item name, sent to RealmEye as `/wiki/trigplanar`-style garbage** (`api/services/stored_answers.py`'s `_shiny_divine_item_name`). This is a build request ("a set FOR this class/stat"), not a single named item, but the "item/sprite/set/loadout" strip left "for full dexterity huntress" behind and nothing rejected it as a non-name - it got handed to `resolve_item_query`/`resolve_item_query_with_trim`, which found no catalog match (correctly, it's not an item), then fell through to a live scrape attempt since it was short enough to look like a plausible not-yet-catalogued item. Added a check: if the extracted "name" starts with a bare preposition/relative word (`for`/`on`/`to`/`that`/`which`/`who`), it's not a real item name (none start that way), so return `None` and let the message fall through to the general build-brief flow (`realmshark.parse_query`) that already understands "best build for a dex huntress."
- **"Shiny divine attack huntress" (no "for", no "set") still slipped past the fix directly above and scraped `/wiki/attack-huntress`** (`api/services/stored_answers.py`) - found live minutes later, in production logs, right after deploying the fix above: a bare `{stat} {class}` pair (or `{stat} {class} build`) has no preposition to catch and no "set"/"build" left behind to signal a build request, so it read as a plain two-word item name and paid the full two-attempt ~30s scrape timeout before 404ing (then correctly negative-cached, so it wouldn't repeat, but the user still got no answer). Added `_BUILD_VOCAB_WORDS`, built from the same `STAT_ALIASES`/`CLASS_ALIASES` dicts `api/models/build.py` already exports for the DPS-graph parser (covers nicknames too - "dex", "myst", "atk"): if *every* word left in the extracted name is stat or class vocabulary, it's a build reference, not an item (a real item name always has a connector word or a non-class/stat noun - "Ring of Decades", "Crown" - so this never over-rejects). Also added "build"/"gear" to the words stripped before the item name is judged.
  - Tests: `test_shiny_divine_bare_stat_and_class_is_not_treated_as_an_item` (`api/tests/test_stored_answers.py`)
- **"Show me full shiny divine attack huntress" (a class+stat build ask, no items named) rendered a wall of build-brief text instead of the shiny/divine item-circle loadout.** Once the two fixes directly above stopped "attack huntress" from being misread as a literal item name, the message correctly fell through - but landed on the generic weapon/ability/armor/ring balanced-loadout brief (`api/services/realmshark.py`'s RealmShark-graph tail), because the set-visualizer item-circle rendering only ever existed for explicitly-named sets ("full shiny divine Enforcer, Ballistic Star, Straitjacket, and Lean"), never for a class+stat ask with no items named. Added:
  - `wiki_scaling.top_build_items()`: the single best weapon/ability/armor/ring for a class+stat build, reusing the exact same ranking each text-brief slot agent already computes (`retrieve_weapon_brief`/`retrieve_ability_brief`/`retrieve_armor_brief`/`retrieve_universal_rings`) by asking each for its top pick and reading back the first `[item:...]` token, so this can never disagree with what the full brief already says about that slot. Weapon/armor ask for 2 picks (not 1): `_top_stat_items`' "always include a T7 baseline" rule can *replace* the actual top pick at `limit=1` instead of just appending it. Rings stay at `limit=1` since T7 is deliberately always the ring agent's first pick regardless of raw stat value (a guaranteed, always-available choice - the existing ring agent's own header text already says this).
  - `item_aliases.is_stat_class_shiny_divine_query()`: shiny/divine wording plus a resolved class+stat, but no items named directly (a real named set always wins).
  - `item_aliases.retrieve_set_visualizer()` now accepts a `stat` parameter and, when no items are named but this new detector fires, derives the 4 names from `top_build_items()` instead of returning empty.
  - Wired the detector everywhere the named-set check (`is_set_visualize_query`) already gated routing, so both paths render identically: `slot_graph.route_slots()` (picks the `set` agent), `realmshark.retrieve_build_knowledge()` (routes to `run_slot_agents` instead of the plain-text graph branch), and `routers/chat.py` (skips the redundant wiki RAG pass, same reasoning as a named set).
  - Tests: `test_top_build_items_picks_one_item_per_slot`, `test_top_build_items_skips_slots_with_no_data`, `test_build_knowledge_routes_shiny_divine_class_stat_to_set_visualizer` (`api/tests/test_wiki_scaling.py`); `test_stat_class_shiny_divine_query_needs_shiny_or_divine_and_no_named_items`, `test_retrieve_set_visualizer_derives_items_from_build_when_none_named`, `test_retrieve_set_visualizer_stays_empty_without_shiny_divine_wording` (`api/tests/test_item_aliases.py`); `test_named_shiny_divine_set_routes_to_set_agent_only`, `test_shiny_divine_class_stat_with_no_named_items_routes_to_set_agent`, `test_plain_build_ask_with_no_shiny_divine_wording_stays_on_gear_agents`, `test_shiny_divine_with_no_resolved_class_stat_does_not_force_set_agent` (`api/tests/test_slot_graph.py`, new file)

### Added
- **Server-side chat history sync for signed-in accounts** (`api/services/chat_sessions.py`, `api/routers/chat_sessions.py`, `web/lib/chatHistory.ts`). Chats lived only in browser `localStorage` (`realm_pal_sessions:{email}`), which an incognito window's storage teardown (on last-tab-close) wipes even though the signed-in account itself is untouched - reported live Sep 14 as "chats disappear after logging back in" in an incognito test. New `chat_sessions` table (SQLite/Postgres via `api/services/db.py`, same pattern as `entitlements`/`accounts`) makes the account, not the browser, the unit of persistence for signed-in users:
  - `GET /chat/sessions`, `PUT /chat/sessions/{id}`, `DELETE /chat/sessions/{id}`, `POST /chat/sessions/sync` (bulk upsert + merged read-back, used once right after sign-in).
  - Frontend pushes a session to the server (fire-and-forget, best-effort) at the same points it already saves to `localStorage`; on sign-in, `syncSessionsFromServer()` pushes anything local-only, merges in anything server-only (by `updatedAt`, newest wins), and writes the merged result back to `localStorage`.
  - Anonymous/guest sessions are untouched - still `localStorage`-only, since there's no email to key a server row on.
  - Capped at `Settings.chat_sessions_max_per_account` (default 200) per account; oldest sessions past the cap are dropped on write.
  - Fixed a latent bug in `api/dependencies.py`'s `require_user` while wiring this up: it 503'd whenever `Settings.auth_configured` was false, but that flag only reflects whether Entra JWKS verification is set up - the app actually launched on the local email+password JWT path instead (see BACKLOG.md item 6, Entra deprioritized), which `get_optional_user` already verifies independently. `require_user` was unused anywhere else, so this was previously a dead, latent 401-vs-503 mismatch rather than an active production bug.
  - Tests: `api/tests/test_chat_sessions.py` (10 tests: roundtrip, overwrite, per-account isolation, delete, ordering, bulk sync, cap enforcement, unknown email, router-level scoping and merge)

### Changed
- **Mobile web layout** (`web/components/chat/ChatInterface.tsx`, `web/components/chat/ChatSidebar.tsx`): phone browsers now use a Claude-style chat-first shell. The desktop account cluster (messages left / What's new / Quests / Sign in) no longer stretches across the top of the screen. A compact header exposes a top-left sidebar button; the existing sidebar (IGN, pet, chats, suggestions, quests, account) reopens as a full-screen overlay. The chat shell is `position: fixed` to `visualViewport` height (`--app-height` / `--app-offset`, `100svh` fallback) with `viewport-fit=cover` so the composer stays above Safari's bottom toolbar instead of sitting under it (`h-screen` / `100vh` previously included that chrome and forced a page scroll to reach the input).
- **Container App CPU/memory bumped 0.5 vCPU/1 GiB → 1.0 vCPU/2 GiB**: the single shared Playwright semaphore (`_PW_SEM = asyncio.Semaphore(1)` in `api/services/scraper.py`) was causing 16-40+ second pet/dungeon/skin lookups whenever specialist warming ran concurrently with a live request, on top of just being CPU-starved for a Chromium workload. New revision deployed with both this and the embeddings env vars above.

### Known issues (carried forward, not yet fixed)
- Every chat message unconditionally scrapes+ingests the signed-in user's own IGN profile even when the message has nothing to do with the player (`api/routers/chat.py`'s `if body.ign:` block) - see `BACKLOG.md`.

---

## [2026.09.13] - Sep 13, 2026

### Added
- **Account-scoped chat history** (`web/lib/chatHistory.ts`): Chats persist per email as `realm_pal_sessions:{email}` in localStorage
- **Daily quests system** (`api/routers/quests.py`): Rotating dungeon + player lookup + shiny-divine item, once per UTC day
  - Persistent per-user: `realm_pal_daily_quests:{email}` and `realm_pal_quest_shift:{email}` in Redis
  - Completion grants +1 message to free and paid via `POST /chat/quests/claim`
- **Pay-as-you-go billing** (`api/services/claude_billing.py`): Included pool of 68 Claude replies/mo (~$2.50), overage at $0.08/reply up to user-set spend cap
  - Durable entitlements store (`api/services/entitlements.py`): SQLite with Stripe webhook sync
  - New endpoints: `GET /payments/billing`, `POST /payments/on-demand`, `POST /payments/set-spending-cap`
- **Email+password authentication** (`POST /auth/signin`, `POST /auth/register`): Local SQLite accounts with PBKDF2-SHA256, fallback to magic-link
- **Stored answers** (`api/services/stored_answers.py`): Classify turn before Claude
  - Drops, best-slot hubs, early-game → warmed Redis
  - Build mints to `wiki:build:v1:{class}:{stat}` after first Sonnet reply
  - Dungeon guides from warmed wiki (no essay)
  - Shiny-divine items → cached item + no model call
  - Stored hits skip daily message meter for signed-in users
- **Card zoom** (`SpriteZoomTrigger`, `SpriteZoom.tsx`): Click sprites for inline popover; click cards for centered modal with full details
- **Top pet detection** (`_pick_top_pet` in `api/services/scraper.py`): Pick by highest RealmEye ability sum, not first slot
- **Sidebar chat ordering fix**: Chats stay in chronological position; only move to top when a new message is actually sent (not on selection)
- **Lookup rate limiting** (`api/services/rate_limit.py`): 12/min anon, 40/min signed-in on `/players`, `/items`, `/dungeons`, `/skins/render`, `/sprite`
- **Magic-link hardening**:
  - Separate `MAGIC_LINK_SECRET` from `JWT_SECRET`
  - Single-use enforcement via Redis `SET NX` with `jti` tracking
  - No link logging in info messages
  - Throttled `POST /payments/verify` and `POST /auth/request-link` under lookup rate limiter
- **CORS hardening** (`Settings.cors_allowed_origins`): Only `app_url` unless `DEBUG=true`
- **Secrets warnings** (`_warn_on_default_secrets`): Loud startup warning if `JWT_SECRET` or `PII_HASH_SECRET` unrotated in production
- **What's new changelog** (`web/lib/changelog.ts`, `ChangelogModal.tsx`):
  - User-facing UI with "What's new" button (dot badge while unseen)
  - First-load popup for new version
  - Wired to account settings page
  - `.cursor/rules/changelog.mdc`: ensures future deploys add user-facing entries
- **Enchantment specialist** (`api/services/enchanting.py`), wiring completed:
  - `api/services/specialist_warm.py`: `warm_enchanting_store` wired into `specialist_snapshot`, `missing_specialist_work`, `has_missing_work`, `warm_all_specialists`; `api/scripts/warm_specialists.py --status` prints "Enchanting rolls"
  - `api/services/realmshark.py` (`retrieve_build_knowledge`): enchant-only messages early-return `retrieve_enchanting_brief` directly (skips the weapon/ability/armor/ring fan-out); full "best {stat} {class}" builds get an Enchantments section appended via the same call
  - `api/routers/chat.py`: enchant-only turns skip the extra Qdrant wiki RAG pass and are excluded from the RealmShark DPS-leaderboard citation (same treatment as player-only turns)
  - **Implied-stat inference** (`api/services/wiki_scaling.py`): `infer_item_base_stat(item)` reads an item's own "On Equip" line (e.g. Cackling Straitjacket's `+20 ATT`) and returns the dominant stat via `_BONUS_PAT`, uncapped by the ring-tuned `_bonus_value` plausibility ceiling (T7 rings cap at +11; item base bonuses run higher). `infer_class_primary_stat(payload)` returns the stat most of a class's abilities scale with, from the cached wiki-scaling payload
    - `retrieve_enchanting_brief`: when no stat is named but an item resolves, look up the cached `ItemProfile`, infer the stat from its own base bonus, and note the inference in the returned text so Claude states it plainly instead of listing every stat's rolls unfiltered
    - `retrieve_build_knowledge`: when a full build names a class but no stat ("best kensei build"), infer the class's dominant scaling stat from `cached_class_wiki_scaling` instead of dropping the Enchantments section entirely
    - Both ties (two stats with equal bonus/ability count) return `None` and fall back to the prior unfiltered behavior rather than guessing
- **Entra External ID portal setup complete**: external tenant `RealmPal` (`RealmPal.onmicrosoft.com`), two single-tenant app registrations (`RealmPal API`, `RealmPal Web` as a public SPA client with PKCE, no client secret), user flow `sign-up-sign-in` collecting email only with email+password (not OTP, not magic link; Google deferred, known silent-renewal bug). `.env` now carries `ENTRA_TENANT_ID`, `ENTRA_WEB_CLIENT_ID`, `ENTRA_API_CLIENT_ID`, `AUTH_JWKS_URL`, `AUTH_ISSUER`, `AUTH_AUDIENCE`, `ENTRA_USER_FLOW`; `Settings().auth_configured` confirmed `True` against the live `.well-known/openid-configuration` response. Code integration (MSAL SPA sign-in, swapping local email+password) is separate follow-up work, not done yet
- **Stripe Customer Portal** (`api/routers/payments.py`, `api/services/entitlements.py`, `web/lib/api.ts`, `BillingModal.tsx`): found during a full checkout → webhook → entitlement audit that there was no self-service way for a paying customer to cancel or update their payment method, only a direct Stripe Dashboard edit by us. Added `POST /payments/portal` (opens a `stripe.billing_portal.Session` for the signed-in paid account's Stripe customer), `entitlements.get_stripe_customer_id(email)`, and a "Manage subscription or cancel" button on the paid plan card in `BillingModal.tsx`. Requires the Customer Portal to be enabled once in the Stripe Dashboard (Settings → Billing → Customer portal) before it works in production; Stripe returns a clear 503 otherwise
- **Production branch established**: `master` (already GitHub's default branch) is now the production branch; `dev` stays the active working branch for all day-to-day work. Fast-forwarded `master` up to `dev`'s tip (`1d76456`, 133 files, since `master` had drifted 6+ commits and many entire features behind `dev`). Added GitHub branch protection on `master`: pull request required before merging (0 required approvals since solo dev right now, but no direct push allowed at all, verified with a real push that got rejected), no force-pushes, no branch deletion, conversation resolution required, enforced for admins too so there's no back door. `dev` itself has no protection, stays free to push directly like before. Going forward: keep committing to `dev`, open a PR `dev` -> `master` when a batch of work is deploy-ready, merge it there (a CI status check can be required on that PR later once one exists)

### Changed
- **Pricing model**: Paid included pool reduced from 90 → 68 Claude replies (~$2.50 at $0.0365/reply)
  - Daily fuse reduced from 200 → 50 messages/day (`paid_message_limit`)
  - Updated `api/config.py`, `.env.example`, `README.md`, `BACKLOG.md`
  - Tests retargeted to assert pool exhaustion at 68, not 90
- **Sidebar quick-suggestion prompts**: Now collapsible via chevron button; state persisted in localStorage
- **Usage meter removal**: Removed old "0/90 Claude replies" chip from header/sidebar; replaced with daily quests progress bar
- **Account menu consolidation**: Billing and spending-limit modals consolidated into account menu
- **Stripe Checkout**: Added `payment_method_types=["card", "link"]` to both `api/routers/payments.py` and legacy `_checkout_url_for` in `api/routers/chat.py`
- **JWT verification**: Now signature-only; entitlements check separate (`entitlements.is_active`)
  - Revoked subscriptions denied even with valid JWT
  - Fails open for unknown emails (backward compat for pre-entitlements customers)

### Fixed
- **Stripe webhook silently dropped guest checkouts with no known email** (`api/routers/payments.py`, `_apply_stripe_event`): `checkout.session.completed` only checked `customer_email` (our own pre-fill, null once Stripe attaches a Customer object) and `metadata.email` (empty for a guest we had no email for at Checkout-session creation), never `customer_details.email` (what Stripe actually confirmed at checkout, always populated). A guest reaching checkout via the exhausted-quota flow with no known email, typing their own email straight into Stripe's page, would pay successfully and never get an entitlement row, paid with nothing to show for it, unless the client-side `/payments/confirm` return-path happened to also fire. Fixed to check `customer_details.email` first, matching the ordering `confirm_checkout` already used
  - Test: `test_payments.py::test_checkout_completed_falls_back_to_customer_details_email`
- **Lookup 429s on HMS guides**: `/items` no longer burns 12/min scrape window on warmed Redis hits
- **Item card fan-out**: Stored guide briefs strip `[item:]` hooks; cannot enqueue 20+ card fetches
- **Stored hits don't move chat to top**: Changed from always re-ordering sessions to keeping chronological order; only move when message count increases (new message added)
- **Dungeon quest icons**: Show correct portal sprites (purple dome for Shatters, not ice portal)
- **Shiny quest**: Only shows star badge if item actually has a shiny version
- **Paywall reminder slide showed the wrong info** (`PaywallModal.tsx`): the 3rd slide always displayed the daily-refresh countdown even when the caller still had free messages left. Now shows "You still have N free messages left today" while `remaining > 0`, and only switches to the refresh countdown once `remaining` hits 0
- **Daily quest bonus could desync from the message quota** (`api/services/daily_quests.py`, `api/routers/chat.py`): `_claimed_key`/`_free_bonus_key` expired at a fixed UTC-midnight-derived TTL while the message quota itself (`rate_limit.Quota`) is a rolling 24h window anchored to the caller's first message. `claim_daily_bonus` now takes the caller's live quota TTL (`rate_limit.peek_ttl`) and expires the claim/bonus at the same instant the quota resets, for the free/guest path. Frontend (`web/lib/quests.ts`): added `syncQuestWindow`, called from `ChatInterface.tsx`'s `refreshUsage`, which detects a quota rollover from `resets_in_seconds` increasing and clears local quest checkmarks/claim state only then, not on a UTC calendar flip. `readProgress`'s old same-day date check is now only a 2-day stale-data safety net
  - Test: `test_daily_quests.py::test_claim_expires_with_quota_not_at_utc_midnight`
- **New account's IGN was silently dropped** (`web/lib/accountProfile.ts`, `PaywallModal.tsx`): registering an account sends `ign` to the backend, but nothing saved it client-side, so the very next `AUTH_CHANGED_EVENT` (fired inside `registerAccount` itself) found no saved profile and cleared the sidebar's IGN box, skipping the pet scrape entirely. `saveSavedAccountProfile`/`loadSavedAccountProfile` now take an optional explicit `email` param so the profile can be saved *before* the auth token exists (keyed by the email being registered, not `decodeAuthEmail()`, which isn't populated yet). `handleCreateAccount` saves the typed IGN under that email right before calling `registerAccount`, guarded so it never overwrites an already-saved profile (e.g. a failed registration retry)
- **Chats started from Quests / sidebar quick-suggestions never appeared in the sidebar** (`ChatInterface.tsx`): the session-persist effect added earlier the same day (see "Stored hits don't move chat to top" above) only ever updated an *existing* session via `prev.map(...)`, which is a no-op insert for a session id that isn't in `prev` yet. Every chat still went through the composer's normal flow fine (its session already existed by the time this ran), but a chat whose very first message came from the Quests modal or a sidebar quick-suggestion generated a fresh id that `.map()` silently dropped, since those entry points also call the same `sendMessage()`. Now inserts (`[updated, ...prev]`) when the session doesn't exist yet, and still only updates-in-place (no reorder) when it does. This also fixes quick-suggestions on the *currently open* chat looking like they "didn't save": the chat itself was never in `sessions` to begin with
- **`scan_iter` was unclassified in `api/redis_namespace.py`**, so any namespaced deployment (`DEPLOYMENT_NAMESPACE` set, i.e. every real Azure deploy) raised `AttributeError: Redis command 'scan_iter' is not classified` the moment anything called it, first hit in prod as a caught-and-logged warning from `specialist_warm.dps_store_status`'s loadout count on the very first Container App boot. It couldn't just join `_SINGLE_KEY_COMMANDS` like `get`/`set`: `scan_iter`'s `match` argument is a glob that needs the namespace prefix applied so the scan only sees this deployment's keys instead of every deployment sharing the same Redis instance, and unlike a normal command it *yields keys back*, which need the prefix stripped again on the way out so a caller that reuses one (e.g. `client.delete(key)`) doesn't double-prefix it. Added a new `_KEY_ITERATOR_COMMANDS` category and a `NamespacedRedis._strip_prefix` async generator to handle both directions
  - Test: `test_namespacing.py::test_scan_iter_only_sees_this_namespace_and_strips_the_prefix`

### Internal
- **Postgres migration, code side** (`api/services/db.py`, new): Shared backend behind one interface for `accounts.py`, `entitlements.py`, `uploads.py`, `billing_prefs.py` - SQLite when `DATABASE_URL` is unset (local dev/tests, unchanged), Postgres via `asyncpg` when it's set (any deployment with more than one Container Apps replica, where SQLite on a shared volume isn't safe with concurrent writers)
  - `?` placeholders rewritten to `$1, $2, ...` for Postgres so every call site's query string is unchanged across both backends
  - `db.add_column_if_missing`: portable `ALTER TABLE ... ADD COLUMN` (Postgres supports `IF NOT EXISTS` natively; SQLite doesn't for `ALTER TABLE`, only `CREATE TABLE`/`INDEX`/`VIEW`/`TRIGGER`, so that backend checks `PRAGMA table_info` first)
  - `db.execute_returning`: `UPDATE ... RETURNING` support so a read-then-write (`set_status_by_customer`) stays one atomic round trip instead of racing a separate `SELECT`
  - Schema still created lazily on first use per store (same as the old per-path cached `sqlite3.Connection` did implicitly), not only via an explicit `init_db()` call - every public function in the four store modules calls it first, cheap after the first time per resolved path/DSN
  - `uploads.py`'s `data` column is the one place DDL isn't portable (`BLOB` vs `BYTEA`); `db.run_ddl(..., postgres_statements=...)` branches only that one statement
  - New `asyncpg==0.30.0` dependency; `DATABASE_URL` setting in `api/config.py`; optional `postgres` service added to `docker-compose.yml` (commented out by default) for testing the Postgres path locally without standing up Azure
  - Manually verified against a real local Postgres container: accounts create/duplicate-reject/verify/IGN lookup, entitlements upsert/`is_active`/`set_status_by_customer` RETURNING, billing_prefs column migration, uploads BYTEA round-trip - all 353 existing pytest cases still pass unchanged against the SQLite default (no live Postgres in CI yet, that's still a gap)
- **`api/Dockerfile`** (new): `docker-compose.yml` referenced one that never existed. Built on `mcr.microsoft.com/playwright/python:v1.49.0-noble` so Chromium/Firefox/WebKit and every OS-level dep the scraper needs ship in the image, rather than hand-maintaining an apt-get list that drifts from whatever Playwright actually needs release to release. Build context is the repo root (not `api/`) so `uvicorn api.main:app` resolves the same package path it does locally. New `.dockerignore` (repo root) keeps `web/`, `.git`, `.env`, and caches out of the build context. `docker-compose.yml`'s `api` service build context/port fixed to match (`context: .` / `dockerfile: api/Dockerfile`, `8001:8001` not `8000:8000`); removed the obsolete `version: "3.9"` key (Compose ignores and warns on it now)
- **Azure Container Registry created**: `realmpalacr` in a new `rg-realmpal` resource group (not the pre-existing `rg-certio`, where an old non-working Foundry resource lives). Image built and pushed as `realmpalacr.azurecr.io/realmpal-api:latest`
- **Qdrant Cloud provisioned and seeded**: free-tier cluster `realmpal` (AWS us-east-1). `QDRANT_URL`/`QDRANT_API_KEY` set. Seeded via `python -m api.scripts.seed_wiki` (39 hubs) and `seed_dps` (36 RealmShark builds); verified `get_collections`/`query_points`/`upsert` against the real cloud cluster, not just that the seed scripts exited clean. Known gap: local `qdrant-client` 1.13.0 is a couple minors behind the cloud server's 1.19.1, breaks the single-collection `get_collection()` detail call only (nothing in the app's runtime path uses it), worth bumping eventually
- **Azure Managed Redis provisioned**: `realmpal-cache` in `rg-realmpal`, East US 2, Memory Optimized tier (cheapest offered; Balanced is tuned for production throughput this app doesn't need), HA disabled, public network access enabled (no VNet set up yet for this project, same tradeoff as Postgres below). `REDIS_URL` built from the resource's Primary access key and Overview hostname (`rediss://` TLS, port `6380`)
- **Azure Database for PostgreSQL Flexible Server provisioned**: `realmpal-db` in `rg-realmpal`, East US 2, Burstable B1ms / 32 GiB autogrow (~$16/mo; the create wizard defaults to "Production" workload type, which quotes a Business Critical D4ds_v5 + zone-redundant HA around $549/mo, switched to "Dev/Test" workload + "Disabled (99.9% SLA)" zonal resiliency instead), PostgreSQL-only authentication (no Entra auth, the app connects via plain `asyncpg` credentials), public access with "allow public access from any Azure service" checked plus the operator's own IP allow-listed for direct checks. `realmpal` database created inside it (no migration scripts needed, every store's `CREATE TABLE IF NOT EXISTS` runs on first use same as the SQLite path always did)
- **Container Apps Environment + Container App deployed**: `realmpal-env` environment, `realmpal-api` app, East US 2, Consumption workload profile, 0.5 CPU / 1 GiB, image `realmpalacr.azurecr.io/realmpal-api:latest` pulled via the environment's system-assigned managed identity (portal auto-grants it `AcrPull`, no registry secret needed), ingress HTTP on port `8001` open to any traffic. First revision crashed on boot (`pydantic_core.ValidationError: Set ANTHROPIC_API_KEY for local fallback, or configure Foundry`), env vars were pasted in without it; added `ANTHROPIC_API_KEY` (matches the already-made decision to launch on a direct key and swap to Foundry once Azure billing review clears, not held on it) and redeployed. Second revision booted clean and `/health` returns `200 {"status":"ok","model":"claude-sonnet-4-6","provider":"anthropic"}` from the public Application URL, then surfaced the `scan_iter` bug above (caught, logged, non-fatal), fixed and redeployed as a third revision
  - Secrets currently sit as plaintext Container App env vars (`JWT_SECRET`, `STRIPE_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`); moving them to Key Vault references is next, not done yet
- **Dropped hybrid Next.js hosting for `web/` before it was ever deployed**: picking Azure Static Web Apps for the frontend, then double-checking whether hybrid (SSR) rendering was actually needed, turned up that `web/app/api/chat/route.ts` (a proxy that would've been the only reason to need a live Next.js server: it forwarded the `Authorization` header and re-streamed the FastAPI backend's SSE response) was dead code - `web/lib/api.ts`'s `sendChatMessage` already fetches `${API_URL}/chat/stream` directly from the browser and always has, nothing in `web/` ever called `/api/chat`. Same story for the `/api/sprite` rewrite in `next.config.ts`, also unreferenced anywhere. Deleted both. `next.config.ts` now uses `output: "export"` (Next.js's fully stable static-export mode) instead of `output: "standalone"` (which was for Azure Static Web Apps' hybrid mode, still labeled preview by Microsoft, with documented cold-start and streaming-reliability gaps on the Functions/App Service layer it runs SSR on - exactly the kind of risk not worth taking for a chat app's core latency-sensitive feature, especially for zero actual benefit). `images.unoptimized` set to `true` since static export has no server to run the Next/Image optimization API; these are small pixel-art wiki icons already correctly sized at the source, no visible difference. Rebuilt clean: all 8 routes now `○ Static`, `out/` produced
  - Found while checking this: 6 pre-existing ESLint errors (`react-hooks/set-state-in-effect`) across `SpriteZoom.tsx`, `SkinPortrait.tsx`, `PlayerCard.tsx` (both `components/chat/` and `components/player/`), unrelated to tonight's changes (confirmed via `git diff --stat`, this session's diff never touched those files) and not a build blocker (`next build` doesn't run ESLint as a gating step in this Next.js version). Left as a follow-up, tracked in `BACKLOG.md`, not fixed here to avoid unrelated scope creep
- **First production deploy of `web/` (Azure Static Web Apps)**: created `realmpal-web` in `rg-realmpal`, GitHub-connected to `master`, static (non-hybrid) build (`app_location: /web`, `output_location: out`). One-time protected-branch bypass needed for Azure's auto-committed workflow file (re-locked immediately after). Live at `https://thankful-mushroom-0951bfb0f.3.azurestaticapps.net`
- **Multi-origin CORS + `NEXT_PUBLIC_API_URL` wiring** (`api/config.py`, workflow YAML): added `EXTRA_CORS_ORIGINS` (comma-separated) alongside `APP_URL` so CORS can allow the azurestaticapps.net URL and the eventual `realmpal.com` apex + `www` domains at once during the custom-domain cutover. Added `NEXT_PUBLIC_API_URL` as a GitHub secret, passed into the Build And Deploy step's `env` (static export bakes `NEXT_PUBLIC_*` into the JS bundle at build time, there's no server at runtime to read a portal setting from). Fixes the deployed frontend's "Failed to fetch" on sign-in/register, caused by `NEXT_PUBLIC_API_URL` defaulting to `localhost:8000`. Test: `test_cors_includes_extra_origins_alongside_app_url`
- **Auth request timeout** (`web/lib/api.ts`): `postAuth` (sign-in/register) had no client-side timeout, so a slow backend response (e.g. queued behind the scraper semaphore below) left the UI spinning forever with no feedback. Added a 20s `AbortController` timeout with a clear, retryable error message
- **Diagnosed: live scrapes queue behind specialist warming in production**: a player lookup took 43s in prod because `api/services/scraper.py`'s `_PW_SEM = asyncio.Semaphore(1)` (one Chromium at a time, parallel launches crash the driver, likely a `/dev/shm` constraint) serializes every scrape, including specialist warming's UmiEnjoyers BIS/hub/dungeon queue. Compounded by ~8 same-night redeploys each restarting the process mid-warm, so it never got an uninterrupted run to finish and reach its 7-day TTL. No code fix yet, tracked in `BACKLOG.md`, needs real testing (interactive requests should get semaphore priority over background warming) before touching it in production
  - Confirmed same night: `/health` (pure static JSON, zero I/O) took 37s to respond while warming was active. Ruled out a Python-side blocking bug (`_goto_with_retry`'s retries use `asyncio.sleep`, not blocking `time.sleep`; page-data extraction runs as JS inside the browser via `page.evaluate()`, not heavy Python-side parsing) - the real cause is almost certainly the Container App's CPU allocation (0.5 vCPU / 1 GiB, Azure's small default), too little to run headless Chromium and FastAPI's event loop at the same time without one starving the other. Recommended bumping to 1.0 vCPU / 2 GiB, not yet applied
- **`web/lib/api.ts`: timeout `fetchPlayer`/`fetchDungeon`/`fetchItem`**: same gap as the auth fix above, these scrape-backed lookups had no client-side timeout either, so the sidebar's pet selector could look completely broken during a slow/CPU-starved window even though the backend eventually returned 200 (confirmed in prod logs: both a `Turbine` and a `Nutz` lookup succeeded, just took 17-22s). Extracted a shared `fetchWithTimeout` helper (`postAuth` now uses it too, replacing its one-off inline version) and gave scrape-backed lookups a 45s allowance vs auth's 20s. `Could not ingest player profile into RAG store` warnings in the same logs are unrelated and non-fatal by design (`api/routers/players.py` already catches that and still returns the profile); the underlying `AsyncQdrantClient` is `@lru_cache`'d in `api/dependencies.py`, not recreated per request as first suspected
  - **Correction, Sep 14, ~12:15 AM:** the conclusion above ("unrelated and non-fatal by design") was incomplete. The `@lru_cache`'d-client finding was correct as far as it went, but the actual root cause sits one layer earlier: `api/services/embeddings.py`'s `EMBEDDING_BACKEND` defaults to `"ollama"` (`OLLAMA_URL=http://localhost:11434`), and there's no Ollama server anywhere on the Container App, so the embed call itself throws `httpx`'s generic `All connection attempts failed` before the Qdrant write is ever attempted. This isn't narrow: the exact same failure also silently empties `retrieve_context` for every non-specialist chat turn (caught by a broad `except Exception` in `api/routers/chat.py`, logged as "RAG context retrieval failed, answering without retrieved context") - i.e. most chat replies are running with zero retrieved wiki context, with no error surfaced to the user. Reproduced live: asked about a dungeon slug already confirmed cached in Redis and still got "I don't have dungeon guide data... in the context provided". Full writeup and fix plan (blocked on getting a Voyage AI API key + re-seeding Qdrant Cloud, since it was originally seeded with Ollama embeddings) is at the top of `BACKLOG.md`'s resume-order list as of Sep 14
  - `DATABASE_URL` took four more redeploys to get right, each a distinct real-world Postgres connection-string gotcha worth remembering: (1) the admin password contained `@`, which broke DSN parsing since asyncpg's parser reads the first `@` as the credentials/host separator - URL-encoding it as `%40` fixed host resolution but not auth; (2) the Container App's outbound IP wasn't covered by "allow public access from any Azure service" and needed an explicit firewall rule; (3) the connection string was missing `:5432/realmpal?sslmode=require` entirely, so Postgres defaulted to a database named after the username; (4) ultimately reset the admin password to alphanumeric-only rather than keep chasing encoding edge cases, since that password gets pasted into multiple places (Container App env var, Key Vault next, local `.env` for one-off checks) and any one of them getting the encoding wrong reproduces the same failure. The `realmpal` database itself also had to be created manually (Databases blade only ships the `postgres`/`azure_sys`/`azure_maintenance` system ones by default) - confirmed clean by the total absence of the three "Could not open the ... DB" warnings in the next revision's Log stream
- **Deployment namespace** (`DEPLOYMENT_NAMESPACE` in `api/redis_namespace.py`): Scopes all Redis keys and Qdrant collection per environment (prod/staging)
- **Entitlements durability** (`api/services/entitlements.py`): SQLite replaces in-memory JWT `paid` claim
  - Stripe webhooks update: `checkout.session.completed` → `status="active"`, `customer.subscription.updated/deleted` → update/close
  - Pure function `_apply_stripe_event` tested without Stripe signature; real HMAC test included
- **Chat history account scoping**: Email keyed via `historyOwnerRef`, `persistPausedRef`; logout doesn't mix sessions
- **Specialist warming** (`api/services/specialist_warm.py`):
  - Startup warms only empty stores; GitHub Action `Refresh wiki specialists` (Monday) and `refresh_wiki` CLI force-refresh
  - Category hubs (enchanting, weapons, ability-items, armor) are indexes; expected to have 0 items
  - ~7 day TTL on wiki stores; players stay ~2 min live
- **Input sanitization** (`api/services/validation.py`):
  - `sanitize_lookup_name` rejects control/newline chars, `/`, `\`, `..`, oversized input
  - Prevents path-traversal noise and log injection
- **Changelog rule** (`.cursor/rules/changelog.mdc`): Every user-facing change needs changelog entry before deploy
- **Doc history rule** (`.cursor/rules/doc-history.mdc`): Keep dated prior text when updating `BACKLOG.md`, `README.md`, or `docs/`
- **No-read-secrets rule** (`.cursor/rules/no-read-secrets.mdc`): Agent must never read `.env`/`.env.*` or any real-credential file; verify writes via the app's own settings loader printing only booleans, never raw values
- **Documentation restructure**: Moved detailed pricing/benchmarks to `docs/pricing.md` (gitignored) and `docs/chat-quality-benchmarks.md`
- **Tests**:
  - `pytest api/tests/test_claude_billing.py`: Verify 68-pool exhaustion, overage billing, stored-hit metering skip
  - `pytest api/tests/test_stored_answers.py`: Paid stored hit does not increment Claude meter, second identical ask is cache hit, constrained follow-up streams
  - `pytest api/tests/test_specialist_startup.py`: `enchanting` counted in full-store snapshot; startup does not warm when `ENCHANTING_CACHE_KEY` is seeded
  - `pytest api/tests/test_enchanting.py` (new): `infer_item_base_stat` reads On Equip bonus / ignores scaling-only items / returns `None` on a tie; `infer_class_primary_stat` picks the most-common scaling stat / returns `None` on tie or empty; `retrieve_enchanting_brief` infers Attack from Cackling Straitjacket's `+20 ATT` when no stat is named, but respects an explicit stat over the item's own bonus; `retrieve_build_knowledge` infers Kensei's Dexterity scaling for a stat-less "best kensei build" instead of dropping Enchantments
  - `pytest api/tests/test_daily_quests.py::test_claim_expires_with_quota_not_at_utc_midnight` (new): claim/bonus key TTL tracks the caller's live quota TTL, not a fixed 24h-from-claim or calendar key
  - `pytest api/tests/test_payments.py` (5 new): `checkout.session.completed` falls back to `customer_details.email`; `/payments/portal` opens a session for a paid account's Stripe customer, 401s signed-out, 404s an account with no Stripe customer on file; `entitlements.get_stripe_customer_id` returns `None` with no row
- **353 backend tests pass** (`pytest api/tests/ -q`); `tsc --noEmit` clean on `web/` after the fixes above

### Deployment
- **Commits pushed to `master`**:
  - `25bf6bf`: Server-issued identity + IP-keyed quotas; `--no-proxy-headers` security
  - `b320ca3`: `DEPLOYMENT_NAMESPACE` for Redis + Qdrant
  - `4c1f60b`: Cost ceilings + `killswitch:chat`; paid tokens daily limit
- **Uncommitted on `dev`** (ready for next session):
  - Foundry client (blocked on Azure billing account review)
  - Lookup rate limits
  - CORS hardening
  - Magic-link hardening
  - Entitlements SQLite
  - Email+password accounts
  - Guest 3 / signed-in 5 daily meter

### Known Issues
- **Azure Foundry deployment blocked**: Billing account under review; cannot purchase Marketplace models until cleared by Azure Support
- **Entra Google SSO silent renewal bug**: 12–24h after first sign-in, token renewal fails; workaround is email OTP only or force `prompt=select_account`
- **Infrastructure lockdown pending**: Docker Compose still exposes Redis 6379 and Qdrant 6333 with no credentials (local dev only; move to private networking + creds on real deploy)

### Next Up
1. **Azure Static Web App for `web/`**: no frontend hosting plan existed yet, backend-only so far. Decided Azure Static Web Apps over Vercel (stays fully on Azure for the portfolio story) and over a second Container App (Static Web Apps' free tier + built-in GitHub CI is simpler than hand-rolling ingress/scaling for a second container). Once live: point its `NEXT_PUBLIC_API_URL` at the Container App's Application URL, and update the API's `app_url` setting (drives `cors_allowed_origins`) to the Static Web App's URL
2. **Key Vault**: move plaintext env vars pasted into the Container App (`JWT_SECRET`, `STRIPE_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`) into Key Vault references
3. **Production secrets review**: `PII_HASH_SECRET` and `MAGIC_LINK_SECRET` are both still unset on the deployed Container App (each falls back to `JWT_SECRET`, logged as startup warnings in the live log stream); set both explicitly and rotate `JWT_SECRET` off its local-dev value before real launch
4. **Entra code integration**: MSAL SPA sign-in against the now-configured `RealmPal` tenant; swap (or complement) local email+password with Entra-issued tokens
5. **Enable Stripe Customer Portal in the Dashboard for live mode**: same one-time toggle as test mode, separate per mode
6. **Per-user Qdrant filtering**: Low priority (currently holds only public scraped data)

#### History
##### Until Sep 13, 2026 (later same day, fourth revision)
1. Container Apps click-through: registry created and image pushed, Qdrant Cloud provisioned and seeded; still need Azure Managed Redis provisioned (Azure Cache for Redis blocks new creation from Oct 1, 2026, switched picks mid-session, see `docs/DEPLOYMENT_GUIDE.md` history), then the Container Apps Environment + Container App itself. Exact steps in `docs/DEPLOYMENT_GUIDE.md` Priority 4
2. Provision the real Postgres server: code side is done; still need the actual Azure Database for PostgreSQL Flexible Server created and `DATABASE_URL` pointed at it. `docs/DEPLOYMENT_GUIDE.md` Priority 6
3. Key Vault: move plaintext env vars pasted into the Container App into Key Vault references
4. Entra code integration, Stripe live-mode Customer Portal toggle, per-user Qdrant filtering: unchanged, see current list above

**Superseded because:** Redis, Postgres, and the Container App itself all got
provisioned and deployed (Sep 13, later, see "Internal" above), which
surfaced that there was no plan at all yet for where the Next.js frontend
would live, that became its own item ahead of Key Vault.

##### Until Sep 13, 2026 (later same day, third revision)
1. Entra code integration: MSAL SPA sign-in against the now-configured `RealmPal` tenant; swap (or complement) local email+password with Entra-issued tokens
2. Enable Stripe Customer Portal in the Dashboard: Settings → Billing → Customer portal, one-time toggle, required before the new `/payments/portal` endpoint works outside test mocks
3. Container Apps + Key Vault: Infrastructure for Azure deploy
4. PostgreSQL migration: After Foundry unblocked
5. Per-user Qdrant filtering: Low priority (currently holds only public scraped data)

**Superseded because:** decided to do the Postgres migration immediately
(Sep 13, later) instead of waiting on Foundry, and starting the Container
Apps click-through surfaced that there was no `Dockerfile` and no plan for
Redis/Qdrant once the API isn't running via docker-compose. Items 1-3
above got split out to reflect that.

##### Until Sep 13, 2026 (later same day, second revision)
1. Entra External ID: Collect portal values; portal setup documented in `docs/DEPLOYMENT_GUIDE.md` - **done later this same day** (tenant, both app registrations, user flow, `.env` values), see "Added" above
2. Stripe payment flow audit: End-to-end review of checkout → webhook → entitlement (no known bug; unverified since Link payment method was added) - **done later this same day**, found and fixed the `customer_details.email` gap and the missing Customer Portal, see "Added"/"Fixed" above

##### Until Sep 13, 2026 (later same day)
1. Enchantment specialist: Wire 4 remaining tasks (warm integration, RAG injection, wiki skip, tests) - **done later this same day**, see "Added" above

---

## [Unreleased] - Work in Progress

### Planned
- **DPS specialist** (started, low priority): Wiki formula + RealmShark loadouts as reference, same wiring pattern as the now-shipped Enchantment specialist (see [2026.09.13])
- **Entra External ID**: CIAM tenant with Google + email OTP sign-in
- **Container Apps deployment**: FastAPI on managed Azure compute
- **PostgreSQL**: Replace SQLite after Foundry works
- **Per-user Qdrant filtering**: Add `user_email` metadata to vectors when per-user docs arrive
- **CI/CD pipeline**: Auto-deploy on `master` push

### Not Planned This Release
- **Real email provider for magic-link** (magic-link is fallback; email+password is primary)
- **Guild page lookups**
- **Flutter mobile app**

---

## [2026.09.12] - Sep 12, 2026

### Added
- **Stored answers system** foundation:
  - `api/services/stored_answers.py`: Classify turn before Claude
  - Redis stores for wiki dumps, builds, guides
  - `rag.py`: Embedding-based context retrieval
- **Specialist warming** (`api/services/specialist_warm.py`):
  - Hubs, T7/ST/UT items, dungeons, Umi BIS, DPS boards, skins
  - Weekly refresh via GitHub Action
- **Dungeon guides** from warmed wiki (no Claude essay)
- **Build guide storage** (`wiki:build:v1:{class}:{stat}`)

### Infrastructure
- **Redis persistence** via AOF (survives `stop_services`)
- **Qdrant collection** with public scraped data

---

## [Earlier Releases]

### 2026.09.08
- Initial authentication system (JWT, magic-link sign-in)
- Chat streaming with Claude API
- Basic quota system (guest 3/day, signed-in 5/day)
- Player/item/dungeon/skin lookups with Playwright scraping
- RealmEye integration

### 2026.09.01
- Project initialization
- Docker setup (FastAPI + Next.js)
- Basic chat interface
- Redis connection

---

## Migration Guides

### Upgrading to 2026.09.13 from Earlier

#### From Pre-Entitlements (no Stripe subscription tracking)

If you have an existing deployment with customers who paid before `entitlements.py` landed:

1. **Do nothing immediately**: `_has_legacy_paid_token` falls open for unknown emails; existing tokens keep working
2. **On customer's next sign-in**: Email is added to entitlements store as `active`
3. **If subscription cancelled**: Stripe webhook adds `status="cancelled"` row; next token verification denies access

#### From Old Pricing (90 included pool)

1. Update `.env`: `PAID_CLAUDE_INCLUDED=68`, `PAID_MESSAGE_LIMIT=50`
2. Restart API and web
3. Existing users see new limits on next chat message over the pool
4. No data migration needed (pool size is config-only)

#### From Pre-Account-Scoped Chats

1. Chats stored as `realm_pal_sessions` (unkeyed) are migrated to `realm_pal_sessions:{email}` on first login
2. Guest and account chats stay separate afterward

---

## Developer Notes

### Running Locally

```bash
# Install
pip install -r api/requirements-dev.txt
npm install --prefix web

# Run
cd api && python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
cd web && npm run dev

# Test
pytest api/tests/ -v

# Warm specialist stores
python -m api.scripts.warm_specialists --status
python -m api.scripts.refresh_wiki  # Force full refresh
```

### Environment Variables

**Required:**
- `JWT_SECRET`: Session token secret (rotate before production)
- `STRIPE_KEY`: Stripe API key
- `FOUNDRY_RESOURCE` / `FOUNDRY_BASE_URL`: Azure Foundry endpoint (or leave empty for `ANTHROPIC_API_KEY`)

**Optional:**
- `DEBUG=true`: Enables `/docs`, serves localhost CORS, relaxed secrets checks
- `DEPLOYMENT_NAMESPACE`: Multi-tenant isolation (default: empty, all share same Redis/Qdrant)
- `PAID_CLAUDE_INCLUDED=68`: Included Claude per month
- `PAID_MESSAGE_LIMIT=50`: Max messages per day for paid
- `CLAUDE_OVERAGE_USD=0.08`: Cost per Claude reply after pool

### Security Checklist for Production

- [ ] `DEBUG=false`
- [ ] `JWT_SECRET` rotated (not `change-me-in-production`)
- [ ] `MAGIC_LINK_SECRET` set (separate from `JWT_SECRET`)
- [ ] `PII_HASH_SECRET` set
- [ ] All secrets in Key Vault, not `.env`
- [ ] CORS restricted to `app_url`
- [ ] Redis password set
- [ ] PostgreSQL (not SQLite) in use
- [ ] Backups enabled
- [ ] Monitoring enabled (Azure Monitor, Datadog, etc.)

