# RealmPal

An AI companion for Realm of the Mad God. Ask about players, items, classes, and dungeons — RealmPal answers with stored RealmEye wiki, item sprites, set loadouts, and dyed skin portraits. Player lookups stay live.

Not affiliated with DECA Games. Data via [realmeye.com](https://www.realmeye.com), [umienjoyers.com](https://umienjoyers.com), and [RealmShark](https://tracker.realmshark.cc/dps-leaderboards).

---

## Features

- **Chat** - stored RealmEye replies for drops, builds, dungeon guides, and skins; Claude only when the ask is new or constrained
- **Accounts** - email + password sign-in / register; magic link is the forgot-password path. Chats and daily quests stay with the account
- **Player lookup** - `/player <ign>` or the sidebar IGN field; the sidebar pet is the highest-stat pet on RealmEye
- **Build specialists** - first `{stat} {class}` ask uses Sonnet (nicknames like pally / trix / sorc work), then the reply is replayed from Redis
- **Item cards** - wiki sprites and infobox rows from the warmed item store; the grid only shows gear the asked class can wear. Click a card to zoom the whole tile
- **Set visualizer** - shiny/divine (and nicknamed) sets render as a four-slot loadout
- **Skin visualizer** - class skin plus clothing and accessory dyes/cloths, composited the same way RealmEye outfits are
- **Dungeon guides** - RealmEye wiki dumps from the warmed store (Hard Mode focuses the HM section), not a fresh Claude essay
- **Daily quests** - three tasks a day in chat; finish the set for an extra message
- **What's new** - in-app changelog from `web/lib/changelog.ts`
- **RAG** - scraped wiki context indexed in Qdrant so Claude answers stay grounded
- **Freemium** - 3 guest messages / 5 signed-in free messages per 24h, then $7/month via Stripe Checkout. Pro includes 90 Claude replies; stored wiki/build answers do not count (signed-in stored hits also skip the daily meter). Extra Claude is $0.08 with a user-set spend cap.

---

## Tech Stack


| Layer           | Technology                                        |
| --------------- | ------------------------------------------------- |
| Frontend        | Next.js 16 (App Router), TypeScript, Tailwind CSS |
| Backend         | FastAPI, Python 3.12, LangGraph specialists       |
| Vectors / cache | Qdrant, Redis                                     |
| AI              | Claude (`claude-sonnet-4-6`) via Microsoft Foundry (local Anthropic fallback) |
| Scraping        | Playwright (RealmEye + UmiEnjoyers)               |
| Payments        | Stripe Checkout + magic-link JWT                  |
| Mobile          | Flutter (planned)                                 |


---

## Project Structure

```
RealmPal/
├── api/
│   ├── routers/       # chat, auth, players, items, dungeons, skins, payments, sprite, uploads
│   ├── services/      # stored answers, RAG, scraper, slot graph, specialist warm,
│   │                  # Claude billing, daily quests, accounts, entitlements
│   ├── models/        # Pydantic response models
│   ├── scripts/       # wiki refresh / specialist warm
│   └── main.py        # FastAPI app factory
├── web/
│   ├── app/           # chat, sign-in / register, account, legal
│   ├── components/    # chat UI, item/player cards, sprite zoom, quests, billing
│   └── lib/           # API client, changelog, quests, chat history
├── .github/workflows/ # weekly wiki specialist refresh
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
- An Anthropic API key (local fallback) **or** a Microsoft Foundry resource

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USER/RealmPal.git
cd RealmPal

cp .env.example .env
# Set JWT_SECRET and either ANTHROPIC_API_KEY (local) or Foundry
# (FOUNDRY_RESOURCE + FOUNDRY_USE_ENTRA, or FOUNDRY_API_KEY).
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
uvicorn api.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

```bash
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Default compose/API port is **8000**; keep `web/.env.local` in sync.

Always start the API with `--no-proxy-headers`. Uvicorn otherwise rewrites the client address from a caller-supplied `X-Forwarded-For`, which lets anyone reset their own rate limit. Proxy trust is configured instead via `TRUST_FORWARDED_FOR` and `FORWARDED_PROXY_HOPS`.

### 4. Tests

Covers auth and quotas, stored-answer hits, Claude billing, daily quests, specialist warm (do not re-scrape a full store), item-cache keys, and class-wearable item cards.

```bash
cd api
pip install -r requirements-dev.txt
cd ..
pytest
```

API docs (when `DEBUG=true`): [http://localhost:8001/docs](http://localhost:8001/docs) on Windows local, or port 8000 if you started uvicorn that way.

---

## How It Works

1. The user asks a question (player, item, dungeon, set, or dyed skin).
2. `stored_answers` classifies the turn. Drops, minted `{stat} {class}` builds, dungeon wiki dumps, shiny-divine quests, and skin templates stream from Redis with no Claude call.
3. If the ask is new or constrained, the **slot graph** routes to specialists (weapon / ability / armor / ring / player / dungeon / set / skin). A first-time build uses Sonnet and mints `wiki:build:v1:{class}:{stat}` for the next identical ask. Dungeon how-tos do not mint a Claude essay over the wiki store.
4. Specialists read cached RealmEye wiki pages in Redis (not live-scraped on chat). A new/empty Redis is filled in the background on API startup. After that, GitHub Action `Refresh wiki specialists` (Monday, or "Run workflow") and `python -m api.scripts.refresh_wiki` refill the store for ~7 days. Check with `python -m api.scripts.warm_specialists --status`. Player lookups scrape RealmEye on request.
5. Claude (when used) streams a short answer plus UI tokens (`[item:]`, `[loadout]`, `[skin:...]`).
6. The web app fetches warmed item profiles (`GET /items/{name}`) for sprites and cards. Click a character row, item card, or skin tile to zoom the whole card. The card grid drops items the asked class cannot equip; comparison text can still name sister-class gear.

**Paid flow:** Redis counts Claude-using messages per IP (guest, 3/24h) or signed-in email (5/24h). Signed-in stored hits skip that daily meter. The next Claude request returns `402`; guests are asked to sign in, signed-in users see Stripe Checkout. Pro is $7/month for 90 Claude replies. After the pool, `$0.08`/reply up to a user spend cap (`GET`/`POST /payments/on-demand`). Daily 200 is the fuse.

---

## API Endpoints


| Method | Endpoint              | Description                                |
| ------ | --------------------- | ------------------------------------------ |
| `GET`  | `/health`             | Process health                             |
| `POST` | `/auth/register`      | Email + password + IGN                     |
| `POST` | `/auth/signin`        | Email + password session                   |
| `POST` | `/auth/request-link`  | Magic-link fallback                        |
| `POST` | `/chat/stream`        | Streamed chat (SSE); stored hits skip Claude |
| `GET`  | `/chat/usage`         | Free-message usage for a session           |
| `GET`  | `/chat/quests/art`    | Daily quest dungeon / shiny sprites        |
| `POST` | `/chat/quests/claim`  | Extra message after finishing today's set  |
| `POST` | `/chat/feedback`      | Thumbs up/down on a reply                  |
| `GET`  | `/players/{username}` | RealmEye player profile                    |
| `GET`  | `/items/{name}`       | Warmed item profile + sprite (`?class_name=` marks `wearable`) |
| `GET`  | `/dungeons/{name}`    | Dungeon guide                              |
| `GET`  | `/skins/render`       | Composite skin + clothing + accessory dyes |
| `GET`  | `/sprite`             | Sprite sheet crop                          |
| `POST` | `/uploads`            | Chat image attachment                      |
| `POST` | `/payments/checkout`  | Stripe Checkout session                    |
| `POST` | `/payments/confirm`   | Confirm Checkout after redirect            |
| `POST` | `/payments/webhook`   | Stripe webhook                             |
| `GET`  | `/payments/verify`    | Magic-link → JWT                           |
| `GET`  | `/payments/billing`   | Plan, Claude pool, and spend cap           |
| `GET`  | `/payments/on-demand` | Read pay-as-you-go spend cap               |
| `POST` | `/payments/on-demand` | Set pay-as-you-go spend cap                |


---

## Environment Variables

See `.env.example`. Required:

- `JWT_SECRET`
- One chat backend: `ANTHROPIC_API_KEY` (local fallback) **or** Foundry
  (`FOUNDRY_RESOURCE` or `FOUNDRY_BASE_URL`, plus `FOUNDRY_USE_ENTRA=true`
  or `FOUNDRY_API_KEY`). Production should use Entra so no key sits in `.env`.

Optional until you turn on paid + production embeddings:

- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`
- `EMBEDDING_BACKEND` (`ollama` local, or `voyage` + `VOYAGE_API_KEY`)
- `QDRANT_URL`, `REDIS_URL`, `APP_URL`, `API_URL`

---

See [BACKLOG.md](BACKLOG.md) for planned work. Stored-answer chat shipped; next is Enchantment wiring, then Entra, then the Foundry billing block.

---

## License

MIT