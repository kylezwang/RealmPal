# Backlog

Last updated: 9/10/26

## Highest priority

- **Multi-tenancy** — isolate users, sessions, usage, and paid accounts so more than one operator (or environment) can run RealmPal without sharing Redis keys, Qdrant collections, or Stripe customer state. Planned OAuth.
- **Security hardening** — the MVP trusts the client more than a public deployment can afford. In rough priority order:
  - *Server-issued identity.* `session_id` comes from the client and is the only thing keying `ratelimit:{session_id}`, so rotating it resets the free tier. Identity has to be server-issued (the planned OAuth subject) before it can double as the tenant boundary.
  - *Real entitlement checks.* A JWT with `paid: true` is accepted on signature alone — no subscription lookup, no revocation list, no `aud`/`iss` checks — so a cancelled or refunded plan keeps working until the token expires. Separate the magic-link secret from the session secret, make magic links single-use, and never write them to logs.
  - *Abuse and cost limits.* `POST /payments/checkout` and `/chat/stream` are unauthenticated and uncapped: an attacker can mint Stripe sessions or burn Anthropic tokens at will. Needs per-identity and per-IP quotas, request/stream ceilings, timeouts, and a global kill switch.
  - *Tenant isolation in storage.* Redis keys and the single hardcoded `realm_pal` Qdrant collection are global. Namespace both per tenant and filter retrieval by tenant, or one user's ingested data can surface in another's answers.
  - *Infrastructure lockdown.* `docker-compose.yml` exposes Redis 6379 and Qdrant 6333 with no password or API key, and bind-mounts `./api` into the container. Move to private networking with credentials, keep `DEBUG=false` (it also gates `/docs`), and pin CORS to real origins instead of the hardcoded `localhost:3000`.
  - *Untrusted scraped content.* Prompt-injection defense is a short regex denylist over text scraped from third-party sites that flows into the system prompt. Treat scraped text as data, not instructions, and allowlist scrape targets so user input can't steer outbound requests (SSRF).
  - *Secrets and PII.* Keys live in a local `.env`; move to a managed secret store with rotation, and give scraped profiles and billing emails explicit TTLs plus a deletion path.
- **Enchantment specialist** — LangGraph slot next to weapon / ability / armor / ring. Reads RealmEye enchant tables and reports which rolls matter for an item or stat build. Needs a dedicated scrape first; the `enchanting` wiki hub seed is not enough.
- **DPS specialist** — Subagent specializing in calculating potential Damage Per Second (DPS) for related builds using reference from RealmShark.

## Other notes

- Flutter mobile app (iOS + Android)
- Guild page lookups
- Scheduled re-scraping so wiki/player data stays fresh
- Real email provider for magic-link login (Resend)
