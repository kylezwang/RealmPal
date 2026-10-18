# RealmPal Development System: Complete Workflow

**Setup Date:** Sep 13, 2026  
**Purpose:** Unified changelog & documentation system for development, deployment, and operations

---

## The Three-Changelog System

### 1. BACKLOG.md (Forward-Looking Product Roadmap)

**Role:** Where are we going? What's next?

- Active priorities and in-progress work
- Blocked items with unblock conditions
- Technical decisions already made
- Research findings and options

**Lifecycle:**
- Start work → add to "In Progress" section
- Finish work → remove entirely (don't keep stale copy)
- Done work → archived in CHANGELOG.md and git history

**Read by:** Product managers, team leads, developers planning

---

### 2. CHANGELOG.md (Developer Technical Archive)

**Role:** What changed? How? Migration guide?

- Every completed version (not every commit)
- Breaking changes and migrations
- Technical details, file changes, and tests
- Internal refactors and infrastructure
- Known issues at time of release
- Linked commits

**Lifecycle:**
- Feature complete → write full technical section with commits
- Operations reads this before deploying
- Becomes permanent record in git

**Read by:** Developers, DevOps, anyone integrating with API

---

### 3. web/lib/changelog.ts (User-Facing UI Changelog)

**Role:** What's new in the app?

- User-visible improvements only
- Benefit-focused, no jargon
- 1-4 short bullets per release
- Appears in app UI ("What's new" modal, first-load popup, settings)

**Lifecycle:**
- Same day as CHANGELOG.md entry (if user-visible changes)
- Never hand-edit `LATEST_VERSION` constant (derived automatically)

**Read by:** End users (in-app UI only)

---

## Workflow: Building a Feature

### Phase 1: Start (BACKLOG.md)

```markdown
## In Progress

### Enchantment specialist (started Sep 13, not finished)

**Already in the tree:**
- `api/services/enchanting.py`

**Still open:**
1. Wire into warm...
2. Inject into RAG...
3. Skip extra wiki RAG...
4. Tests...

Do not start Entra until those four are done.
```

### Phase 2: Complete (CHANGELOG.md)

```markdown
## [2026.09.15] - Sep 15, 2026

### Added
- **Enchantment specialist**: Isolate enchant-only questions, store in wiki:enchanting:v1, skip extra RAG

### Tests
- test_enchant_question_retrieves_brief
- test_dex_roll_enchant_does_not_fire_on_wis_item
- test_enchant_follow_up_still_calls_claude

### Commits
- abc1234: Enchantment specialist wiring and tests
```

### Phase 3: User-Visible (web/lib/changelog.ts, if applicable)

```typescript
{
  version: "2026.09.15",
  date: "Sep 15, 2026",
  items: [
    "Enchanting advice is now instant for popular questions, no wait.",
  ],
}
```

### Phase 4: Remove from BACKLOG

Delete the entire "Enchantment specialist" section from BACKLOG.md. It now lives in CHANGELOG.md and git history.

---

## File Locations

| File | Purpose | Audience | Tracked? |
|---|---|---|---|
| **BACKLOG.md** | Forward roadmap, current work | Team leads, product | YES |
| **CHANGELOG.md** | Technical release notes, migrations | Developers, DevOps | YES |
| **web/lib/changelog.ts** | User-facing "What's new" | End users (app UI) | YES |
| **README.md** | Project overview, setup | Developers, new readers | YES |
| **docs/DEPLOYMENT_*.md** | Azure portal steps, architecture | DevOps | YES |
| **docs/chat-quality-benchmarks.md** | Performance traces, stored-answer map | Developers | YES |
| **docs/pricing.md** (gitignored) | Unit-econ, business logic | Internal only | NO |
| **docs/business.md** (gitignored) | Business assumptions | Internal only | NO |
| **.cursor/rules/development-workflow.mdc** | This workflow guide | Developers | YES |
| **.cursor/rules/doc-history.mdc** | Date-stamped history preservation | Developers | YES |
| **.cursor/rules/changelog.mdc** | User changelog entry rules | Developers | YES |

---

## Cursor Rules Synergy

### development-workflow.mdc (NEW)

Explains the three-changelog system and prevents BACKLOG staleness. When you finish a feature:

1. Remove from BACKLOG
2. Add full technical entry to CHANGELOG.md
3. Add user benefit to web/lib/changelog.ts (if visible)
4. Commit with reference to the feature

**Always apply:** Yes (guides future sessions)

### changelog.mdc

Reminds you to add user-facing entries (short, benefit-focused, no jargon) to `web/lib/changelog.ts` before deploying user-visible changes.

**Always apply:** Yes

### doc-history.mdc

Preserve old values with dates when updating BACKLOG, CHANGELOG, README, or docs. Never overwrite facts.

**Always apply:** Yes

**Example:**
```markdown
## History

### Until Sep 13, 2026
Paid Claude pool was 90. Daily fuse was 200.
```

---

## Anti-Patterns (Don't Do These)

### Stale BACKLOG

```markdown
## Enchantment specialist (started, not finished)

**Still open:**
1. Wire warm_enchanting_store...
```

**Problem:** No date; reader can't tell if this is from Sep 1 or Sep 20.

**Fix:** Remove it entirely once complete. It's in CHANGELOG.md now.

### User Details in CHANGELOG.md

```markdown
### Added
- **Billing**: User spend cap defaults to $0, stored at entitlements.stripe_subscription_id
```

**Problem:** Operations/DevOps don't care about UI behavior.

**Fix:** Put business detail in CHANGELOG.md; user benefit in `web/lib/changelog.ts`:
- CHANGELOG: "Entitlements store subscription status; on-demand spend cap configurable"
- UI: "Pro now lets you set a spending limit for extra messages"

### History Duplication

```markdown
# BACKLOG.md

## Done

### Enchantment (archived)

## History

### Until Sep 15, 2026
Wire warm_enchanting_store...
```

**Problem:** This is now in CHANGELOG.md too.

**Fix:** Remove "Done" section and history from BACKLOG. Link to CHANGELOG.md if needed later.

### Forgetting Commits in CHANGELOG.md

```markdown
## [2026.09.15]

### Added
- Enchantment specialist
```

**Problem:** Reviewer has no way to find the code.

**Fix:** Always include commit hashes:

```markdown
### Commits
- abc1234: Enchantment specialist wiring
- def5678: Enchantment tests
```

---

## Implementation Checklist

When finishing a feature:

- [ ] All tests pass (`pytest api/tests/ -v`)
- [ ] Code reviewed and merged to dev/master
- [ ] CHANGELOG.md entry created with commits
- [ ] User-visible changes added to web/lib/changelog.ts (if applicable)
- [ ] BACKLOG.md updated: feature removed (not marked "done")
- [ ] Commit message references the feature completion

**Example commit:**

```
feat: enchantment specialist wiring and tests

Completes enchantment specialist with full LangGraph isolation. Queries
resolve instantly from wiki store or stream Claude for constrained follow-ups.

- Wire warm_enchanting_store into specialist warming
- Inject brief into retrieve_build_knowledge for full builds
- Skip extra RAG on enchant-only turns
- Tests: stored brief lookup, slot-specific filtering, constrained follow-ups

Related:
- CHANGELOG.md: [2026.09.15] Enchantment specialist
- web/lib/changelog.ts: "Enchanting advice is now instant"
- Closes: Enchantment specialist (BACKLOG archived)
```

---

## Quick Reference

**When starting work:**
```markdown
## In Progress
### Feature Name (started TODAY, not finished)
Details here...
```

**When finishing work:**
1. Delete from BACKLOG
2. Add to CHANGELOG.md with commits
3. Add to web/lib/changelog.ts (if user-visible)
4. Commit with feature reference

**When reading old decisions:**
→ Check BACKLOG History section or CHANGELOG.md

**When debugging user complaints:**
→ Check web/lib/changelog.ts for exact date of changes

**When planning infrastructure:**
→ Check CHANGELOG.md [version] for breaking changes / migrations

---

## FAQ

**Q: Why remove completed work from BACKLOG?**  
A: Prevents staleness. BACKLOG should always show "what's next", not "what we did last week". Old work lives in CHANGELOG.md.

**Q: What if I need to reference old BACKLOG text?**  
A: It's in CHANGELOG.md History section or git history. Add a date-stamped History block if you're changing it.

**Q: When do I write CHANGELOG.md?**  
A: After the feature is done and tests pass, before it ships. Same day as web/lib/changelog.ts (if user-visible).

**Q: Can internal refactors go in web/lib/changelog.ts?**  
A: No. Only user-visible changes (new features, pricing, UI, bug fixes they'd feel). Tests, refactors, perf work (no visible effect) belong only in CHANGELOG.md.

**Q: Do I need to hand-edit LATEST_VERSION?**  
A: No. It's derived automatically from the first entry in web/lib/changelog.ts. Never touch it.

**Q: What if two features ship the same day?**  
A: Same version number (e.g., `2026.09.15-2`), extend the existing items array instead of creating a new entry.

---

## Success Metrics

- BACKLOG is always ≤ 1 week behind current work (no stale items)
- Every completed feature has a CHANGELOG.md entry before shipping
- Every user-visible change in web/lib/changelog.ts (rule enforced)
- No duplicate history between BACKLOG and CHANGELOG.md
- Commits link to the features they complete

