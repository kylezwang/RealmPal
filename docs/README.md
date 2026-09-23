# RealmPal Documentation

This directory contains all project documentation. Most files are tracked in git and visible to the public (for deployed projects). Sensitive files (pricing math, business estimates) are gitignored.

## Public Documentation (Tracked in Git)

| File | Purpose |
|---|---|
| `DEPLOYMENT_GUIDE.md` | Exact Azure portal steps for production deployment |
| `DEPLOYMENT_QUICK_REFERENCE.md` | Quick summary of priorities and commands |
| `DEPLOYMENT_ARCHITECTURE.md` | Infrastructure diagrams and data flows |
| `chat-quality-benchmarks.md` | Chat response quality traces and stored-answer map |
| `jev-routing-plan.md` | Saved plan (Sep 23, 2026): optional Jev disambiguator for ambiguous chat routing |

## Private Documentation (Gitignored)

| File | Purpose |
|---|---|
| `pricing.md` | Unit-econ estimates, hosting costs, break-even analysis, pricing sketches |
| `business.md` | (Reserved for future business logic notes) |

## Related Documentation (Outside docs/ folder)

| File | Purpose |
|---|---|
| `../CHANGELOG.md` | **Developer changelog** — technical details, breaking changes, migrations (git-tracked) |
| `../BACKLOG.md` | **Product roadmap** — current priorities, decisions, research notes (git-tracked) |
| `../README.md` | **Project overview** — feature list, setup instructions (git-tracked) |
| `../web/lib/changelog.ts` | **User-facing changelog** — rendered in app UI ("What's new" modal) (git-tracked) |

## Guidelines

- **New doc?** Put it in `docs/` unless it's a changelog, backlog, or readme (those stay at root)
- **Business logic or pricing?** Add to `docs/pricing.md` and gitignore it
- **Keep old info?** See `.cursor/rules/doc-history.mdc` — add a `## History` section with timestamped prior text
- **User-facing changelog?** Update `web/lib/changelog.ts` per `.cursor/rules/changelog.mdc`
- **Dev changelog?** Update `../CHANGELOG.md` with technical details

## Audience

- **Developers (you):** Read `CHANGELOG.md`, `BACKLOG.md`, and these docs
- **Users:** See "What's new" in the app (from `web/lib/changelog.ts`)
- **Operators:** See `DEPLOYMENT_GUIDE.md` for production setup

