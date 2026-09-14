# Backlog

Last updated: 9/14/26 (12:21 AM)

Target platform: **Azure**. Chosen for portfolio reasons — it's screened for by the
enterprise half of the roles being targeted, and invisible to the startup half.
Container Apps for compute (the API needs a real container for Playwright, which
rules out serverless), Entra External ID for identity, Key Vault for secrets.
SQLite on a mounted volume until billing lands, then Azure Postgres.
**Claude via Microsoft Foundry**, not a generic Anthropic API key (see below).

**See `.cursor/rules/development-workflow.mdc`:** Completed work moves from here → CHANGELOG.md (technical details) → git history. BACKLOG looks forward only; don't keep stale copy.

Resume order when context is fresh:

1. **CRITICAL, not yet fixed - embeddings backend unreachable in production, silently breaking all RAG** (found Sep 14, ~12:15 AM, during a live post-deploy smoke test). `api/services/embeddings.py`'s `EMBEDDING_BACKEND` env var defaults to `"ollama"`, pointing at `OLLAMA_URL=http://localhost:11434` - there is no Ollama server anywhere on the Container App, so every embedding call fails with `httpx`'s generic `All connection attempts failed`. This is NOT a narrow/contained issue - it breaks:
   - `retrieve_context` (`api/routers/chat.py` ~line 647): every non-specialist chat question answers with `context = ""` (caught by the broad `except Exception` at line 660, logged as "RAG context retrieval failed, answering without retrieved context"), i.e. **every chat reply that isn't a dungeon/player/enchant-only specialist turn runs with zero retrieved wiki context**, silently, no error surfaced to the user.
   - `ingest_player` (`api/routers/players.py` line 57, `api/routers/chat.py` line 601): every player-profile scrape logs "Could not ingest player profile into RAG store" and never writes to Qdrant - **note this corrects an earlier same-day (Sep 13) CHANGELOG.md note that called this "unrelated and non-fatal by design" after ruling out client-recreation as the cause; that part was right (client is `@lru_cache`'d, not recreated per request) but the conclusion was incomplete - it stopped one layer too shallow and didn't catch that the embeddings call itself (needed before the Qdrant write) was the actual dead end.**
   - Reproduced live Sep 14: asked "How to do moonlight village?" and "Battle for the Nexus" (a dungeon slug already confirmed cached in Redis per the same night's warm log) and got "I don't have dungeon guide data... in the context provided" for both - strongly suggests dungeon-guide retrieval also leans on this same embeddings path (likely a semantic match from the freeform dungeon name to a wiki slug), not just the generic RAG block.
   - **Root cause confirmed, fix path decided (Sep 14): the Qdrant Cloud collection was seeded using Ollama's `nomic-embed-text` embeddings** (confirmed with the user directly - `EMBEDDING_BACKEND` was left at its default when `python -m api.scripts.seed_wiki` (39 hubs) and `seed_dps` (36 builds) were run locally in Sep 13's session). Flipping just the Container App's `EMBEDDING_BACKEND` to `voyage` would run production queries in `voyage-3-lite`'s vector space against Ollama-embedded vectors - not just broken, but silently *wrong* (would return semantically nonsensical matches instead of an obvious error). Cannot fix by env var alone.
   - **Decided Sep 14, ~8:20 AM: go with Voyage, not self-hosted Ollama.** Priced out self-hosting: `nomic-embed-text` needs to stay warm 24/7 (no scale-to-zero, chat needs embeddings synchronously), realistically costing ~$25-70/mo in Azure Container Apps compute (1.0-1.5 vCPU / 2-3 GiB running mostly-idle at $0.000008/vCPU-sec + $0.000001/GiB-sec idle rates) just to avoid a service (Voyage) that's free at this project's scale (200M free tokens, one-time, never expires). Not worth it.
   - **Code fixed Sep 14, ~8:25 AM (commit `6f77324`, on `dev`, not yet in a PR to master):** the code had never actually been run against Voyage and carried a wrong, unverified assumption - it called `voyage-3-lite` and assumed it shared Ollama's 768-dim vector space. Neither is true (voyage-3-lite is fixed at 512 dims; no Voyage model outputs 768). Switched to `voyage-4-lite` (same $0.02/M price, but covered by the 200M free-token grant - `voyage-3-lite` predates that grant and gets none) and made `VECTOR_SIZE` derive from the active backend (768 Ollama / 1024 Voyage's default `output_dimension`) instead of a hardcoded 768 duplicated in two files. This commit alone has no runtime effect yet (`EMBEDDING_BACKEND` still defaults to `"ollama"`).
   - **Exact next steps (picking up here):**
     1. Sign up for a Voyage AI API key at voyageai.com (next action, in progress Sep 14 ~8:25 AM).
     2. **Delete the existing Qdrant collection before re-seeding** - this step wasn't in the original plan and matters: the live collection is 768-dim (Ollama), Voyage's `voyage-4-lite` outputs 1024-dim by default, and `ensure_collection()` (`api/services/ingestion.py`) only creates a collection if the name doesn't already exist yet, it will NOT resize an existing one. Re-seeding without deleting first would try to upsert 1024-dim vectors into a 768-dim collection, which Qdrant will reject. Delete via the Qdrant Cloud dashboard (Clusters -> `realmpal` -> Collections -> the collection named by `qdrant_collection`/`QDRANT_COLLECTION` in `.env`, currently `realm_pal` -> Delete), or `await client.delete_collection(name)` in a one-off script.
     3. Set `EMBEDDING_BACKEND=voyage` and `VOYAGE_API_KEY=<key>` in the local `.env` temporarily (just for re-seeding).
     4. Re-run `python -m api.scripts.seed_wiki` and `python -m api.scripts.seed_dps` locally (same `QDRANT_URL`/`QDRANT_API_KEY` as before, pointing at the same Qdrant Cloud cluster) - `ensure_collection()` will recreate the collection fresh at 1024 dims since it's gone now, then seed into it with Voyage embeddings.
     5. Set the same `EMBEDDING_BACKEND=voyage` + `VOYAGE_API_KEY` as Container App environment variables (Portal: Container Apps -> `realmpal-api` -> Containers -> Edit and deploy -> Environment variables tab -> Add), which creates a new revision.
     6. Smoke test: ask a dungeon question (e.g. "how to do moonlight village") and a build question, confirm the reply actually cites real context and doesn't say "I don't have ... in the context provided". Check the log stream for "RAG context retrieval failed" / "Could not ingest ... into RAG store" - both should disappear.
   - Also worth deciding while there: is there other Qdrant-backed content beyond wiki hubs + DPS loadouts (e.g. live-ingested player profiles, item data) that also needs a one-time re-embed, or that self-heals since it's ingested fresh on every live scrape? Check `api/services/ingestion.py` for every `qdrant.upsert` call site before assuming the two seed scripts are the complete list.
2. **Fixed Sep 14 (~12:20 AM): Claude's generic wiki-referral citations were triggering doomed item scrapes.** `web/lib/itemLookup.ts`'s `extractItemNames()` treated *any* `[text](.../wiki/...)` markdown link as a real item/dungeon name, including Claude's own fallback text like `[RealmEye wiki dungeon page](.../wiki/realmeye-wiki-dungeon-page)` when it lacked real context (itself a symptom of bug #1 above - Claude falls back to this phrasing more often when it has no retrieved context to cite from). This fired a frontend `fetchItem()` for a name that could never exist, and the backend then burned 15-30s of the single shared Playwright semaphore (see #4 below) trying and retrying a scrape of a URL that was never real, worsening contention for every concurrent user. Filtered out generic referral words (`wiki`/`page`/`guide`/`directly`/`article`) since no real item/dungeon/set name contains them. Committed `9ceb1de` on `dev`, PR'd to `master`: https://github.com/kylezwang/RealmPal/pull/9 (not yet merged as of Sep 14, ~12:21 AM).
3. **Azure Static Web App for `web/` is live and confirmed working end to end** (Sep 13 night into Sep 14): deployed, `NEXT_PUBLIC_API_URL` wired via GitHub secret, `EXTRA_CORS_ORIGINS` wired on the API, "Failed to fetch" on sign-in/register fixed, and a real account (`Turbine`) successfully registered/signed-in/chatted against the live site (confirmed via Container App logs, not just a screenshot). See CHANGELOG.md `[2026.09.13]` for full technical detail. What's left from the original plan below: nothing blocking, this item is done.
4. **Diagnosed, not yet fixed - CPU/semaphore contention (`_PW_SEM = asyncio.Semaphore(1)` in `api/services/scraper.py`) causes slow-to-the-point-of-looking-broken pet/dungeon/skin lookups.** Reconfirmed live Sep 14: a fresh pet lookup after a redeploy took 16-40+ seconds while specialist warming was mid-run competing for the same single-Chromium-page semaphore; the sidebar correctly said "No pet found yet" the whole time (this is accurate loading state, not a display bug - confirmed by checking `PetCompanion.tsx`/`ChatInterface.tsx`'s `loadPlayer`/`setPlayerProfile` wiring, no bug found there), and the pet displayed correctly the moment warming finished (`Specialist stores warmed` logged) and the semaphore freed up. Every redeploy interrupts the warm queue's dungeon-guide pass before it reaches all 179 slugs (171/179 cached as of the last full pass, Sep 13 night), so back-to-back redeploys in one session compound this. Action still pending (Azure Portal: Container Apps -> `realmpal-api` -> Scale and revisions -> Edit and deploy -> Container tab -> CPU and Memory): bump from 0.5 vCPU / 1 GiB to 1.0 vCPU / 2 GiB, then avoid unnecessary redeploys until one warm pass runs to completion uninterrupted.
5. **Also observed Sep 14, not yet fixed - every chat message unconditionally scrapes+ingests the signed-in user's own IGN profile**, even for messages with nothing to do with the player (`api/routers/chat.py`, `if body.ign:` block, ~line 588 - "Player profiles change constantly, scrape on lookup" comment explains the *intent* but this fires on every uncached message regardless of whether the message needs it, e.g. a pure "how to do X dungeon" question). Confirmed in the same Sep 14 logs: asking about Moonlight Village still triggered a 14s `Scraping player profile {'username': 'Turbine'}` call. This directly adds to item #4's semaphore contention. Worth reconsidering: only scrape when `player_only`/`buildish` is true for *this* message (the router already computes these flags for the RAG-skip logic right below it), not unconditionally whenever `body.ign` is set.
6. **Not yet investigated - skin/outfit visualizer scraper bug, independent of CPU contention.** `scrape_outfit_catalog()`'s `https://www.realmeye.com/top-characters-with-outfit` fetch fails the same way every time it was tried Sep 13-14, warm or not: `locator(".chooser-table, #class")` resolves to 2 elements (ambiguous - "Proceeding with the first one" logged), then still times out waiting 20s x 2 retries. This isn't slowness, it's a real scrape-target bug (RealmEye likely changed that page's markup) that fully breaks the "what does skin X look like with clothing Y" feature - confirmed via a live "Vampire Slayer Archer with Large/Small Crown cloth" request returning blank skin/clothing/accessory boxes and a 404 from `/skins/render`. Needs the actual page inspected (view-source or a Playwright trace) to find the right selector, not just retried.
7. **Azure Static Web App for `web/`, in Static (not Hybrid) mode**: no
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

   **Done as of Sep 14 - see item 3 above.** Kept here (not deleted) per
   `doc-history.mdc` since this was the original plan text, not just a
   status update.
8. **Key Vault**: move the env vars pasted into the Container App (JWT
   secret, Stripe key, `DATABASE_URL`, `REDIS_URL`) into Key Vault
   references instead of plaintext. Priority 5 in the deploy guide.
9. **Production secrets review**: the deployed Container App's log stream
   shows `PII_HASH_SECRET is unset` and `MAGIC_LINK_SECRET is unset`
   warnings (Sep 13) - both are silently falling back to `JWT_SECRET`. Set
   both explicitly and rotate `JWT_SECRET` off its local-dev value before
   real launch.
10. **Stripe live mode**: test mode is fully verified end to end (Sep 13, see Done below). Before real launch: repeat the same setup in Live mode (dashboard toggle top-right) - live secret key into `.env`, rerun `python -m api.scripts.ensure_stripe_price` for the live-mode price, re-enable the Customer Portal toggle (it's a separate on/off per mode), and point the webhook endpoint at the real production URL.
11. **Entra External ID**: MSAL sign-in built on `feature/entra-auth` (Sep 13), but hit a "failed fetch" error in manual testing. Deprioritized for now (not blocking launch, decided Sep 13), come back to it after Container Apps.
12. Launch on a direct `ANTHROPIC_API_KEY` (decided Sep 13); swap to Foundry once the Azure billing review clears, don't hold deployment on it.

## History
### Until Sep 14, 2026, 12:21 AM (this revision)
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

**`api/Dockerfile` created and the API image built + pushed** (Sep 13): there
was no Dockerfile at all before this (docker-compose referenced one that
didn't exist). Built on `mcr.microsoft.com/playwright/python` so Chromium +
every OS-level dep the scraper needs ships in the image. Registry created as
`realmpalacr` in a fresh `rg-realmpal` resource group (not the old, broken-
Foundry `rg-certio`). Also found and fixed local disk at 0.43 GB free
(Docker's storage went read-only mid-build) - cleared Temp, pruned Docker's
build cache and two unrelated old images, back to a healthy ~12 GB free.

**Enchantment specialist is done** (wiring + implied-stat inference + tests, Sep 13). See `CHANGELOG.md` [2026.09.13] for detail.

**Stripe checkout → webhook → entitlement audit is done** (Sep 13): found and fixed a real bug (guest checkout emails only in `customer_details.email` were silently dropped) and shipped a self-service Stripe Customer Portal link. See `CHANGELOG.md` [2026.09.13] for detail.

**Stripe test mode fully verified working end to end** (Sep 13): `STRIPE_SECRET_KEY` and `STRIPE_PRICE_ID` in `.env` had never actually been filled in, both were still the literal `.env.example` placeholder text (`sk_test_...` / `price_...`), which `stripe_configured` correctly refused to treat as real. Real test secret key pasted in by hand; `api/scripts/ensure_stripe_price.py` auto-created the "RealmPal Pro" $7/mo test-mode price and wrote `STRIPE_PRICE_ID`. Confirmed via a real Checkout (test card `4242 4242 4242 4242`) that entitlement activation and the Customer Portal button both work. **Still test mode only**, see item 4 above for what live mode needs.

**Production branch is set up** (Sep 13): `master` is production (protected: PR required, no force-push/delete, enforced for admins too), `dev` is the normal working branch with no protection. `master` was fast-forwarded to `dev`'s tip so it's not stale anymore. Promote a deploy by opening a PR `dev` → `master` and merging it, there's no more direct-push path.

**Azure infra provisioned and the API is fully live** (Sep 13): Azure Managed Redis (`realmpal-cache`), Azure Database for PostgreSQL Flexible Server (`realmpal-db`), and the Container Apps Environment + Container App (`realmpal-api`) all created in `rg-realmpal`, East US 2. Took 7 revisions to get clean: a missing `ANTHROPIC_API_KEY` (crashed on startup with a clear pydantic error), `scan_iter` not being classified in `api/redis_namespace.py` (a real code bug, raised in every namespaced deployment since local dev's default namespace is empty and never exercised this path until `DEPLOYMENT_NAMESPACE=prod` was actually set), then four straight `DATABASE_URL` connection-string issues in a row (password's `@` breaking DSN parsing, missing firewall rule for the Container App's outbound IP, missing `:5432/realmpal?sslmode=require` suffix, and the `realmpal` database itself never having been created). `/health` returns `200`, Postgres/Redis/Qdrant all connect clean, specialist warming is scraping RealmEye and populating stores in the background. See `CHANGELOG.md` [2026.09.13] for full technical detail on each bug.

**`web/` simplified to a pure static export before its first deploy** (Sep 13): found and deleted two dead-code server dependencies (`app/api/chat/route.ts` proxy, `/api/sprite` rewrite) that were the only reason `output: "standalone"` (hybrid hosting) looked necessary; the frontend already calls the Container App directly for everything, including chat streaming. Switched to `output: "export"`. See `CHANGELOG.md` [2026.09.13] for detail.

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

