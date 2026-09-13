# Backlog

Last updated: 9/13/26

Target platform: **Azure**. Chosen for portfolio reasons — it's screened for by the
enterprise half of the roles being targeted, and invisible to the startup half.
Container Apps for compute (the API needs a real container for Playwright, which
rules out serverless), Entra External ID for identity, Key Vault for secrets.
SQLite on a mounted volume until billing lands, then Azure Postgres.
**Claude via Microsoft Foundry**, not a generic Anthropic API key (see below).

Resume order when context is fresh:

1. **Finish Enchantment specialist** - scrape + slot agent exist; warm, chat inject, and tests do not.
2. Entra External ID - needs portal values (tenant/client IDs).
3. Foundry - **blocked**, see below. Don't retry deployment until the billing account clears review.

**Technical summary name for this chat: Stored-answer chat.**

That is the umbrella: classify the turn, serve Redis replies, call Claude only when the ask is new or constrained. Daily quests, $7 + PAYG, account-scoped history, dungeon wiki dumps, and whole-card zoom shipped around it. Warming stays; briefs sit on top of it.

A user-facing changelog also shipped (`web/lib/changelog.ts` is the source of truth for "what's new"; `.cursor/rules/changelog.mdc` makes future sessions add an entry per deploy-worthy change).

Remaining security/multi-tenancy items are small and not blocking: infra lockdown wiring for a real deploy, a stronger prompt-injection defense than a denylist, Key Vault migration, per-user Qdrant filtering.

Do not start Entra mid-session. Do not treat warming as obsolete. See Stored answers. Enchantment is next.

---

### Stored answers — **done** (this session)

`api/services/stored_answers.py` classifies the turn before Claude. Drops, best-slot hubs, early-game, minted `{stat} {class}` briefs, dungeon wiki dumps, shiny-divine quests, and skin templates stream from Redis. Constrained follow-ups and live player lookups still call the model.

Builds: first mint uses Sonnet (`pick_chat_model` keeps `{stat} {class}` and "best items/build" on Sonnet). Class nicknames (`pally`, `trix`, `sorc`, `hunt`, `wiz`, `rog`, …) parse in `api/models/build.py`. Only a Sonnet reply is written to `wiki:build:v1:{class}:{stat}`. The next identical ask is a stored hit.

Dungeon how-tos: compose from warmed `wiki:guide:v6:` pages (`GUIDE_BRIEF_PREFIX = wiki:guide-brief:v2`). Hard Mode uses the last Hard Mode heading, `include_lead=False`, and does not mint a Claude essay over the wiki store. Player-facing HMS notes still append (Source dome, Valen → Nox → Azamoth). Weekly `refresh_wiki` invalidates briefs.

Signed-in stored hits skip the daily free/guest meter. Guests still consume a daily message on a stored hit.

Paid Claude is a monthly pool (`PAID_CLAUDE_INCLUDED` = 68, about $2.50 of Claude at ~$0.0365/reply). Old 90 is replaced. Stored hits do not count against the pool. After the pool, `$0.08`/reply up to a user spend cap (default $0) via `GET`/`POST /payments/on-demand`. Daily fuse is 50 msgs/day (`paid_message_limit`). 70/30 stored/Claude is a success metric, not a hard quota. Paywall copy matches. Dismissing the $7 slide shows when the 5 daily free messages refresh.

Unit-econ estimates: `docs/pricing.md` (local, gitignored). Chat quality traces: `docs/chat-quality-benchmarks.md`. Internal doc history: `.cursor/rules/doc-history.mdc` (keep dated prior text; do not overwrite). **Developer changelog:** `CHANGELOG.md` (technical details, breaking changes, migrations). **User-facing changelog:** `web/lib/changelog.ts` (UI only). **Project structure:** Only `README.md` and `BACKLOG.md` live at root; all other docs in `docs/` folder.

### Changelog / "what's new" — **done** (this session)

`web/lib/changelog.ts` holds `CHANGELOG` (newest entry first) plus `LATEST_VERSION`, `hasUnseenChangelog()`, and `markChangelogSeen()` (keyed on a `localStorage` version string, no backend). `ChangelogModal.tsx` renders the list. Wired in three places: a minimal "What's new" button in the header cluster (dot badge while unseen) with an automatic first-load popup when the visitor hasn't seen `LATEST_VERSION`; a "Changelog" button on `/account/settings`. `.cursor/rules/changelog.mdc` (`alwaysApply`) tells future sessions to add a concise, user-facing entry for every deploy-worthy change and skip internal-only work. `.cursor/rules/doc-history.mdc` (`alwaysApply`) tells sessions to keep dated prior text when updating `BACKLOG.md`, `README.md`, or `docs/`.

### Minimal UI fixes — done (this session)

- Sidebar quick-suggestion prompts (Look up player / What does X look like with Y / Guide to complete Z) can now be collapsed. A small chevron button sits centered above the list in `ChatInterface.tsx`; click flips it and hides/shows the prompt list, remembered in `localStorage` (`realm_pal_suggestions_hidden`) so a visitor who hides them stays hidden on reload.
- Usage meters removed from the chat header and sidebar (the old `0/90 Claude replies` chip, from when the pool was 90). Replaced with a clickable **Daily quests** percent bar that opens a quests modal (ask about the Shatters, see a shiny divine item, look up a player, and similar — three rotate each UTC day). Completing all grants +1 message on **free and paid** via `POST /chat/quests/claim`, once per day (free daily quota or paid included reply). Billing lives in the account menu → **Billing** popup. `GET /payments/billing` added. `DEBUG_UNLIMITED_IGNS` default cleared so Turbine behaves as a normal free account unless explicitly allowlisted in `.env`.
- Lookup 429s on HMS guides: `/items` no longer spends the 12/min scrape window on warmed Redis hits. Chat no longer fans out every dungeon drop as an item-card fetch; stored guide briefs strip `[item:]` / wiki-link hooks so a minted HMS page cannot enqueue 20+ cards.
- Daily quests modal: rotating dungeon (Shatters / Moonlight Village / …) with cached portal sprite, player lookup uses the user icon, shiny-divine shows a cached shiny sprite from `GET /chat/quests/art`.
- Quests header: small `{percent}%` to the right of the progress bar.
- "Show me a shiny divine Crown" (and the same for other quest shinies) is a stored hit (`kind: shiny`): `[loadout shiny divine]` + `[item:Title]`, no Claude. Prefer the exact cached item name.

### Account-scoped history - **done** (this session)

Chats persist as `realm_pal_sessions:{email}` (`web/lib/chatHistory.ts`). Cards attach after the stream (`dungeonGuide`, `items`, `playerProfile`, `showExaltationTable`). Logout no longer writes the signed-in list onto the guest key (`saveSessions(sessions, email)`, `historyOwnerRef`, `persistPausedRef`). Empty account slots copy the legacy unscoped `realm_pal_sessions` once.

Daily quests persist as `realm_pal_daily_quests:{email}` and `realm_pal_quest_shift:{email}`. Reloaded in `applyAuthState`. `stop_services` does not wipe these (browser `localStorage`; Redis `stop` keeps its volume). Incognito wipes storage when the last Incognito window closes.

### Card zoom - **done** (this session)

`SpriteZoomTrigger` (`web/components/chat/SpriteZoom.tsx`): inline sprites keep the popunder + centered modal + RealmEye link. Whole character rows, exaltation rows, item-grid cards, and skin tiles use `preview="card"`: click opens the same centered, shadowed overlay with a scaled copy of the full card (item cards unclip the 170px grid height). Nested gear icons, rank links, and wiki links win the click (`isNestedControl`). Backdrop or Escape closes.

### Top pet - **done** (this session)

`_pick_top_pet` in `api/services/scraper.py` picks the yard pet with the highest RealmEye ability-level sum (then max single, then min). Not the first yard slot. Player profiles cache ~120s; sidebar also caches `top_pet` in `web/lib/accountProfile.ts`. Fresh scrape after API restart replaces a stale Monkey Head if it was not actually the high-stat pet.

### PAYG / billing UI - **done** (this session)

`api/services/claude_billing.py` + `billing_prefs.py`. Billing and spend-cap live in the account menu (`BillingModal`, `SpendingLimitModal`). Included pool and overage match the sketch below. This is no longer "new billing work."

Stripe Checkout (`api/routers/payments.py` `/checkout`, and the legacy `_checkout_url_for` in `api/routers/chat.py`) both pass `payment_method_types=["card", "link"]` so the hosted checkout page offers Link (Stripe's own saved-payment-method flow), not just a bare card form. We do not build our own checkout page; Stripe's hosted page is "the paywall page" once someone clicks Upgrade. Its icon/color branding is a Stripe Dashboard business-branding setting, not code.

### Stored answers (notes)

Specialist warming is the **fact store**. Stored answers are the **reply store**. They stack; the second does not replace the first.

Warming already puts hubs, T7/ST/UT item profiles, dungeons, Umi BIS, and RealmShark boards in Redis so chat does not live-scrape. Claude still reads those facts and writes a new essay every time someone asks "best Wis Kensei." That is the $0.03–$0.05. After a good answer exists, later identical prompts should return RealmPal's own brief — no model. Claude only when the ask is new or constrained ("no ST", "white bag only", "with my mule").

Do **not** fine-tune first. Mint and retrieve Redis keys. Weekly `refresh_wiki` can rebuild briefs from the same warmed hubs.

| Prompt | LLM? | Store |
|---|---|---|
| Where does X drop? | No | `item:profile:v3` `drop_locations` |
| Best bows / best &lt;slot&gt;? | No | warmed hub + a ranked snippet |
| Best early-game items? | No | small static / T0–T6 list (warm currently skips those) |
| Best {stat} {class}? | Once | `wiki:build:v1:{class}:{stat}` after the first solid run |
| Sets RealmShark does not list | Once | RealmPal-owned set brief |

Build order (all four shipped):

1. ~~Classify cheap prompts (drop, best-slot, early-game) and answer from warmed hubs / item profiles with no Claude call. Still emit `[item:]` so the card grid works.~~
2. ~~After a reviewed build reply, write `wiki:build:v1:{class}:{stat}` (loadout + why). Route "best items for a wis kensei" / "wis kensei build" to that key.~~
3. ~~Invalidate or rebuild briefs on weekly wiki refresh so they cannot drift from RealmEye.~~
4. ~~Tests: drop question never hits the LLM; second Wis Kensei in the same TTL is a cache hit; a constrained follow-up still streams.~~

Guest 3 / signed-in 5 per day stays. That is a trial, not a token strategy — the token strategy is skipping the model.

**Target mix: ~70% stored / ~30% Claude.** Success metric, not a hard quota. Meter Claude replies only. Stored hits stay $0.

Rule of thumb: same question for every user (build, dungeon how-to, drops, best bows) → RealmPal brief. About **this player right now** → live scrape, keep it cheap. Constrained follow-ups (“no ST”, “white bag only”) still stream Claude. They do not replace the brief.

Chat quality traces and the stored-answer map: `docs/chat-quality-benchmarks.md`. Unit-econ estimates and the shipped 68 / $2.50 table: `docs/pricing.md` (local, gitignored).

### History

#### Until Sep 13, 2026

The stored-answer map, 10-trace cost table, 70/30 cohort math, hosting estimates, unlimited-$7 break-even, and the working PAYG sketch (included **~80–100 / 90** Claude, daily fuse **200**) lived in this file. Copied in full to `docs/chat-quality-benchmarks.md` and `docs/pricing.md` the same day. Shipped product numbers became **68** Claude included (~$2.50) and a **50** msgs/day fuse. Old 90 is replaced.

---

## Blocked

### Azure Foundry — code done, blocked on Azure billing account review

Chat client is finished in `api/services/llm.py` and doesn't need more work. `_stream_response` picks Foundry when `FOUNDRY_RESOURCE`/`FOUNDRY_BASE_URL` is set (endpoint allowlisted to `https://<resource>.services.ai.azure.com/anthropic`, Entra or a Foundry key, never both), otherwise falls back to `ANTHROPIC_API_KEY`. CCU-aware spend logging, `/health` reporting `provider`, startup warnings on a raw key in prod — all in.

**Deployment fails in the portal**: both `claude-sonnet-4-6` and `claude-sonnet-4-5` deployments show `Provisioning state: Failed`, with "This purchase cannot be completed" from Azure Marketplace. Root cause found: **the Azure billing account (Kyle Wang) is "Under Review" / inactive** — Cost Management + Billing → Billing scopes → that account shows "Your account is under review... buying new products and services... will be restricted until the review is complete." Marketplace can't fulfill any paid model purchase while that's true. This is Microsoft-side, not a RealmPal config problem — resource providers, region (confirm East US 2 / Sweden Central), and subscription type are all fine; the account itself is locked.

Do not keep retrying deployments — each attempt just fails the same way. Resume when:
1. Billing account review clears (check Cost Management + Billing → Billing scopes → account status), or
2. Support resolves it directly.

Then: subscribe the `claude-sonnet-4-6-ccu-plan` Marketplace offer (not `-plan-new`), deploy, paste resource name into `.env`, confirm one live stream logs `provider=foundry` and a `cost_ccu` value.

### Enchantment specialist (started, not finished)

LangGraph slot next to weapon / ability / armor / ring. Reads RealmEye `/wiki/enchanting` tables (eligible slot, I–IV, unique/awakened) plus Umi general-tab BIS enchant notes. Isolation like Ring: an Attack ask must not pick up Mana Bonus.

**Already in the tree:**

- `api/services/enchanting.py` — `is_enchant_query`, `retrieve_enchanting_brief`, `warm_enchanting_store`, cache `wiki:enchanting:v1`
- `api/services/scraper.py` — `scrape_enchanting_page()`
- `api/services/slot_graph.py` — `"enchantment"` on `SlotName`, `_enchantment_agent`, enchant-only routing

**Still open (do these before calling it done):**

1. Wire `warm_enchanting_store` into `specialist_snapshot` / `missing_specialist_work` / `warm_all_specialists` and `warm_specialists --status`. Category hub `enchanting` stays an index (0 items); the roll-table store is separate.
2. `retrieve_build_knowledge`: enchant-only early-return; inject `retrieve_enchanting_brief` on full builds.
3. `chat.py`: skip extra wiki RAG on enchant-only questions (same pattern as dungeon).
4. Tests: "what enchants on QOT", "best DEX roll on Leaf Bow", must not fire on unrelated item questions.

Do not start Entra until those four are done.

### Multi-tenancy

Isolate users, sessions, usage, and paid accounts so more than one operator (or environment) can run RealmPal without sharing Redis keys, Qdrant collections, or Stripe customer state. Planned OAuth.

- ~~*Deployment isolation.*~~ **Done** (`b320ca3`). `DEPLOYMENT_NAMESPACE` scopes Redis keys and the Qdrant collection per environment — see Security hardening.
- ~~*Durable subscription store.*~~ **Done** (this session). `api/services/entitlements.py` — SQLite (`ENTITLEMENTS_DB_PATH`), one row per email: `status`, `stripe_customer_id`, `stripe_subscription_id`, `updated_at`. `POST /payments/webhook` writes to it: `checkout.session.completed` opens an `active` row (also creates the magic link, unchanged); `customer.subscription.updated`/`.deleted` update or close it by matching `stripe_customer_id` (those events carry the customer, not the email). Wired into `_apply_stripe_event`, a pure function factored out of the router so it's tested without needing a real Stripe signature — plus one test that *does* HMAC-sign a payload for real, since a mocked `construct_event` would hide a signature-verification bug. `api/routers/chat.py`'s `_has_legacy_paid_token` now calls `entitlements.is_active(email, settings)` before honoring a JWT's `paid` claim — a cancelled/refunded subscription is denied even with a validly signed, unexpired token. Fails open (trusts the JWT) for an email the store has never heard of, since a customer who paid before this landed has no row to revoke against yet; only an explicit non-active row denies.
- ~~*Email+password accounts.*~~ **Done** (this session). Primary sign-in is `POST /auth/register` and `POST /auth/signin` against `api/services/accounts.py` (SQLite `ACCOUNTS_DB_PATH`, PBKDF2-SHA256). Magic-link `POST /auth/request-link` stays as a Forgot-password fallback so ordinary sign-in does not depend on a paid email API. Entra External ID would later send OTP mail as part of Azure; until portal values exist, a local password is the cheap path. Register does not grant `paid` — that still comes only from `entitlements.is_active`. Password-session JWTs now resolve in `get_optional_user` so a signed-in account uses the user quota (and lookup burst limit), not the anonymous IP bucket. Browser chat history is keyed per email so Guest and account chats stay separate.
- Per-*user* Qdrant retrieval filtering is still open (tracked under Security hardening → Tenant isolation), but Qdrant currently holds only public scraped data, not per-user documents.
- Entra wiring is still open — see below; it plugs into the same `sub`-keyed identity path already used for chat quotas, no multi-tenancy-specific code needed once portal values exist.

### Security hardening

The MVP trusts the client more than a public deployment can afford. Status:

- ~~*Server-issued identity.*~~ **Done** (`25bf6bf`). `api/identity.py` verifies provider-issued JWTs against a JWKS endpoint (`iss`/`aud`/`exp`, asymmetric only) and uses the verified `sub` as identity. Provider-agnostic, so Entra is configuration.
- ~~*Real entitlement checks.*~~ **Done** (this session; see Multi-tenancy → Durable subscription store for the full writeup). A JWT with `paid: true` used to be accepted on signature alone — no subscription lookup, no revocation list — so a cancelled or refunded plan kept working until the token expired. `api/services/entitlements.py` now gives Stripe's webhooks somewhere durable to write to, and `chat.py` actually checks it. `4c1f60b`'s daily ceiling for legacy paid tokens (`PAID_MESSAGE_LIMIT`) stays as defense in depth underneath this.
  - ~~*Magic-link secret separation, single-use, no logging.*~~ **Done** (this session). Magic links were signed with `jwt_secret` — the same secret that signs every session token, so a leaked link was equally useful for forging a session — and were replayable any number of times inside their 30-minute window. `MAGIC_LINK_SECRET` (`config.py`) is now separate, falling back to `JWT_SECRET` only when unset, with a startup warning while it's unset. Every token carries a `jti` (`api/auth.py`); `POST /payments/verify` marks it spent in Redis via `SET NX EX` (atomic, so two concurrent redemptions of one link can't both succeed) and refuses a second use. `send_magic_link` no longer passes the token through `logger.info(msg, email=..., link=...)` — that pattern silently drops unbound kwargs when the message has no matching placeholder (an accident, not a guarantee); it now binds only `email` and never logs the link. `POST /payments/checkout` and `GET /payments/verify` are both throttled by the same lookup rate limiter, closing the "still unauthenticated" note on Checkout-session creation.
- ~~*Abuse and cost limits (chat).*~~ **Done** (`25bf6bf`, `4c1f60b`). Quotas key on the verified `sub` or a hashed client IP. `api/services/budget.py` tracks the day's real spend and returns 503 past `MONTHLY_COST_BUDGET_USD`/30, plus a Redis kill switch (`killswitch:chat`). Request size, replayed history, response tokens and the Anthropic timeout are all capped.
- ~~*Abuse and cost limits (lookups).*~~ **Done** (this session). `/players/{username}`, `/items/{name}`, `/dungeons/{name}`, `/skins/render`, and `/sprite` had **no rate limiting at all** — a cache miss on any of them launches a real headless Chromium behind a single-browser semaphore (`api/services/scraper.py`), so an unthrottled caller could queue unlimited launches and stall every other visitor's lookup. Added `WindowedQuota`/`consume_windowed` in `api/services/rate_limit.py` (short window, not the 24h chat quota) and a shared `enforce_lookup_rate_limit` dependency in `api/dependencies.py`, applied to all five routes. Defaults: 12/min anonymous, 40/min signed-in (`LOOKUP_RATE_LIMIT_ANONYMOUS` / `LOOKUP_RATE_LIMIT_USER` / `LOOKUP_RATE_WINDOW_SECONDS`). Fails open on a Redis blip, same philosophy as the budget check.
- ~~*Tenant isolation in storage.*~~ **Done** (`b320ca3`). `DEPLOYMENT_NAMESPACE` scopes the Qdrant collection and every Redis key via `api/redis_namespace.py`. Fixed `settings.qdrant_collection`, which was dead config. Per-*user* retrieval filtering is still open, but Qdrant currently holds only public scraped data.
- ~~*CORS.*~~ **Done** (this session). `http://localhost:3000` was hardcoded into `allow_origins` unconditionally — a deployed API accepted credentialed cross-origin requests from anyone running the frontend locally. `Settings.cors_allowed_origins` now returns only `app_url` unless `DEBUG=true`.
- *Infrastructure lockdown (remaining).* `docker-compose.yml` still exposes Redis 6379 and Qdrant 6333 with no password or API key, and bind-mounts `./api` into the container. That's a local-dev compose file, not the Container Apps target — move to private networking with credentials when the real deploy happens; `Settings` already supports a Redis URL with credentials and `qdrant_api_key`, so this is wiring, not new code. Keep `DEBUG=false` in any reachable deployment (it also gates `/docs`).
- *Untrusted scraped content — input sanitization done, prompt-injection denylist still weak.* `api/services/validation.py` (`sanitize_lookup_name`, this session) now rejects control/newline characters, `/`, `\`, `..`, and oversized input on every name that reaches a scraper — closes path-traversal noise and header/log injection ahead of the request. Host takeover was never actually reachable: `REALMEYE_BASE`/`UMI_BASE` are fixed constants and every scrape URL is built by concatenation, not from a caller-supplied host. Still open: `rag.py`'s prompt-injection defense is a short regex denylist over scraped text flowing into the system prompt — treat that as data, not instructions, with a stronger approach than a denylist.
- *Secrets and PII.* Keys live in a local `.env`; move to Key Vault with rotation, and give scraped profiles and billing emails explicit TTLs plus a deletion path. `JWT_SECRET` is still `change-me-in-production` locally — startup now warns loudly if `DEBUG=false` and it's unrotated, or if `PII_HASH_SECRET` is unset (`_warn_on_default_secrets` in `api/main.py`, this session). Stream errors no longer log exception text (that path previously dumped the Anthropic key). Rotate any key that has appeared in a local traceback before the API is publicly reachable. Foundry+Entra is the production path so neither Anthropic nor Foundry keys need to live in `.env`.

### Next up from last night: wire Entra External ID

Researched, not yet built. User asked for portal steps, then code once they paste tenant ID / client ID / JWKS URL. Sign-in methods chosen: **Google + email OTP**.

Findings:

- **Two app registrations, not one.** The API registration exposes a scope (`api://<api-client-id>/access_as_user`); the Next.js app requests *only* that scope. Entra issues one audience per token, so mixing Graph and custom API scopes in a single request fails — the `aud` comes back as Graph and the API rejects it. `aud` must be the API's client ID.
- **Authority is `ciamlogin.com`**, not `login.microsoftonline.com`, for external (CIAM) tenants. Issuer: `https://<tenant-id>.ciamlogin.com/<tenant-id>/v2.0`.
- **Known bug in built-in Google federation.** During silent token renewal Entra sends an unsupported `username` parameter to Google, which returns `400 invalid_request`. It surfaces 12–24h after first sign-in. Workarounds: force `prompt=select_account` (loses seamless SSO), or configure Google as a custom OIDC provider. Email OTP alone avoids this. **Decide before building the Google path.**
- Backend needs no new verification code: `api/identity.py` already verifies JWKS-signed tokens. Only `AUTH_JWKS_URL` / `AUTH_ISSUER` / `AUTH_AUDIENCE`. Next.js holds the session in httpOnly cookies and forwards the access token to FastAPI as Bearer.
- Local default stays anonymous until those three env vars are set (`auth_configured` is False).

Portal values to paste back: tenant ID, SPA client ID, API client ID / Application ID URI, JWKS URL, issuer, audience.

### DPS specialist (started, lower than Enchantment)

Wiki formula (`avg damage × shots × (1.5 + 6.5 × DEX/75) × RoF` at 0 DEF) plus RealmShark loadouts as reference. `api/services/dps_specialist.py` and a `"dps"` slot exist. Same leftover wiring as Enchantment (retrieve / chat RAG skip / tests). Finish Enchantment first; RealmShark boards already inject on regular builds, so this is only for DPS-only questions and explicit "what's the DPS" follow-ups.

---

## Done this session — wiki stores + item cards

Chat no longer live-scrapes wiki. Redis holds specialist stores for ~7 days (`wiki_ttl_seconds`). Players stay live (`player_ttl_seconds` = 120).

- `api/services/specialist_warm.py` fills hubs, abilities, T7/ST/UT item profiles (`item:profile:v3`), dungeons, DPS boards, Umi BIS, skins, sets. Startup warms only empty stores; GitHub Action `Refresh wiki specialists` (Monday) and `python -m api.scripts.refresh_wiki` force-refresh.
- Category hubs `weapons` / `ability-items` / `armor` / `enchanting` are indexes (0 items). That is expected and must not restart a warm.
- `missing_specialist_work` treats a few dead pages as complete (Babel Blocks never renders `.wiki-page`; skip it). Apostrophe variants count as the same item.
- `GET /items/{name}` and `/sprite` read the warmed v3 profile (straight or curly apostrophe). Chat item cards must not Playwright-scrape a warmed name.
- Item-card **grid** hides gear the asked class cannot wear (`wearable` from hub membership: Kensei = heavy / katana / sheath / rings). Sister-class comparison **text** is fine and still gets inline chips.
- Local API is **8001** (no uvicorn `--reload` on Windows). After backend changes, restart only when a warm is not running.

First full warm (this machine): abilities 19/19, items 1255/1256, dungeons 179/179, Umi 19/19, DPS 36/36, skins stored. Redis AOF volume keeps it across `stop_services`.

---

## Chat quality base cases

Traces and the stored-answer map now live in `docs/chat-quality-benchmarks.md`.

**HMS fact to keep:** after the purple dome (the Source) on the clear to Nox (2nd boss), drag all 4 branches/flames to the center. “Wings” is regular The Shatters, not Hardmode.

### History

#### Until Sep 13, 2026

The 10-row in/out/cost table lived in this section. Copied in full to `docs/chat-quality-benchmarks.md` the same day.

Local tester: signed-in IGN **Turbine** skips chat + lookup quotas only when listed in `DEBUG_UNLIMITED_IGNS` with `DEBUG=true` (default is empty — normal free/paid testing).

---

## Other notes

- Flutter mobile app (iOS + Android)
- Guild page lookups
- ~~Scheduled wiki re-scraping~~ **Done** (weekly Action + `refresh_wiki`). Player profiles stay live on request.
- Real email provider for magic-link login (Resend)
- ~~Sidebar: collapse the quick-suggestion prompts~~ **Done** (this session). See Minimal UI fixes below.
- Sidebar polish: Suggested title above the bottom-left sidebar section. Your IGN, Chats (stay when none exist), Suggested (planned) section titles — slightly larger font, lighter text color.

---

## Last night, for the next session

Pushed on `master` (`kylezwang/RealmPal`) before this session:

| Commit | What |
|---|---|
| `25bf6bf` | Server-issued identity + IP-keyed quotas. Closed uvicorn `--no-proxy-headers` hole. |
| `b320ca3` | `DEPLOYMENT_NAMESPACE` for Redis + Qdrant. |
| `4c1f60b` | Cost ceilings + `killswitch:chat`. Paid tokens no longer unlimited. |

Earlier this stretch (still uncommitted on `dev`): Foundry client + Azure billing block; lookup rate limits; CORS; magic-link hardening; entitlements SQLite; email+password accounts (`/auth/signin`, `/auth/register`); guest 3 / signed-in 5.

This Cursor chat (**Stored-answer chat**): classify-then-Redis replies; Sonnet-first build mint + class nicknames; dungeon wiki dumps (no Claude essay); shiny-divine stored hit; $7 + PAYG spend cap; daily quests; account-scoped chats/quests; whole-card zoom; highest-stat top pet; What's new changelog. Enchantment/DPS files started, not wired into warm or tests.

Run `pip install -r api/requirements-dev.txt` then `pytest` from repo root.

Decisions already made: per-user accounts in one deployment; managed auth; $7 + PAYG (not a $10 sticker); Pro included Claude = 68 (~$2.50), daily fuse = 50; anonymous free tier keyed on IP (3) vs signed-in (5); Azure-native deploy; SQLite until Azure Postgres; session in httpOnly cookies; global daily spend cap (~$20/month); 70/30 stored/Claude as the success metric.

Do not continue Entra in a depleted session. Start the next one by reading this file, then Enchantment wiring + tests.
