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
- **Lookup 429s on HMS guides**: `/items` no longer burns 12/min scrape window on warmed Redis hits
- **Item card fan-out**: Stored guide briefs strip `[item:]` hooks; cannot enqueue 20+ card fetches
- **Stored hits don't move chat to top**: Changed from always re-ordering sessions to keeping chronological order; only move when message count increases (new message added)
- **Dungeon quest icons**: Show correct portal sprites (purple dome for Shatters, not ice portal)
- **Shiny quest**: Only shows star badge if item actually has a shiny version

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
- **Documentation restructure**: Moved detailed pricing/benchmarks to `docs/pricing.md` (gitignored) and `docs/chat-quality-benchmarks.md`
- **Tests**:
  - `pytest api/tests/test_claude_billing.py`: Verify 68-pool exhaustion, overage billing, stored-hit metering skip
  - `pytest api/tests/test_stored_answers.py`: Paid stored hit does not increment Claude meter, second identical ask is cache hit, constrained follow-up streams

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
1. **Enchantment specialist**: Wire 4 remaining tasks (warm integration, RAG injection, wiki skip, tests)
2. **Entra External ID**: Collect portal values; portal setup documented in `docs/DEPLOYMENT_GUIDE.md`
3. **Container Apps + Key Vault**: Infrastructure for Azure deploy
4. **PostgreSQL migration**: After Foundry unblocked
5. **Per-user Qdrant filtering**: Low priority (currently holds only public scraped data)

---

## [Unreleased] - Work in Progress

### Planned
- **Enchantment specialist** (started, not wired): Isolate enchant-only questions; read RealmEye `/wiki/enchanting` tables and Umi BIS notes
- **DPS specialist** (started, low priority): Wiki formula + RealmShark loadouts as reference
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

