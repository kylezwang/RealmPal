# Backlog

Last updated: 9/11/26

Target platform: **Azure**. Chosen for portfolio reasons — it's screened for by the
enterprise half of the roles being targeted, and invisible to the startup half.
Container Apps for compute (the API needs a real container for Playwright, which
rules out serverless), Entra External ID for identity, Key Vault for secrets.
SQLite on a mounted volume until billing lands, then Azure Postgres.
**Claude via Microsoft Foundry**, not a generic Anthropic API key (see below).

Resume order when context is fresh:

1. **Finish Enchantment specialist** — scrape + slot agent exist; warm, chat inject, and tests do not. No portal/blocked dependency.
2. Entra External ID — needs portal values (tenant/client IDs).
3. Foundry — **blocked**, see below. Don't retry deployment until the billing account clears review.

Wiki specialist stores, item-card cache, and class-wearable grids landed this session. Remaining security/multi-tenancy items are small and not blocking: infra lockdown wiring for a real deploy, a stronger prompt-injection defense than a denylist, Key Vault migration, per-user Qdrant filtering.

Do not start Entra mid-session. Enchantment is already half-built — finish that wiring, don't start a third specialist.

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

Starting traces for token + factual quality. More logs incoming.

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
| Best items for a Mana mystic (after warm) | 11,041 / 1,065 | $0.0491 | Fast chat. Item cards still live-scraped — they read `item:profile:v2` while warm wrote v3. Fixed; cards now prefer v3. |
| Best items for a Wis Kensei (after v3 + warm) | 8,906 / 994 | $0.0416 | Chat + almost every card from Redis. Only Rift Rippers scraped. Grid showed Ninja leather (Hirejou Tenne, Venerable Coral Silk, Centaur's Shielding). Grid now filters `wearable=false`; comparison prose stays. |

**HMS fact to keep:** after the purple dome (the Source) on the clear to Nox (2nd boss), drag all 4 branches/flames to the center. “Wings” is regular The Shatters, not Hardmode.

Local tester: signed-in IGN **Turbine** skips chat + lookup quotas while `DEBUG=true` (`DEBUG_UNLIMITED_IGNS`).

---

## Other notes

- Flutter mobile app (iOS + Android)
- Guild page lookups
- ~~Scheduled wiki re-scraping~~ **Done** (weekly Action + `refresh_wiki`). Player profiles stay live on request.
- Real email provider for magic-link login (Resend)
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

This Cursor chat: specialist wiki warm (startup + weekly Action); item cards read `item:profile:v3` (apostrophe-safe); boot does not re-scrape a near-full store; Babel Blocks skipped; item-card grid hides unequippable class gear; sign-in form centered in the dark panel. Enchantment/DPS files started, not wired into warm or tests.

Run `pip install -r api/requirements-dev.txt` then `pytest` from repo root.

Decisions already made: per-user accounts in one deployment; managed auth; billing deferred; anonymous free tier keyed on IP (3) vs signed-in (5); Azure-native deploy; SQLite until billing; session in httpOnly cookies; global daily spend cap (~$20/month).

Do not continue Entra in a depleted session. Start the next one by reading this file, then finish Enchantment wiring + tests.
