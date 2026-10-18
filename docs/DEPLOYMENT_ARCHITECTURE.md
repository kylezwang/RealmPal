# RealmPal Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PRODUCTION DEPLOYMENT                        │
└─────────────────────────────────────────────────────────────────────┘

┌────────────────────┐
│  Frontend (Next.js)│         ┌──────────────────────────────────┐
│  http://localhost  │────────→│  Azure Container Apps            │
│  or custom domain  │         │  - RealmPal API (FastAPI)        │
│                    │         │  - Auto-scaling (1-3 replicas)   │
│  Features:         │         │  - Managed by Azure              │
│  • Next.auth       │         │  - Port: 8001                    │
│  • Entra CIAM      │         └──────────────────────────────────┘
│  • OAuth flow      │                      ↓
└────────────────────┘         ┌──────────────────────────────────┐
                               │  Key Vault                       │
                               │  - All secrets encrypted         │
                               │  - JWT_SECRET                    │
                               │  - Stripe keys                   │
                               │  - Foundry/Anthropic keys        │
                               │  - DB credentials                │
                               └──────────────────────────────────┘


┌────────────────────────────────────────────────────────────────────┐
│                        AZURE INFRASTRUCTURE                         │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  │  Container       │   │  Redis           │   │  Qdrant          │
│  │  Registry        │   │  (cache/quota)   │   │  (vector search) │
│  │  (image store)   │   │  - chat history  │   │  - embedding     │
│  │                  │   │  - rate limits   │   │    storage       │
│  └──────────────────┘   │  - daily quests  │   │                  │
│                         │  - warmed wiki   │   └──────────────────┘
│  ┌──────────────────┐   └──────────────────┘
│  │  PostgreSQL      │   ┌──────────────────┐
│  │  (post-MVP)      │   │  Entra CIAM      │
│  │  - accounts      │   │  (identity)      │
│  │  - entitlements  │   │  - Google OAuth  │
│  │  - chat history  │   │  - Email OTP     │
│  └──────────────────┘   └──────────────────┘
│
└────────────────────────────────────────────────────────────────────┘


┌────────────────────────────────────────────────────────────────────┐
│                     EXTERNAL INTEGRATIONS                           │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  │  Stripe          │   │  Claude via      │   │  RealmEye /      │
│  │  - Checkout      │   │  Foundry         │   │  Umi / etc       │
│  │  - Billing       │   │  - API key from  │   │  (public data)   │
│  │  - Webhooks      │   │    Azure         │   │  - web scraping  │
│  └──────────────────┘   │  - CCU metering  │   │                  │
│                         └──────────────────┘   └──────────────────┘
│
└────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow: Sign-In

```
1. User visits web → clicks "Sign in with Entra"
   ↓
2. Browser redirected to Entra CIAM (ciamlogin.com)
   ↓
3. User authenticates (Google OAuth OR email OTP)
   ↓
4. Entra redirects back with `code` param
   ↓
5. Next.js exchanges `code` for access token (server-side)
   ↓
6. Access token stored in httpOnly cookie
   ↓
7. Browser session header includes Bearer token on API calls
   ↓
8. FastAPI verifies token against Entra JWKS endpoint
   ↓
9. If valid → request proceeds as authenticated user
   ↓
10. Chat history, quotas, and billing scoped to user email
```

---

## Data Flow: Chat Message

```
1. User sends message from web
   ↓
2. POST /chat/stream (with Bearer token)
   ↓
3. API verifies:
   - JWT signature against Entra JWKS
   - Entitlements lookup (active subscription or free tier)
   - Daily quota (5 free, 50 paid limit)
   ↓
4. Check Redis for stored answers:
   - Is this a known drop? → return wiki brief
   - Is this a known build? → return cached response
   - Is this a dungeon guide? → return wiki dump
   ↓
5. If not stored:
   - Retrieve context from Qdrant (embedding search)
   - Call Claude via Foundry (with Azure Managed Identity)
   - Stream response back to browser
   ↓
6. Update Redis:
   - Increment daily message count
   - Track Claude usage for billing
   ↓
7. Persist to:
   - Browser localStorage (chat history)
   - PostgreSQL (after MVP) for durable backup
```

---

## Deployment Timeline

```
Today (Sep 13)
├─ ✓ Chat sidebar ordering fixed
├─ ✓ Deployment guides created
└─ → Check Foundry billing status

This Week
├─ → Foundry billing clears (Azure support)
├─ → Wire Enchantment specialist (1-2h code)
├─ → Collect Entra portal values (30min)
└─ → Container Apps + Key Vault setup (1h)

Next Week
├─ → PostgreSQL migration (1h)
├─ → E2E testing (2-3h)
├─ → Security hardening review (1h)
└─ → Production launch

Post-Launch
├─ → CI/CD pipeline (GitHub Actions)
├─ → Monitoring (Azure Monitor)
├─ → Per-user Qdrant filtering (optional)
└─ → Scaling as needed
```

---

## Estimated Costs (Monthly)

| Resource | Est. Cost | Notes |
|---|---|---|
| Container Apps | $50-100 | 1-3 replicas, auto-scale |
| PostgreSQL | $50-150 | Single server, flexible compute |
| Redis | $40-80 | Included in Container Apps or standalone |
| Qdrant | $30-100 | Self-hosted on VM or managed service |
| Key Vault | $1 | Per vault, minimal |
| Foundry (Sonnet 4.6) | $0.003/1K tokens | Depends on usage; ~$200-500/mo if 100K messages |
| Entra CIAM | Free-$5 | Free up to 50K active users |
| Stripe | 2.9% + $0.30 | Per transaction (billing) |
| **Total** | ~**$200-800/mo** | Depends on usage (Foundry is biggest variable) |

---

## After Deployment: Monitoring Checklist

- [ ] Container App health checks passing
- [ ] Redis connection stable
- [ ] Qdrant vectors warmed
- [ ] Foundry API responding
- [ ] Entra token validation working
- [ ] Database backups running
- [ ] Error rates < 0.5%
- [ ] P95 response time < 2s
- [ ] Daily active users increasing

