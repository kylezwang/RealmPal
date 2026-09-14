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

1. Entra External ID - **MSAL sign-in built** (Sep 13) on `feature/entra-auth` (branched off `master`, `dev` untouched). Next: manually test the real redirect round-trip with real `.env.local` values, build IGN collection for a first-time Entra sign-up, then merge.
2. Launch on a direct `ANTHROPIC_API_KEY` now (decided Sep 13); swap to Foundry once the Azure billing review clears, don't hold deployment on it.
3. Enable the Stripe Customer Portal in the Dashboard (Settings → Billing → Customer portal), one-time toggle, so the new "Manage subscription" button in `BillingModal.tsx` works outside test mocks.
4. Container Apps + Key Vault for the actual Azure deploy, once Entra sign-in is merged.

**Enchantment specialist is done** (wiring + implied-stat inference + tests, Sep 13). See `CHANGELOG.md` [2026.09.13] for detail.

**Stripe checkout → webhook → entitlement audit is done** (Sep 13): found and fixed a real bug (guest checkout emails only in `customer_details.email` were silently dropped) and shipped a self-service Stripe Customer Portal link. See `CHANGELOG.md` [2026.09.13] for detail.

**Production branch is set up** (Sep 13): `master` is production (protected: PR required, no force-push/delete, enforced for admins too), `dev` is the normal working branch with no protection. `master` was fast-forwarded to `dev`'s tip so it's not stale anymore. Promote a deploy by opening a PR `dev` → `master` and merging it, there's no more direct-push path.

## History
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

### Azure Foundry — code done, blocked on Azure billing account review

Chat client is finished in `api/services/llm.py` and doesn't need more work. `_stream_response` picks Foundry when `FOUNDRY_RESOURCE`/`FOUNDRY_BASE_URL` is set (endpoint allowlisted to `https://<resource>.services.ai.azure.com/anthropic`, Entra or a Foundry key, never both), otherwise falls back to `ANTHROPIC_API_KEY`. CCU-aware spend logging, `/health` reporting `provider`, startup warnings on a raw key in prod — all in.

**Deployment fails in the portal**: both `claude-sonnet-4-6` and `claude-sonnet-4-5` deployments show `Provisioning state: Failed`, with "This purchase cannot be completed" from Azure Marketplace. Root cause found: **the Azure billing account (Kyle Wang) is "Under Review" / inactive** — Cost Management + Billing → Billing scopes → that account shows "Your account is under review... buying new products and services... will be restricted until the review is complete." Marketplace can't fulfill any paid model purchase while that's true. This is Microsoft-side, not a RealmPal config problem — resource providers, region (confirm East US 2 / Sweden Central), and subscription type are all fine; the account itself is locked.

Do not keep retrying deployments — each attempt just fails the same way. Resume when:
1. Billing account review clears (check Cost Management + Billing → Billing scopes → account status), or
2. Support resolves it directly.

Then: subscribe the `claude-sonnet-4-6-ccu-plan` Marketplace offer (not `-plan-new`), deploy, paste resource name into `.env`, confirm one live stream logs `provider=foundry` and a `cost_ccu` value.

---

## Next Up

### Entra External ID — portal done, MSAL sign-in built on a side branch, not merged yet

**Portal (done Sep 13):** External tenant `RealmPal`, apps `RealmPal API` + `RealmPal Web` (SPA, single-tenant), user flow email+password collecting email only. Values in `.env`: tenant ID, SPA client ID, API client ID, `AUTH_JWKS_URL`, `AUTH_ISSUER`, `AUTH_AUDIENCE`, `ENTRA_USER_FLOW`. Backend `api/identity.py` already verifies JWKS tokens when `auth_configured` is true, and already tried first (before the local session JWT) in `api/dependencies.py`'s `get_optional_user` - no backend changes were needed for any of this.

**Built on `feature/entra-auth` (branched off `master`, Sep 13), not merged into `dev` or `master` yet:**
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

## Done (Sep 13, 2026) — See CHANGELOG.md for Technical Details

The following were completed and archived:

**Enchantment specialist** — LangGraph slot next to weapon/ability/armor/ring. Reads RealmEye `/wiki/enchanting` tables + Umi BIS notes. Infers the implied stat from an item's own base stat (or a class's dominant scaling stat for stat-less full builds) when the user doesn't name one.

**Stored answers** — Redis caching of drops, builds, dungeon guides, shiny items. Specialist warming system. 70/30 stored/Claude as success metric.

**Daily quests** — Rotating dungeon/player/shiny item, persistent per-user, grant +1 message/day via `POST /chat/quests/claim`.

**Pay-as-you-go billing** — 68 included Claude/mo (~$2.50), $0.08 overage, user spend cap, Stripe Link payment method.

**Stripe audit + Customer Portal** — Full checkout → webhook → entitlement review. Fixed a real bug: guest-checkout emails only present in `customer_details.email` were silently dropped, no entitlement created. Added self-service "Manage subscription or cancel" via `stripe.billing_portal.Session` (`POST /payments/portal`), gated on enabling the Portal once in the Stripe Dashboard.

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

### DPS specialist (started)

Wiki formula + RealmShark loadouts as reference. Files exist; same wiring pattern the Enchantment specialist used (warm store, build-knowledge injection, chat RAG skip, tests).

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

