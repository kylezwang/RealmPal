# RealmPal Azure Deployment Guide

**Last updated:** Sep 13, 2026  
**Target:** Production deployment with security, multi-tenancy, and managed auth

---

## PRIORITY 1: Unblock Azure Foundry (BLOCKER)

**Status:** Billing account under review — must clear before Foundry deployments work.

### Step 1: Check Billing Account Status

1. Go to **[Azure Portal](https://portal.azure.com)** → sign in with `Kyle Wang` account
2. Search for **"Cost Management + Billing"** (top search bar)
3. Click **"Billing scopes"** (left sidebar)
4. Look for your subscription in the list
5. Click on the subscription name to open its detail page
6. Check the **Account status** section:
   - **If status is "Active"**: proceed to Step 2 (you can skip this section)
   - **If status is "Under Review"**: wait for Microsoft email confirmation OR call Support

### Step 2: If Status Shows "Under Review"

**Contact Azure Support (do NOT retry deployments):**

1. In the same **Cost Management + Billing** page, look for **"Help + support"** (left sidebar)
2. Click **"Create a support request"**
3. Fill out:
   - **Summary:** "Billing account review blocking Foundry marketplace purchases"
   - **Issue type:** Billing
   - **Severity:** Medium (you can deploy non-Foundry resources)
   - **Description:** "Azure billing account is under review and cannot purchase marketplace models (Claude Sonnet 4.6 via Foundry). Can this be expedited?"
4. Submit and wait for response

**Expected wait:** 24–48 hours. In the meantime, proceed to sections 2–6 below (all can run without Foundry).

### Step 3: Once Billing Review Clears

1. Return to **Azure Portal** → **Cost Management + Billing** → **Billing scopes** → confirm status is "Active"
2. Search for **"Azure AI Services"** (top search bar)
3. Create a new resource:
   - **Resource group:** Create new or use existing (e.g., `realmpal-prod`)
   - **Region:** East US 2 (or Sweden Central if US region issues arise)
   - **Name:** `realmpal-foundry` (or similar)
4. Once created, go to **Marketplace** inside the resource:
   - Click **"Models"** (left sidebar)
   - Search for **"Claude Sonnet 4.6"** (or latest Sonnet)
   - Click **"Deploy"**
   - Select **"claude-sonnet-4-6-ccu-plan"** (NOT `-plan-new`)
   - Accept terms and deploy
5. After deployment succeeds:
   - Copy the **Resource name** (e.g., `realmpal-foundry`)
   - Copy the **Endpoint URL** from **Keys and Endpoint** (looks like `https://realmpal-foundry.services.ai.azure.com/`)
6. Paste these into `.env`:
   ```
   FOUNDRY_RESOURCE=realmpal-foundry
   FOUNDRY_BASE_URL=https://realmpal-foundry.services.ai.azure.com/
   ```
7. Restart API and verify log shows `provider=foundry` on first chat

---

## PRIORITY 2: Enchantment Specialist Wiring - DONE (Sep 13, 2026)

**Status:** Complete. All 4 tasks below shipped same day; see `CHANGELOG.md`
[2026.09.13] "Enchantment specialist" for the actual diffs, tests, and the
implied-stat inference (`infer_item_base_stat`, `infer_class_primary_stat`)
added on top of this wiring. Steps kept below for reference only, they
describe what was built, not what's left to do.

**Why it matters:** Completes the specialist system before moving to Entra. Four precise tasks:

### Task 1: Wire Enchanting Store into Warm

**File:** `api/services/specialist_warm.py`

1. Find the `specialist_snapshot()` function (around line 100)
2. In the list of warm calls, add:
   ```python
   "enchanting": await warm_enchanting_store(redis_client, settings),
   ```
3. Find `missing_specialist_work()` function (around line 150)
4. Add to the `missing.append` checks:
   ```python
   if not await is_enchanting_store_warmed(redis_client):
       missing.append("enchanting")
   ```
5. Find `warm_all_specialists()` function (around line 200)
6. Add to the loop:
   ```python
   if "enchanting" in categories or not categories:
       await warm_enchanting_store(redis_client, settings)
   ```
7. Run CLI test: `python -m api.scripts.warm_specialists --status`
   - Should show `enchanting: warmed` or `enchanting: [count] items`

### Task 2: Inject Enchanting Brief into Chat RAG

**File:** `api/services/stored_answers.py`

1. Find `retrieve_build_knowledge()` function (around line 250)
2. After the line `if ask_kind == "build":`, add early return for enchant-only:
   ```python
   elif ask_kind == "enchant":
       return await retrieve_enchanting_brief(redis_client, prompt, settings)
   ```
3. On full builds, add enchanting context injection:
   ```python
   # After retrieving build context, add:
   enchant_brief = await retrieve_enchanting_brief(redis_client, prompt, settings)
   if enchant_brief:
       context += f"\n**Enchanting tips:** {enchant_brief}"
   ```

### Task 3: Skip Extra Wiki RAG on Enchant-Only Questions

**File:** `api/routers/chat.py`

1. Find the section that does RAG retrieval (around line 300)
2. Before `rag_results = await rag.retrieve(...)`, add:
   ```python
   if ask_kind == "enchant":
       # Skip extra wiki RAG for enchant-only questions; brief is enough
       rag_results = []
   else:
       rag_results = await rag.retrieve(...)
   ```

### Task 4: Add Tests for Enchanting

**File:** `api/tests/test_stored_answers.py`

Add three new test functions:

```python
async def test_enchant_question_retrieves_brief(redis_client, anon_settings):
    """Test 'what enchants on QOT' returns brief, no Claude."""
    # Mock redis with enchanting store
    # Call chat with "what enchants on Oreo of the Third"
    # Assert response is stored brief, not streamed

async def test_dex_roll_enchant_does_not_fire_on_wis_item(redis_client, anon_settings):
    """Test 'best DEX roll on Leaf Bow' does not suggest WIS enchants."""
    # Leaf Bow is WIS-only slot
    # Assert enchanting brief is DEX-relevant only

async def test_enchant_follow_up_still_calls_claude(redis_client, anon_settings):
    """Test constrained enchant follow-up ('no water') still streams."""
    # After stored "best DEX rolls on Leaf", ask "but not water"
    # Assert second call streams Claude, not retrieves
```

**Validation:** Run `pytest api/tests/test_stored_answers.py::test_enchant_question_retrieves_brief -v`

---

## PRIORITY 3: Entra External ID Portal Setup (NO CODE YET)

**Status:** Research done. Portal values needed before building Entra integration.

**Why it matters:** Multi-tenancy + managed auth (Google + email OTP). Do NOT code until you have portal values pasted back here.

### Step 1: Create the External Tenant (if not already created)

Reachable straight from the **Azure Portal**, from inside your existing
"Default Directory" (that's your **workforce** tenant, manages who on your
team can access Azure resources; it's just where this creation flow lives,
you're not configuring that tenant itself here).

1. **[Azure Portal](https://portal.azure.com)**, signed into your Default
   Directory
2. Open the **Microsoft Entra ID** blade → **Overview**
3. Click **"Manage tenants"**
4. Click **"Create"**
5. Select **"External"**, then **"Continue"** (URL will show
   `CreateDirectoryBlade/tenantType=ciam` when you're on the right page)
6. **Basics tab:**
   - **Tenant Name:** RealmPal Production
   - **Domain Name:** realmpal-prod (or similar; must be globally unique,
     becomes `<name>.onmicrosoft.com`; cannot be edited or deleted later,
     though a custom domain can be added afterward)
   - **Country/Region:** United States (also cannot be changed later)
7. Click **"Next: Add a subscription"**
8. **Add a subscription tab:**
   - **Subscription:** select your existing Azure subscription
   - **Resource group:** select one, or click **"Create new"** and name it
     `realmpal-prod` if none exists
9. Click **"Next: Review + create"**, confirm the details, then click
   **"Create"**
10. Provisioning can take **up to 30 minutes** (watch the Notifications bell,
    top right). Once done, switch into the new tenant via the **Settings**
    (gear) icon, top menu → **"Directories + subscriptions"** → select the
    new tenant

Once you're in the new external tenant, everything in Steps 2-6 below
(App registrations, API permissions, user flow) is done from that same
Entra ID blade, now scoped to the new tenant instead of the Default
Directory.

### Step 2: Create API Application Registration

1. In your CIAM tenant, search for **"App registrations"** (top search)
2. Click **"New registration"**
   - **Name:** RealmPal API
   - **Supported account types:** "Single tenant only - RealmPal" (customers sign in via a User Flow inside this tenant, not via their own separate Entra tenant or a personal Microsoft account, so this is single-tenant even though the end users are external customers)
   - **Redirect URI:** Leave blank for now
3. Once created, copy and save:
   - **Application (client) ID** → paste into `.env` as `ENTRA_API_CLIENT_ID`
   - **Directory (tenant) ID** → paste into `.env` as `ENTRA_TENANT_ID`
4. Click **"API permissions"** (left sidebar)
   - Click **"Add a permission"** → **"Microsoft Graph"** → **"Delegated permissions"**
   - Search for and add: `profile`, `email`, `openid`
5. Click **"Expose an API"** (left sidebar)
   - Click **"Add a scope"**
     - **Application ID URI:** Click "Set" → accept the default
     - **Scope name:** `access_as_user`
     - **Who can consent:** Admins and users
     - **Description:** Access RealmPal as the signed-in user
   - Copy the full scope (e.g., `api://[client-id]/access_as_user`) → save for Step 3

### Step 3: Create SPA Application Registration (Next.js Frontend)

1. Still in **App registrations**, click **"New registration"**
   - **Name:** RealmPal Web
   - **Supported account types:** "Single tenant only - RealmPal" (same reasoning as the API app above)
   - **Redirect URI:** platform dropdown → **"Single-page application (SPA)"** (not "Web"; SPA uses PKCE, no client secret) → `http://localhost:3000/auth/callback` (for local dev)
2. Once created, copy and save:
   - **Application (client) ID** → paste into `.env` as `ENTRA_WEB_CLIENT_ID`
3. Click **"Authentication"** (left sidebar)
   - Under the SPA platform's redirect URIs, click **"Add URI"** and also add the production URL once known, e.g. `https://realmpal.com/auth/callback`
   - Leave both "Implicit grant and hybrid flows" checkboxes unchecked
4. Click **"API permissions"** (left sidebar)
   - Remove any default permissions
   - Click **"Add a permission"** → **"My APIs"** → select **"RealmPal API"**
   - Check the `access_as_user` scope → **"Add permissions"**

**No client secret for this app.** SPAs are public clients (the code runs in the user's browser, so any embedded secret would be visible to anyone with dev tools open); MSAL uses PKCE instead. Do not create one here.

### Step 4: Get JWKS URL and Issuer

1. Open this URL directly in a browser (public JSON, no login needed),
   using your tenant ID copied via the copy-icon next to "Tenant ID" on
   the Entra ID Overview page (do not retype it by hand, see History below
   for why that matters):
   ```
   https://[tenant-id].ciamlogin.com/[tenant-id]/v2.0/.well-known/openid-configuration
   ```
2. Copy the value of `jwks_uri` → paste into `.env` as `AUTH_JWKS_URL`. For
   a CIAM tenant this resolves to
   `https://[tenant-id].ciamlogin.com/[tenant-id]/discovery/v2.0/keys`
   (not under `/v2.0/.well-known/...` like a workforce tenant's JWKS URL)
3. Copy the value of `issuer` → paste into `.env` as `AUTH_ISSUER`
   (`https://[tenant-id].ciamlogin.com/[tenant-id]/v2.0`)
4. Paste the API **client ID** again as `AUTH_AUDIENCE` in `.env`
5. Verify without printing secrets: `python -c "from api.config import
   Settings; print(Settings().auth_configured)"` should print `True`

### Step 5: Identity Providers (skip for MVP)

Email with password is a built-in local account method. No Identity
providers page setup is required. Skip Google for now (known silent-renewal
bug 12-24h after first sign-in). Add Google later under External Identities
→ All identity providers if needed.

### Step 6: Create Sign-In/Sign-Up User Flow

1. Search for **"User flows"** (left sidebar)
2. Click **"+ New user flow"**
   - **Type:** Sign up and sign in
   - **Name:** sign-up-sign-in
3. Configure:
   - **Identity providers:** Email accounts → **Email with password**
     (not OTP, not magic link; matches RealmPal's existing password UX)
   - **User attributes to collect:** **Email Address only**. Skip display
     name, given name, and surname; IGN is collected in-app
   - **Page layout:** default is fine
4. Once created, copy the flow name from the top of the page → paste into
   `.env` as `ENTRA_USER_FLOW`

### Step 7: Collect Portal Values for .env

Add these to `.env` (placeholders only; never paste real values into docs):

```bash
# Entra External ID (CIAM)
ENTRA_TENANT_ID=your-tenant-id
ENTRA_WEB_CLIENT_ID=your-spa-client-id
ENTRA_API_CLIENT_ID=your-api-client-id
AUTH_JWKS_URL=https://[tenant-id].ciamlogin.com/[tenant-id]/discovery/v2.0/keys
AUTH_ISSUER=https://[tenant-id].ciamlogin.com/[tenant-id]/v2.0
AUTH_AUDIENCE=your-api-client-id
ENTRA_USER_FLOW=sign-up-sign-in
```

No `ENTRA_WEB_CLIENT_SECRET`: the SPA registration is a public client (PKCE via
MSAL), see Step 3.

**Portal setup complete when** `Settings().auth_configured` is `True` and
`ENTRA_USER_FLOW` is set. Next work is code: MSAL SPA sign-in against this
user, then swap local email+password for Entra-issued tokens.

---

## PRIORITY 4: Azure Container Apps Setup

**Status:** Infrastructure ready. This hosts the FastAPI backend.

### Step 1: Create Container Registry

1. Go to **[Azure Portal](https://portal.azure.com)**
2. Search for **"Container registries"** (top search bar)
3. Click **"+ Create"**
4. **Basics tab:**
   - **Subscription:** your subscription
   - **Resource group:** click **"Create new"** → type `rg-realmpal` → **"OK"**
     (a fresh group, not the pre-existing `rg-certio` that an old, non-working
     Foundry resource lives in)
   - **Registry name:** `realmpalacr` (must be globally unique across all of Azure,
     lowercase letters/numbers only; if taken, try `realmpalacr01` or similar)
   - **Location:** East US 2
   - **SKU:** Basic (cheapest tier, fine for a single small API image)
5. Click **"Review + create"**, then **"Create"** once validation passes
6. Wait ~30 seconds for deployment, then click **"Go to resource"**
7. On the registry's **Overview** page, copy the **Login server** value
   (looks like `realmpalacr.azurecr.io`) — save it, needed for every step
   after this
8. Click **"Access keys"** (left sidebar) → toggle **"Admin user"** to
   **Enabled** → copy the **Username** and one of the two **Password**
   values. Needed so Container Apps can pull the image without a separate
   managed-identity setup (fine for a single-registry, single-app setup
   like this one)

### Step 1.5: Build & Push the API Image

Container Apps needs an actual image sitting in the registry before Step 3
below can point at it. `api/Dockerfile` builds the FastAPI backend on top
of `mcr.microsoft.com/playwright/python`, which ships Chromium/Firefox/
WebKit and all their OS-level deps preinstalled (the scraper needs a real
browser). That base image is large (~5 GB built), so this step needs
meaningful free disk space and time on a first run; do not use `--no-cache`
on later rebuilds or every layer pulls fresh again.

1. From the repo root (not `api/`, the Dockerfile's build context is the
   whole repo so `uvicorn api.main:app` resolves the same package path it
   uses locally):
   ```
   docker build -f api/Dockerfile -t realmpalacr.azurecr.io/realmpal-api:latest .
   ```
2. Log in to the registry (run this yourself in your own terminal, not
   through an assistant, so the password never ends up in any transcript):
   ```
   docker login realmpalacr.azurecr.io -u <Username from Step 1 Access keys> -p <Password from Step 1 Access keys>
   ```
3. Push the image:
   ```
   docker push realmpalacr.azurecr.io/realmpal-api:latest
   ```
4. Every time you ship a code change later, rebuild with a new tag (don't
   reuse `:latest` once this is live, so you can roll back):
   ```
   docker build -f api/Dockerfile -t realmpalacr.azurecr.io/realmpal-api:v1.0.1 .
   docker push realmpalacr.azurecr.io/realmpal-api:v1.0.1
   ```
   Then update the Container App's revision to that tag (Container App →
   **Application** → **Containers** → **Edit and deploy** → change **Image
   tag**).

### Step 1.6: Qdrant Cloud (vector search)

Locally, Qdrant runs as its own docker-compose service (`http://qdrant:
6333`), that hostname doesn't exist once the API is the only container
running in Azure. Qdrant has no Azure-managed offering; since this
collection only ever holds public wiki scrapes (no user data, see
`PRIORITY 7` below), Qdrant Cloud's free tier is the simplest fix, one
less thing to run yourself.

1. Go to **[https://cloud.qdrant.io](https://cloud.qdrant.io)** and sign
   up / log in (email, Google, or GitHub)
2. Click **"Create Cluster"** (sometimes labeled **"+ New Cluster"**)
3. Choose the **Free tier** (1 GB, no card required)
4. **Cluster name:** `realmpal`
5. **Region:** the AWS or GCP region closest to your Azure region (Qdrant
   Cloud runs on AWS/GCP, not Azure, there is no cross-cloud pairing to
   get exactly right, just pick the nearest one to East US 2, e.g. AWS
   `us-east-1`)
6. Click **"Create"**, wait ~1-2 minutes for provisioning
7. Once ready, open the cluster → copy the **Cluster URL** (looks like
   `https://xxxxxxxx-xxxx-xxxx.us-east-1-0.aws.cloud.qdrant.io:6333`)
8. Click **"API Keys"** (left sidebar within the cluster) → **"Create API
   Key"** → copy it immediately, it is only shown once
9. Set in the Container App's environment variables (Step 4 below):
   ```
   QDRANT_URL=<the Cluster URL from step 7>
   QDRANT_API_KEY=<the API key from step 8>
   ```
10. The collection itself starts empty (the API only creates it if
    missing at startup, it doesn't populate it, see the docstring in
    `api/services/ingestion.py`). Seed it once against the new cluster
    from your own machine, with `QDRANT_URL`/`QDRANT_API_KEY` from steps
    7-8 set in your local `.env` temporarily:
    ```
    api\.venv\Scripts\python.exe -m api.scripts.seed_wiki
    api\.venv\Scripts\python.exe -m api.scripts.seed_dps
    ```
    (Redis's specialist stores, by contrast, don't need this - `api/main.
    py`'s startup check warms those automatically the first time the app
    boots against an empty Redis.)

### Step 1.7: Azure Managed Redis

Locally, Redis is a docker-compose service too (`redis://redis:6379`),
same problem as Qdrant. Redis holds message quotas, quest state, and
session cache, not billing-critical data, but it does need to survive
restarts and handle concurrent access safely, so it gets an actual managed
service rather than the SQLite-style "run it as a Container App" shortcut.

1. Go to **[Azure Portal](https://portal.azure.com)**
2. Search for **"Azure Cache for Redis"** (top search bar) - this search
   term still works, it lands on a chooser screen with both options
3. Click **"+ Create"**
4. On the **"Choose a Redis service for your workload"** screen, pick
   **"Azure Managed Redis (Recommended)"**, not the "Azure Cache for
   Redis" tile next to it - that one shows its own banner saying new
   creation requests are blocked starting **October 1, 2026** and it's
   fully retired **September 30, 2028**. No reason to provision something
   that can't be recreated in a few weeks
5. **Basics tab:**
   - **Subscription:** your subscription
   - **Resource group:** `rg-realmpal`
   - **Cache name:** `realmpal-cache` (globally unique, becomes
     `realmpal-cache.<region>.redis.azure.net`)
   - **Location:** East US 2
   - **Pricing tier:** **Memory Optimized**, smallest SKU offered (Azure's
     own guidance: Memory Optimized's lower memory-to-vCPU ratio "provides
     a lower price point... an excellent choice for development and
     testing environments" - Balanced is tuned for production throughput
     this app doesn't need yet)
   - **High availability:** disable it if offered as a toggle - this data
     isn't billing-critical, and disabling HA on the smallest SKU roughly
     halves the cost
6. Click **"Review + create"**, then **"Create"**
7. Wait for provisioning (Redis caches are slower than most resources to
   come up, this is normal, not stuck)
8. Once deployed, go to the resource → **"Authentication"** or **"Access
   keys"** (left sidebar, exact label varies by portal version) → copy the
   **Primary** key or connection string
9. Set in the Container App's environment variables (Step 4 below). Azure
   Managed Redis uses a different hostname suffix than the old service and
   still requires TLS:
   ```
   REDIS_URL=rediss://:<primary-key>@realmpal-cache.<region>.redis.azure.net:6380/0
   ```
   Note the double `s` in `rediss://`, that is what tells the Python Redis
   client to use TLS; a single `redis://` on port 6380 will fail the
   handshake. Copy the exact hostname from the resource's Overview page
   rather than guessing the `<region>` suffix.

### Step 2: Create Container Apps Environment

1. Search for **"Container Apps"** (top search)
2. Click **"Create container app"**
3. Fill in:
   - **Resource group:** rg-realmpal (the same one from Step 1, so the
     registry and the app live together)
   - **Container app name:** realmpal-api
   - **Region:** East US 2
   - **Container Apps environment:** Click "Create new"
     - **Name:** realmpal-env
     - **Zone redundancy:** Disabled (for cost)
4. Click **"Next: Container"**

### Step 3: Configure Container

1. **Container details:**
   - **Image source:** Azure Container Registry
   - **Registry:** realmpalacr
   - **Image:** realmpal-api (pushed in Step 1.5 above; if it's not in the
     dropdown yet, the push hasn't finished or Azure's UI cached the empty
     registry list, refresh the page)
   - **Image tag:** latest
   - **CPU/Memory:** 0.5 CPU, 1 GB RAM (scale up if needed later)
2. Click **"Next: Bindings"**

### Step 4: Configure Environment Variables

1. Click **"Next: Environment variables"**
2. Add variables from your `.env`:
   ```
   JWT_SECRET=your-value
   STRIPE_SECRET_KEY=your-key
   STRIPE_PRICE_ID=your-price-id
   DATABASE_URL=postgresql://realmpaladmin:<password>@realmpal-db.postgres.database.azure.com:5432/realmpal?sslmode=require
   QDRANT_URL=your-qdrant-cloud-cluster-url
   QDRANT_API_KEY=your-qdrant-cloud-api-key
   REDIS_URL=rediss://:<primary-key>@realmpal-cache.<region>.redis.azure.net:6380/0
   FOUNDRY_RESOURCE=realmpal-foundry (after Foundry is deployed)
   FOUNDRY_BASE_URL=https://realmpal-foundry.services.ai.azure.com/
   DEPLOYMENT_NAMESPACE=prod
   DEBUG=false
   ```
   `DATABASE_URL`, `QDRANT_URL`/`QDRANT_API_KEY`, and `REDIS_URL` replace
   the docker-compose service hostnames (`redis://redis:6379`,
   `http://qdrant:6333`) used locally - those hostnames don't exist once
   this container is the only thing running. See Priority 6 (Postgres),
   the Qdrant Cloud setup, and the Azure Cache for Redis setup for where
   each of those three values comes from.
3. **IMPORTANT:** Move sensitive values to Key Vault (see next section) - do NOT paste raw API keys here

### Step 5: Configure Ingress & Scaling

1. Click **"Next: Networking"**
   - **Ingress traffic:** Enable
   - **Ingress type:** HTTP
   - **Target port:** 8001 (FastAPI port)
   - **Allow traffic from:** Anywhere (or restrict to your IP for testing)
2. Click **"Next: Scaling"**
   - **Min replicas:** 1
   - **Max replicas:** 3
   - **Scaling rules:** CPU threshold 70% (auto-scale on load)

### Step 6: Review and Deploy

1. Click **"Review + Create"**
2. Review all settings
3. Click **"Create"**
4. Wait ~2 minutes for deployment

### Step 7: Get Container App URL

1. Once deployed, navigate to the new Container App resource
2. Copy the **Application URL** (e.g., `https://realmpal-api.happybeach-abc123.eastus2.containerapps.io`)
3. Save for frontend configuration and Entra redirect URIs

---

## PRIORITY 5: Azure Key Vault Setup

**Status:** Centralizes secrets. Prevents hardcoded keys in `.env`.

### Step 1: Create Key Vault

1. Go to **[Azure Portal](https://portal.azure.com)**
2. Search for **"Key Vaults"**
3. Click **"Create"**
   - **Resource group:** realmpal-prod
   - **Vault name:** realmpal-kv (must be globally unique)
   - **Region:** East US 2
   - **Pricing tier:** Standard
4. Click **"Create"**

### Step 2: Grant Container App Access

1. Once created, go to the Key Vault resource
2. Click **"Access policies"** (left sidebar)
3. Click **"Create"**
   - **Template:** Key Vault secrets officer
   - **Principal:** Search for your Container App name (realmpal-api) → select it
4. Click **"Create"**

### Step 3: Add Secrets

1. In the Key Vault, click **"Secrets"** (left sidebar)
2. For each secret, click **"+ Generate/Import"**:
   ```
   JWT_SECRET → your-secret-key
   STRIPE_KEY → your-stripe-key
   ANTHROPIC_API_KEY → your-anthropic-key (if not using Foundry)
   MAGIC_LINK_SECRET → your-magic-link-secret
   PII_HASH_SECRET → your-pii-hash-secret
   FOUNDRY_KEY → your-foundry-key (if using Foundry)
   ```
3. After adding each, copy the **Secret identifier** (the full URI)

### Step 4: Update Container App to Reference Secrets

1. Go back to the Container App (realmpal-api)
2. Click **"Containers"** (left sidebar)
3. Edit the container
4. Under **Environment variables**, replace plain-text secrets with Key Vault references:
   - Instead of `JWT_SECRET=my-key`, use `@Microsoft.KeyVault(SecretUri=https://realmpal-kv.vault.azure.net/secrets/JWT_SECRET/abc123)`
5. Click **"Update"**

---

## PRIORITY 6: Azure Database for PostgreSQL

**Status:** DONE (Sep 13, 2026) at the code level - `api/services/db.py` now
supports both SQLite (local dev/tests, `DATABASE_URL` unset) and Postgres
(`DATABASE_URL` set) behind one interface; `accounts.py`, `entitlements.py`,
`uploads.py`, `billing_prefs.py` all run on either backend unchanged. What's
left here is provisioning the actual Azure resource and pointing the
Container App's `DATABASE_URL` at it.

No manual schema/migration step needed: each store creates its own tables
on first use (same as the SQLite path always did), so Step 3 below is just
"create an empty database", not "run migration scripts."

### Step 1: Create the PostgreSQL Server

1. Go to **[Azure Portal](https://portal.azure.com)**
2. Search for **"Azure Database for PostgreSQL flexible servers"** (top
   search bar) - "Single Server" is retired, only "Flexible Server" shows
   up now
3. Click **"+ Create"**
4. **Basics tab:**
   - **Subscription:** your subscription
   - **Resource group:** `rg-realmpal` (same group as everything else)
   - **Server name:** `realmpal-db` (globally unique; becomes
     `realmpal-db.postgres.database.azure.com`)
   - **Region:** East US 2 (match the Container App's region)
   - **PostgreSQL version:** latest offered (17 or 18)
   - **Workload type:** Development (Burstable tier, cheapest; switch to
     Production later if traffic justifies it)
5. Click **"Configure server"** under Compute + storage:
   - **Compute tier:** Burstable
   - **Compute size:** B1ms (1 vCore, 2 GiB) - smallest that isn't the
     absolute minimum B1ms is already the practical floor for a real app
   - **Storage:** 32 GiB, autogrow enabled
   - **Backup retention:** 7 days is fine
   - Click **"Save"**
6. **Authentication:** PostgreSQL authentication only
   - **Admin username:** `realmpaladmin` (not `postgres` or `admin`,
     reserved/blocked names)
   - **Password:** generate a strong one, save it somewhere durable (Key
     Vault once Priority 5 above is done; a password manager in the
     meantime), not just in your head
7. Click **"Next: Networking"**

### Step 2: Networking

1. **Connectivity method:** Public access (selected by default) - private
   access via VNet is more isolated but needs VNet peering with the
   Container Apps environment, more setup than this project needs yet
2. Check **"Allow public access from any Azure service within Azure to
   this server"** - this is what lets the Container App reach it without
   VNet integration
3. Under **Firewall rules**, click **"Add current client IP address"** so
   you (locally) can also connect directly to run one-off checks
4. Click **"Review + create"**, then **"Create"** once validation passes
5. Wait ~5-10 minutes for provisioning, then click **"Go to resource"**

### Step 3: Create the Database

Azure creates a default `postgres` database, but keep the app in its own:

1. On the server's Overview page, note the **Server name** (the full
   `realmpal-db.postgres.database.azure.com` hostname)
2. Left sidebar → **"Databases"** → **"+ Add"**
3. **Name:** `realmpal` → **"Save"**

No table creation needed here - `api/services/db.py` runs `CREATE TABLE IF
NOT EXISTS` for each store the first time the app touches it, same as it
already does locally against SQLite.

### Step 4: Set DATABASE_URL

Add this to the Container App's environment variables (Priority 4, Step 4)
once the Container App exists, and to your own `.env` only if you want to
point local dev at this same server temporarily (normally leave it unset
locally so you keep using SQLite):

```
DATABASE_URL=postgresql://realmpaladmin:<password>@realmpal-db.postgres.database.azure.com:5432/realmpal?sslmode=require
```

`sslmode=require` matters: Azure Database for PostgreSQL rejects
unencrypted connections by default, and asyncpg (the driver
`api/services/db.py` uses) needs that query param, not a separate flag, to
know to negotiate TLS.

---

## PRIORITY 7: Per-User Qdrant Filtering (LOW PRIORITY)

**Status:** Qdrant currently holds only public data. Per-user filtering adds isolation for private documents.

**Recommendation:** Defer until you have multi-tenant document uploads. For now:
- Keep global Qdrant collection (currently public scrapes only)
- When implementing per-user docs: add `user_email` metadata field to every vector before insert
- On retrieval: filter results where `metadata.user_email == current_user.email`

---

## Deployment Checklist

**Before going live:**

- [ ] Billing account status is "Active" (can deploy Foundry)
- [ ] Enchantment specialist wired and tested
- [ ] Entra portal values collected and pasted into `.env`
- [ ] Container Registry created and image pushed
- [ ] Container App running with correct endpoint
- [ ] Key Vault secrets configured
- [ ] PostgreSQL database initialized
- [ ] Redis connection verified
- [ ] Qdrant collection warmed
- [ ] Tests pass: `pytest api/tests/ -v`
- [ ] Local docker-compose verified working
- [ ] Production `.env` reviewed (no `DEBUG=true`, all secrets rotated)

---

## Rollback Plan

If something breaks in production:

1. **Container App revert:** Click **"Revisions"** → select previous working version → click **"Activate"**
2. **Database rollback:** Azure PostgreSQL has automatic backups (7 days by default)
3. **Secrets rotation:** If a key is compromised, update in Key Vault and restart Container App

---

## Support & Next Steps

- **Foundry blocked?** Contact Azure Support (see Priority 1, Step 2)
- **Entra issues?** Known bug with Google SSO + silent renewal — use email OTP only for MVP
- **Performance issues?** Scale Container App to 2–3 replicas and increase CPU/memory
- **After MVP:** Set up CI/CD pipeline to auto-deploy on git push to `master`

---

## History

### Until Sep 13, 2026 (later same day) - PRIORITY 4 Step 1.7 (Redis)

Original text told the reader to create an **"Azure Cache for Redis"**
resource directly (Basic C0 tier, ~$16/mo, hostname
`<name>.redis.cache.windows.net`).

**Superseded because:** when actually clicking through **"+ Create"** in
the portal (Sep 13, later), Azure now shows a chooser screen first with a
banner: Azure Cache for Redis blocks new creation requests starting
**October 1, 2026** (18 days out from that day) and fully retires
**September 30, 2028**, recommending **Azure Managed Redis** instead. Not
worth provisioning a resource that can't be recreated in a few weeks for a
project meant to show current cloud practice. Switched the pick to Azure
Managed Redis's Memory Optimized tier (Microsoft's own guidance calls that
tier the cheaper dev/test fit; Balanced is tuned for production
throughput this app doesn't need) and updated the hostname suffix and
connection string accordingly.

### Until Sep 13, 2026 (later same day) - PRIORITY 6 (Postgres)

Original text said "Only deploy AFTER Foundry is working," told the reader
to create a **"Single server"** tier (`az` UI: "Azure Database for
PostgreSQL servers" → Create → Single server), and to manually run
`CREATE TABLE accounts (...)` / `CREATE TABLE entitlements (...)` SQL
against the new database as a migration step.

**Superseded because:** (1) product decision on Sep 13 was to do the
Postgres migration immediately rather than work around SQLite's
concurrent-write limits with a mounted volume + single replica, so this
no longer waits on Foundry. (2) Azure retired the "Single Server" tier;
the portal only offers "Flexible Server" now. (3) `api/services/db.py`
was written the same day to run its own `CREATE TABLE IF NOT EXISTS` /
`ALTER TABLE ... ADD COLUMN` against whichever backend `DATABASE_URL`
points at, the same way it always did against SQLite - so there is no
manual schema/migration step at all, just point `DATABASE_URL` at an
empty database.

### Until Sep 13, 2026 (later same day) - PRIORITY 4 Step 1

Original text said to name the resource group `realmpal-resource` when
creating the Container Registry.

**Superseded because:** when actually creating it in the portal, the user
named it `rg-realmpal` instead (matching the `rg-` prefix convention and
avoiding confusion with the older, non-working Foundry resource sitting in
`rg-certio`). Every later step in this guide (Container Apps, Key Vault,
Postgres) should use `rg-realmpal`, not `realmpal-resource` or
`realmpal-prod`.

### Until Sep 13, 2026 (later same day) - PRIORITY 3 Steps 5-6

Original Step 5 walked through adding Google as an identity provider and
recommended email OTP. Step 6 collected email + given name + surname and
selected "Email Accounts (OTP only)". Step 7 still showed the wrong JWKS
path under `/v2.0/.well-known/.../jwks` and a B2C-style
`ENTRA_USER_FLOW=B2C_1_sign-up-sign-in` example.

**Superseded because:** product decision on Sep 13 was email with password
(no OTP, no magic link), email address only (IGN stays in-app), and Google
deferred. Live `.well-known` response already fixed the JWKS path in Step 4;
Step 7 was aligned to match. "Do NOT code yet" replaced with "portal done,
code integration next" once values landed in `.env`.

### Until Sep 13, 2026 (later same day) - PRIORITY 3 Step 4

Original text pointed at "Token configuration" in the app registration and
guessed the JWKS URL would live under
`https://[tenant-id].ciamlogin.com/[tenant-id]/v2.0/.well-known/openid-configuration/jwks`.

**Superseded because:** the real `.well-known/openid-configuration`
response (fetched live) put `jwks_uri` at
`https://[tenant-id].ciamlogin.com/[tenant-id]/discovery/v2.0/keys`
instead, a different path shape than a workforce tenant's JWKS URL.
`.env.example` already had this correct path; only this guide's draft
guessed wrong. Also worth recording: the tenant ID itself was misread
from a screenshot twice in the same session (transcribed as `dc3cb10a...`
when the real value was `dc3eb10a...`), tiny portal text makes
`c`/`e`/`0`/`O`/`1`/`l` easy to confuse. Copy IDs via the portal's copy
icon, never retype them by hand.

### Until Sep 13, 2026 (later same day) - PRIORITY 3 Steps 2-3

Original text for both app registrations:

- Step 2 (API): "**Supported account types:** Accounts in any identity
  provider or organizational directory (for multi-tenant scenarios)"
- Step 3 (SPA): "**Supported account types:** Same as API (multi-tenant)",
  "**Redirect URI:** Web → `http://localhost:3000/auth/callback`", plus a
  4th sub-step: "Click **Certificates & secrets** → New client secret → 6
  month expiration → paste as `ENTRA_WEB_CLIENT_SECRET`"

**Superseded because:** a real screenshot of the "Register an application"
page for a CIAM external tenant showed the actual dropdown options
("Single tenant only - RealmPal" / "Multiple Entra ID tenants" / "Any
Entra ID Tenant + Personal Microsoft accounts" / "Personal accounts
only"), none of which match the old B2C-era wording above. For External ID
customer sign-in, "Single tenant only" is correct: user-flow sign-ins
(email, OTP, Google, etc.) all present to the app as sign-ins into this one
tenant, "multi-tenant" and "personal accounts" are for a different scenario
(other companies' own Entra tenants). Also corrected: the SPA redirect
platform must be "Single-page application (SPA)", not "Web", and a SPA is
a public client so it must not have a client secret at all (PKCE via MSAL
instead); the old Step 3.4 client-secret instructions were removed rather
than just corrected, since no code path ever consumed
`ENTRA_WEB_CLIENT_SECRET`.

### Until Sep 13, 2026 (later same day) - PRIORITY 3 Step 1

Original instructions assumed tenant creation happened inside the regular
Azure Portal:

1. Go to **[Azure Portal](https://portal.azure.com)**
2. Search for **"Azure AD B2C"** (or **"Entra External ID"** in newer portal)
3. Click **"Create new external identity customer tenant"**
   - **Organization name:** RealmPal Production
   - **Country/Region:** United States
   - **Domain name:** realmpal-prod (or similar; must be globally unique)
4. Wait ~5 minutes for provisioning
5. Once created, you'll be redirected to the new tenant

**Superseded because:** Azure AD B2C stopped being available to purchase
for new customers on May 1, 2025, and that search result no longer exists
in the Azure Portal for a subscription without an existing B2C tenant.

### Until Sep 13, 2026 (same day, second revision) - PRIORITY 3 Step 1

The immediate replacement text claimed external tenant creation "cannot
be done from `portal.azure.com` at all anymore" and required the separate
Microsoft Entra admin center (`entra.microsoft.com`), per Microsoft Learn's
`tenant-configurations` page ("You can't create external tenants via the
Azure portal, which supports creation of workforce tenants only").

**Superseded because:** a real screenshot from inside the Azure Portal
showed the actual "Create a tenant" blade for an external/CIAM tenant,
reachable from the Default Directory's Entra ID → Overview → "Manage
tenants" → "Create" → "External" flow (URL:
`CreateDirectoryBlade/tenantType=ciam`), contradicting the Learn docs.
Ground truth from the live portal wins; corrected steps are in the current
PRIORITY 3 Step 1 above.

