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

## PRIORITY 2: Enchantment Specialist Wiring (MEDIUM PRIORITY)

**Status:** Code files exist, but not wired into warm/tests.

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

### Step 1: Create CIAM Tenant (if not already created)

1. Go to **[Azure Portal](https://portal.azure.com)**
2. Search for **"Azure AD B2C"** (or **"Entra External ID"** in newer portal)
3. Click **"Create new external identity customer tenant"**
   - **Organization name:** RealmPal Production
   - **Country/Region:** United States
   - **Domain name:** realmpal-prod (or similar; must be globally unique)
4. Wait ~5 minutes for provisioning
5. Once created, you'll be redirected to the new tenant

### Step 2: Create API Application Registration

1. In your CIAM tenant, search for **"App registrations"** (top search)
2. Click **"New registration"**
   - **Name:** RealmPal API
   - **Supported account types:** Accounts in any identity provider or organizational directory (for multi-tenant scenarios)
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
   - **Supported account types:** Same as API (multi-tenant)
   - **Redirect URI:** Web → `http://localhost:3000/auth/callback` (for local dev)
2. Once created, copy and save:
   - **Application (client) ID** → paste into `.env` as `ENTRA_WEB_CLIENT_ID`
3. Click **"API permissions"** (left sidebar)
   - Remove any default permissions
   - Click **"Add a permission"** → **"My APIs"** → select **"RealmPal API"**
   - Check the `access_as_user` scope → **"Add permissions"**
4. Click **"Certificates & secrets"** (left sidebar)
   - Click **"New client secret"**
   - Set expiration to **6 months**
   - Copy the **Value** (NOT the ID) → paste into `.env` as `ENTRA_WEB_CLIENT_SECRET`

### Step 4: Get JWKS URL and Issuer

1. Still in your CIAM tenant, search for **"Token configuration"** (in App registration context)
   - Or navigate: **App registrations** → **RealmPal API** → **Token configuration** (left sidebar)
2. Look for the **OpenID Connect metadata endpoint**:
   - It will be something like: `https://[tenant-id].ciamlogin.com/[tenant-id]/v2.0/.well-known/openid-configuration`
3. Open that URL in a browser (it's public JSON)
4. Copy the value of `jwks_uri` → paste into `.env` as `AUTH_JWKS_URL`
5. Copy the value of `issuer` → paste into `.env` as `AUTH_ISSUER`
6. Paste the API **client ID** again as `AUTH_AUDIENCE` in `.env`

### Step 5: Configure Social Identity Providers

1. Back in CIAM tenant, search for **"Identity providers"** (left sidebar)
2. Click **"+ New identity provider"** → **"Google"**
   - Enter your Google OAuth credentials (from Google Cloud Console)
   - **Note:** Known bug with silent renewal — if you hit this, either:
     - Keep Google but lose silent SSO (add `prompt=select_account` to auth request), OR
     - Use email OTP only (remove Google)
   - **Recommendation for now:** Email OTP only (simpler, no Google bugs)
3. Email OTP is already a built-in provider — no extra setup needed

### Step 6: Create Sign-In/Sign-Up User Flow

1. Search for **"User flows"** (left sidebar)
2. Click **"New user flow"**
   - **Type:** Sign up and sign in
   - **Name:** sign-up-sign-in
3. Configure:
   - **Identity providers:** Select **"Email Accounts (OTP only)"** and optionally **"Google"**
   - **User attributes to collect:** email, given name, surname
   - **Page layout:** Choose a theme (default is fine)
4. Once created, copy the **User flow policy ID** (e.g., `B2C_1_sign-up-sign-in`) → paste into `.env` as `ENTRA_USER_FLOW`

### Step 7: Collect Portal Values for .env

Add these to `.env`:

```bash
# Entra External ID (CIAM)
ENTRA_TENANT_ID=your-tenant-id
ENTRA_WEB_CLIENT_ID=your-spa-client-id
ENTRA_WEB_CLIENT_SECRET=your-spa-client-secret
ENTRA_API_CLIENT_ID=your-api-client-id
AUTH_JWKS_URL=https://[tenant-id].ciamlogin.com/[tenant-id]/v2.0/.well-known/openid-configuration/jwks
AUTH_ISSUER=https://[tenant-id].ciamlogin.com/[tenant-id]/v2.0
AUTH_AUDIENCE=your-api-client-id
ENTRA_USER_FLOW=B2C_1_sign-up-sign-in
```

**Do NOT code the Entra integration yet.** Paste portal values here first and confirm they work with a test token fetch.

---

## PRIORITY 4: Azure Container Apps Setup

**Status:** Infrastructure ready. This hosts the FastAPI backend.

### Step 1: Create Container Registry

1. Go to **[Azure Portal](https://portal.azure.com)**
2. Search for **"Container registries"** (top search)
3. Click **"Create"**
   - **Resource group:** realmpal-prod (create if needed)
   - **Registry name:** realmpalacr (must be globally unique, lowercase)
   - **Region:** East US 2
   - **SKU:** Basic (sufficient for small deployments)
4. Click **"Create"**
5. Once deployed, go to the resource
6. Copy and save the **Login server** (e.g., `realmpalacr.azurecr.io`)

### Step 2: Create Container Apps Environment

1. Search for **"Container Apps"** (top search)
2. Click **"Create container app"**
3. Fill in:
   - **Resource group:** realmpal-prod
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
   - **Image:** realmpal-api (will be pushed later)
   - **Image tag:** latest
   - **CPU/Memory:** 0.5 CPU, 1 GB RAM (scale up if needed later)
2. Click **"Next: Bindings"**

### Step 4: Configure Environment Variables

1. Click **"Next: Environment variables"**
2. Add variables from your `.env`:
   ```
   JWT_SECRET=your-value
   STRIPE_KEY=your-key
   FOUNDRY_RESOURCE=realmpal-foundry (after Foundry is deployed)
   FOUNDRY_BASE_URL=https://realmpal-foundry.services.ai.azure.com/
   DEPLOYMENT_NAMESPACE=prod
   DEBUG=false
   ```
3. **IMPORTANT:** Move sensitive values to Key Vault (see next section) — do NOT paste raw API keys here

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

**Status:** Replaces SQLite in production. Only deploy AFTER Foundry is working.

### Step 1: Create PostgreSQL Server

1. Go to **[Azure Portal](https://portal.azure.com)**
2. Search for **"Azure Database for PostgreSQL servers"**
3. Click **"Create"** → **"Single server"** (simpler for MVP)
   - **Resource group:** realmpal-prod
   - **Server name:** realmpal-db (globally unique)
   - **Region:** East US 2
   - **Version:** 13 or 14
   - **Admin username:** dbadmin
   - **Password:** Generate a strong password → save to Key Vault
4. Click **"Create"** (takes ~5 minutes)

### Step 2: Configure Firewall

1. Once deployed, go to the resource
2. Click **"Connection security"** (left sidebar)
3. Click **"Add current client IP"** (to allow local dev access)
4. **For Container App:** Also add the subnet of your Container Apps environment:
   - You may need to contact Azure Support for the exact subnet range, OR
   - Check the Container App's **Networking** settings for the managed identity subnet

### Step 3: Create Databases

1. Using `psql` or Azure Data Studio:
   ```sql
   CREATE DATABASE realmpal;
   CREATE TABLE accounts (...); -- From api/services/accounts.py
   CREATE TABLE entitlements (...); -- From api/services/entitlements.py
   ```
2. Run migration scripts to initialize schema

### Step 4: Update .env

```bash
# PostgreSQL
DATABASE_URL=postgresql://dbadmin:your-password@realmpal-db.postgres.database.azure.com:5432/realmpal
# Store password in Key Vault, not .env
```

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

