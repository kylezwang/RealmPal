# Backlog

Last updated: 9/13/26

Target platform: **Azure**. Chosen for portfolio reasons — it's screened for by the
enterprise half of the roles being targeted, and invisible to the startup half.
Container Apps for compute (the API needs a real container for Playwright, which
rules out serverless), Entra External ID for identity, Key Vault for secrets.
SQLite on a mounted volume until billing lands, then Azure Postgres.
**Claude via Microsoft Foundry**, not a generic Anthropic API key (see below).

**See `.cursor/rules/development-workflow.mdc`:** Completed work moves from here → CHANGELOG.md (technical details) → git history. BACKLOG looks forward only; don't keep stale copy.

Resume order when context is fresh:

1. **Finish Enchantment specialist** - 4 wiring tasks (warm, RAG, skip, tests).
2. Entra External ID - needs portal values (tenant/client IDs).
3. Foundry - **blocked**, see Blocked section below. Don't retry deployment until billing clears.

---

## In Progress

### Enchantment specialist (started Sep 13, not finished)

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

---

## Blocked

### Azure Foundry — code done, blocked on Azure billing account review

Chat client is finished in `api/services/llm.py` and doesn't need more work. `_stream_response` picks Foundry when `FOUNDRY_RESOURCE`/`FOUNDRY_BASE_URL` is set (endpoint allowlisted to `https://<resource>.services.ai.azure.com/anthropic`, Entra or a Foundry key, never both), otherwise falls back to `ANTHROPIC_API_KEY`. CCU-aware spend logging, `/health` reporting `provider`, startup warnings on a raw key in prod — all in.

**Deployment fails in the portal**: both `claude-sonnet-4-6` and `claude-sonnet-4-5` deployments show `Provisioning state: Failed`, with "This purchase cannot be completed" from Azure Marketplace. Root cause found: **the Azure billing account (Kyle Wang) is "Under Review" / inactive** — Cost Management + Billing → Billing scopes → that account shows "Your account is under review... buying new products and services... will be restricted until the review is complete." Marketplace can't fulfill any paid model purchase while that's true. This is Microsoft-side, not a RealmPal config problem — resource providers, region (confirm East US 2 / Sweden Central), and subscription type are all fine; the account itself is locked.

Do not keep retrying deployments — each attempt just fails the same way. Resume when:
1. Billing account review clears (check Cost Management + Billing → Billing scopes → account status), or
2. Support resolves it directly.

Then: subscribe the `claude-sonnet-4-6-ccu-plan` Marketplace offer (not `-plan-new`), deploy, paste resource name into `.env`, confirm one live stream logs `provider=foundry` and a `cost_ccu` value.

---

## Next Up After Enchantment

### Entra External ID — research done, portal setup pending

Researched, not yet built. User will provide portal values (tenant ID, client IDs, JWKS URL). Sign-in methods: **Google + email OTP** (known Google bug; decision to make: keep Google and force `prompt=select_account`, or use email OTP only).

**What's needed from you:**
- Portal setup steps in `docs/DEPLOYMENT_GUIDE.md` (already provided Sep 13)
- Copy 7 values into `.env`
- Code integration once values are in place

Backend is already prepared: `api/identity.py` verifies JWKS-signed tokens. Frontend holds session in httpOnly cookies and forwards Bearer token. No additional verification code needed.

**Findings:**
- Two app registrations (API + SPA), not one
- Authority: `ciamlogin.com` (not `login.microsoftonline.com`) for CIAM
- Google bug: unsupported `username` parameter during silent renewal (12–24h after first sign-in)

Portal values to collect: tenant ID, SPA client ID, API client ID / Application ID URI, JWKS URL, issuer, audience.

---

## Done (Sep 13, 2026) — See CHANGELOG.md for Technical Details

The following were completed and archived:

**Stored answers** — Redis caching of drops, builds, dungeon guides, shiny items. Specialist warming system. 70/30 stored/Claude as success metric.

**Daily quests** — Rotating dungeon/player/shiny item, persistent per-user, grant +1 message/day via `POST /chat/quests/claim`.

**Pay-as-you-go billing** — 68 included Claude/mo (~$2.50), $0.08 overage, user spend cap, Stripe Link payment method.

**Email+password auth** — Local SQLite (PBKDF2-SHA256), fallback to magic-link. Primary sign-in method until Entra.

**Account-scoped history** — Chats & quests keyed per email, separate from guest sessions. LocalStorage persistence.

**Card zoom** — Sprites & full cards clickable → centered modal with RealmEye link.

**Top pet detection** — Highest RealmEye ability sum, not first slot.

**Sidebar improvements** — Collapsible quick-suggestion prompts, daily quests progress bar.

**Lookup rate limiting** — 12/min anon, 40/min signed-in on `/players`, `/items`, `/dungeons`, `/skins/render`, `/sprite`.

**Magic-link hardening** — Separate `MAGIC_LINK_SECRET`, single-use via Redis `SET NX`, no link logging.

**CORS hardening** — Only `app_url` unless `DEBUG=true`.

**What's new changelog** — User-facing UI with first-load popup, wired to settings page.

**Multi-tenancy foundation** — `DEPLOYMENT_NAMESPACE` for Redis & Qdrant scoping; entitlements SQLite store; subscription lookup on every JWT; fails open for unknown emails.

**Security hardening** — Server-issued JWTs, real entitlement checks, lookup rate limits, input sanitization, CORS/CSURF, cost budgets.

See `CHANGELOG.md` [2026.09.13] for commits, migrations, tests, and technical detail.

---

## Future (Planned, Lower Priority)

### DPS specialist (started, lower than Enchantment)

Wiki formula + RealmShark loadouts as reference. Files exist; same wiring as Enchantment. Finish Enchantment first.

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

---

## Documentation & Rules

**Changelog structure:**
- `CHANGELOG.md` — Developer changelog (technical, breaking changes, migrations)
- `web/lib/changelog.ts` — User-facing changelog (app UI only)
- `.cursor/rules/changelog.mdc` — Enforce user-facing entries on every deploy
- `.cursor/rules/development-workflow.mdc` — NEW: Separates BACKLOG (forward), CHANGELOG (completed), UI changelog

**Doc history:**
- `.cursor/rules/doc-history.mdc` — Keep dated prior text when updating BACKLOG, CHANGELOG, README, or docs/

**Project structure:**
- `BACKLOG.md`, `README.md` at root (high-level, visible)
- All other docs in `docs/` folder
- `docs/pricing.md` and `docs/business.md` gitignored (business logic)

**Related references:**
- `docs/DEPLOYMENT_GUIDE.md` — Exact Azure portal steps
- `docs/DEPLOYMENT_QUICK_REFERENCE.md` — Commands & timeline
- `docs/DEPLOYMENT_ARCHITECTURE.md` — Infrastructure diagrams
- `docs/chat-quality-benchmarks.md` — Traces & stored-answer map
- `docs/pricing.md` (gitignored) — Unit-econ, hosting costs, break-even
- `docs/README.md` — Doc structure & audience guide

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
- Google SSO silent renewal bug in Entra (12–24h after first sign-in). Decision pending.
- Infrastructure lockdown pending (Redis/Qdrant credentials, docker-compose → Container Apps)
- Prompt-injection defense weak (regex denylist; should be stronger)

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

