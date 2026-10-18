# RealmPal Deployment: Quick Reference

## Current State (Sep 13, 2026)

**Done:**
- Stored-answer system (classify → Redis reply or Claude)
- Daily quests & PAYG billing
- Email+password sign-in (local)
- Account scoping (chats, quests per email)
- Card zoom & top pet detection
- Stripe Checkout with Link
- Rate limiting (chat + lookups)
- CORS hardening
- Magic-link hardening
- Security: server-issued JWTs, entitlements DB
- Deployment namespace (prod/staging isolation via `DEPLOYMENT_NAMESPACE`)

**In progress:**
- Foundry client (code done, **billing account under review**)
- Enchantment specialist (started, not wired)

**Blocked:**
- Foundry deployment (waiting for billing review to clear)

## Priority Order for Next Deployment

### 1. **Unblock Foundry** (CRITICAL)
   - **Action:** Check Azure billing account status
   - **Portal path:** Cost Management + Billing → Billing scopes → account status
   - **Expected:** Status should show "Active"
   - **If stuck:** Contact Azure Support
   - **Estimated time:** 24-48h if support needed

### 2. **Wire Enchantment Specialist** (MEDIUM)
   - **Action:** 4 small tasks in code (see DEPLOYMENT_GUIDE.md Priority 2)
   - **Files:** specialist_warm.py, stored_answers.py, chat.py, test_stored_answers.py
   - **Estimated time:** 1-2 hours

### 3. **Get Entra Portal Values** (MEDIUM)
   - **Action:** Create CIAM tenant + 2 app registrations (see DEPLOYMENT_GUIDE.md Priority 3)
   - **Portal path:** App registrations → create 2 (API + Web/SPA)
   - **Output:** 7 values to paste into `.env`
   - **Estimated time:** 30 mins portal setup + 10 mins value collection

### 4. **Container Apps + Key Vault** (HIGH)
   - **Action:** Create registry, app environment, link to Key Vault (see DEPLOYMENT_GUIDE.md Priority 4-5)
   - **Estimated time:** 1 hour

### 5. **PostgreSQL** (MEDIUM)
   - **Action:** After Foundry works, migrate from SQLite
   - **Estimated time:** 30 mins setup + schema migration

### 6. **Per-User Qdrant Filtering** (LOW)
   - **Action:** Defer until you have per-user document uploads
   - **Estimated time:** 2-3 hours (future)

---

## Top 3 Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Billing review stuck | Foundry blocked indefinitely | Contact Azure Support proactively; can proceed without Foundry using `ANTHROPIC_API_KEY` |
| Entra Google SSO bug | Token renewal fails 12-24h after sign-in | Use email OTP only in MVP; add Google later |
| Secrets in `.env` in production | Security breach | Move all secrets to Key Vault before going live |

---

## Command Checklist

```bash
# Before any deployment
pip install -r api/requirements-dev.txt
pytest api/tests/ -v

# After Enchantment wiring
python -m api.scripts.warm_specialists --status

# Build & push container
docker build -t realmpalacr.azurecr.io/realmpal-api:latest .
az acr login --name realmpalacr
docker push realmpalacr.azurecr.io/realmpal-api:latest

# Update Container App
az containerapp update --name realmpal-api --resource-group realmpal-prod \
  --image realmpalacr.azurecr.io/realmpal-api:latest
```

---

## Portal Navigation Bookmarks

| Task | Portal Path |
|---|---|
| Check Foundry status | Cost Management + Billing → Billing scopes |
| Create app registrations | Entra → App registrations |
| View CIAM tenant | Entra External ID |
| Deploy container | Container Apps → Create |
| Manage secrets | Key Vault → Secrets |
| Deploy database | Azure Database for PostgreSQL |
| Set up backup | PostgreSQL → Backups |

---

## Estimated Timeline to Production

| Phase | Tasks | Time | Blocker? |
|---|---|---|---|
| Phase 1 | Unblock Foundry + Enchantment | 1-3 days | Billing review |
| Phase 2 | Entra setup + Portal values | 1 day | No |
| Phase 3 | Container Apps + Key Vault | 1 day | No |
| Phase 4 | PostgreSQL migration | 1 day | No |
| Phase 5 | E2E testing & hardening | 2-3 days | No |
| Phase 6 | Launch | 1 day | No |
| **Total** | | **1-2 weeks** | Billing review |

**Critical path:** Billing review clears → all other work can happen in parallel.

---

## Key Decisions Already Made

- **Compute:** Azure Container Apps (needs real container for Playwright)
- **Auth:** Entra External ID CIAM (Google + email OTP)
- **Database:** SQLite now → PostgreSQL later
- **Secrets:** Key Vault (before production)
- **Foundry:** Microsoft Foundry (not generic Anthropic key)
- **Namespace:** `DEPLOYMENT_NAMESPACE` for multi-tenancy
- **Deployed region:** East US 2

