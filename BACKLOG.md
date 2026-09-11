# Backlog

Highest priority:

- **Enchantment specialist** — LangGraph slot next to weapon / ability / armor / ring. Reads RealmEye enchant tables and reports which rolls matter for an item or stat build. Needs a dedicated scrape first; the `enchanting` wiki hub seed is not enough.
- **Multi-tenancy** — isolate users, sessions, usage, and paid accounts so more than one operator (or environment) can run RealmPal without sharing Redis keys, Qdrant collections, or Stripe customer state.

Other notes:

- Flutter mobile app (iOS + Android)
- Guild page lookups
- Scheduled re-scraping so wiki/player data stays fresh
- Real email provider for magic-link login (Resend)
