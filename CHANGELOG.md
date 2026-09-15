# Changelog

All notable changes to RealmPal are documented here. This is the **developer changelog** (technical details, internal changes, breaking changes, migrations). 

**Related files:**
- **User-facing changelog:** `web/lib/changelog.ts` — rendered in the app UI ("What's new" modal, first-load popup, settings page)
- **Product decisions:** `BACKLOG.md` — high-level roadmap, current priorities, research notes
- **Deployment guide:** `docs/DEPLOYMENT_GUIDE.md` — exact Azure portal steps

Format: each version has technical notes, linked commits, migration guides (if needed), and internal changes not exposed to users.

---

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

### Changed
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

