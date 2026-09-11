# RealmPal

An AI companion for Realm of the Mad God. Ask about players, items, classes, and dungeons — RealmPal answers with live RealmEye data, item sprites, set loadouts, and dyed skin portraits.

Not affiliated with DECA Games. Data via [realmeye.com](https://www.realmeye.com) and [umienjoyers.com](https://umienjoyers.com).

---

## Features

- **Chat** — Claude-powered answers for RotMG questions, streamed into a dark chat UI
- **Player lookup** — `/player <ign>` or the sidebar IGN field; pet sprite follows you in chat
- **Build specialists** — weapon, ability, armor, and ring agents pull the right RealmEye pages for a class/stat
- **Set visualizer** — shiny/divine (and nicknamed) sets render as a four-slot loadout
- **Skin visualizer** — class skin plus clothing and accessory dyes/cloths, composited the same way RealmEye outfits are
- **Dungeon guides** — live RealmEye wiki scrape for the requested dungeon
- **RAG** — scraped wiki/player context indexed in Qdrant so answers stay grounded
- **Freemium** — 3 free messages, then $7/month via Stripe Checkout

---

## Tech Stack


| Layer           | Technology                                        |
| --------------- | ------------------------------------------------- |
| Frontend        | Next.js 16 (App Router), TypeScript, Tailwind CSS |
| Backend         | FastAPI, Python 3.12, LangGraph specialists       |
| Vectors / cache | Qdrant, Redis                                     |
| AI              | Claude (`claude-sonnet-4-6`) via Anthropic        |
| Scraping        | Playwright (RealmEye + UmiEnjoyers)               |
| Payments        | Stripe Checkout + magic-link JWT                  |
| Mobile          | Flutter (planned)                                 |


---

## Project Structure

```
RealmPal/
├── api/
│   ├── routers/       # chat, players, items, dungeons, skins, payments, sprite
│   ├── services/      # RAG, scraper, slot graph, visualizers
│   ├── models/        # Pydantic response models
│   ├── scripts/       # wiki / DPS seed jobs
│   └── main.py        # FastAPI app factory
├── web/
│   ├── app/           # chat page, auth verify
│   ├── components/    # chat UI, loadout row, skin portrait, paywall
│   └── lib/           # API client, token parsers
├── docker-compose.yml # Qdrant + Redis (+ optional API image)
├── start_services.ps1 # Windows local stack
└── stop_services.ps1
```

---

## Getting Started

### Prerequisites

- Docker Desktop (Qdrant + Redis)
- Node.js 20+
- Python 3.12+
- An Anthropic API key

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USER/RealmPal.git
cd RealmPal

cp .env.example .env
# Set ANTHROPIC_API_KEY and JWT_SECRET at minimum.
# JWT_SECRET: python -c "import secrets; print(secrets.token_hex(32))"

cp web/.env.local.example web/.env.local
```

Never commit `.env` or `web/.env.local`. Templates (`.env.example`) are safe to keep in git.

### 2. Windows (recommended on this repo)

```powershell
.\start_services.ps1
```

Starts Docker infra, the API on **[http://127.0.0.1:8001](http://127.0.0.1:8001)**, and the web app on **[http://localhost:3000](http://localhost:3000)**. Point `web/.env.local` at `http://localhost:8001` so the UI hits that API.

Do not use uvicorn `--reload` on Windows: Playwright (used for scraping) needs a Proactor event loop, and `--reload` breaks it. Restart `.\start_services.ps1` after backend changes.

Stop with `.\stop_services.ps1`.

### 3. Manual (macOS / Linux / Docker API)

```bash
docker compose up -d qdrant redis

cd api
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cd ..
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```bash
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Default compose/API port is **8000**; keep `web/.env.local` in sync.

API docs (when `DEBUG=true`): [http://localhost:8000/docs](http://localhost:8000/docs).

---

## How It Works

1. The user asks a question (player, item, dungeon, set, or dyed skin).
2. The **slot graph** routes to one or more specialists (weapon / ability / armor / ring / player / dungeon / set / skin).
3. Specialists scrape or cache RealmEye data; RAG pulls extra wiki chunks from Qdrant.
4. Claude streams a short answer plus UI tokens (`[item:]`, `[loadout]`, `[skin:...]`).
5. The web app renders sprites, loadout rows, and composited skin portraits from those tokens.

**Paid flow:** Redis counts guest messages. The 4th request returns `402`; the UI opens Stripe Checkout. After payment, a magic-link JWT bypasses the free cap.

---

## API Endpoints


| Method | Endpoint              | Description                                |
| ------ | --------------------- | ------------------------------------------ |
| `GET`  | `/health`             | Process health                             |
| `POST` | `/chat/stream`        | Streamed chat (SSE)                        |
| `GET`  | `/chat/usage`         | Free-message usage for a session           |
| `POST` | `/chat/feedback`      | Thumbs up/down on a reply                  |
| `GET`  | `/players/{username}` | RealmEye player profile                    |
| `GET`  | `/items/{name}`       | Item profile + sprite                      |
| `GET`  | `/dungeons/{name}`    | Dungeon guide                              |
| `GET`  | `/skins/render`       | Composite skin + clothing + accessory dyes |
| `GET`  | `/sprite`             | Sprite sheet crop                          |
| `POST` | `/payments/checkout`  | Stripe Checkout session                    |
| `POST` | `/payments/webhook`   | Stripe webhook                             |
| `GET`  | `/payments/verify`    | Magic-link → JWT                           |


---

## Environment Variables

See `.env.example`. Required:

- `ANTHROPIC_API_KEY`
- `JWT_SECRET`

Optional until you turn on paid + production embeddings:

- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`
- `EMBEDDING_BACKEND` (`ollama` local, or `voyage` + `VOYAGE_API_KEY`)
- `QDRANT_URL`, `REDIS_URL`, `APP_URL`, `API_URL`

---

## Backlog (Last updated: 9/10/26)

Highest priority:

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

Other notes:

- Flutter mobile app (iOS + Android)
- Guild page lookups
- Scheduled re-scraping so wiki/player data stays fresh
- Real email provider for magic-link login (Resend)

---

## License

MIT