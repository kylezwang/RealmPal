# Changelog

All notable changes to RealmPal are documented here. This is the **developer changelog** (technical details, internal changes, breaking changes, migrations). 

**Related files:**
- **User-facing changelog:** `web/lib/changelog.ts` — rendered in the app UI ("What's new" modal, first-load popup, settings page)
- **Product decisions:** `BACKLOG.md` — high-level roadmap, current priorities, research notes
- **Deployment guide:** `docs/DEPLOYMENT_GUIDE.md` — exact Azure portal steps

Format: each version has technical notes, linked commits, migration guides (if needed), and internal changes not exposed to users.

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

### Internal
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
1. **Entra code integration**: MSAL SPA sign-in against the now-configured `RealmPal` tenant; swap (or complement) local email+password with Entra-issued tokens
2. **Enable Stripe Customer Portal in the Dashboard**: Settings → Billing → Customer portal, one-time toggle, required before the new `/payments/portal` endpoint works outside test mocks
3. **Container Apps + Key Vault**: Infrastructure for Azure deploy
4. **PostgreSQL migration**: After Foundry unblocked
5. **Per-user Qdrant filtering**: Low priority (currently holds only public scraped data)

#### History
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

