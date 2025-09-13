# TradingJournal — ROADMAP.md

> A big‑chunks, end‑to‑end plan from current scaffold to a completed Windows trading journal. Work in short feature branches, open PRs into `main`, and keep each phase shippable.

## Contributing Flow
- Branch naming: `feature/<phase>-<topic>` (e.g., `feature/p1-alembic`).
- Conventional commits (e.g., `feat:`, `fix:`, `perf:`).
- Pre‑commit required: ruff/black/mypy run locally and in CI.
- Keep docs and examples updated as you land features.

---

## Phase 1 — Data Layer Foundations (models, migrations, invariants)
**Goal**: Durable schema + fast, predictable DB I/O.

### Tasks
- Add **Alembic**; first migration creates `symbols`, `trades`, `daily_prices`.
- Indexes: `(profile_id, symbol, trade_date)` and `(symbol, date)`.
- Enforce SQLite perf PRAGMAs: `WAL`, `synchronous=NORMAL`, `temp_store=MEMORY`.
- Add DTOs (pydantic) for input boundaries: `TradeIn`, `SymbolIn`, `DailyPriceIn`.
- DAO guarantees: idempotent `symbols` upsert, batched inserts, read APIs for UI.

### Definition of Done (DoD)
- `alembic upgrade head` bootstraps a fresh DB.
- 10k synthetic trades insert quickly (batched).
- Unit tests assert constraints, types, and index presence.

---

## Phase 2 — CSV Ingestion (robust & idempotent)
**Goal**: Import TraderSync‑style CSVs cleanly, without duplicates.

### Tasks
- Ingest service with header mapping file; multi‑format date parsing.
- Idempotency key: `(profile_id, symbol, trade_date[, time])`.
- Diagnostics: per‑row errors to a log + summarized in UI; “dry run” CLI.
- Tests: golden CSVs (good/bad/edge); every trade references an existing symbol.

### DoD
- Re‑running the same CSV creates **no duplicates**.
- `python -m journal.ingest.tradersync path.csv` works and logs a summary.

---

## Phase 3 — Market Data & Backfill Orchestrator
**Goal**: Fill `daily_prices` and `prev_close` reliably and fast.

### Tasks
- Harden Polygon adapter: retries/backoff; small thread pool; UTC date normalize.
- Backfill engine: compute missing sets; group by symbol & contiguous date ranges.
- Write `daily_prices` in batches; set `prev_close` on `trades`.
- Caching/guards: DB‑first; circuit breaker on repeated failures.
- Tests: mocked Polygon responses (happy/empty/rate‑limited); property tests for prev_close.

### DoD
- `python -m journal.services.backfill --all-missing` fills OHLCV + prev_close.
- Re‑run only fetches what’s missing.

---

## Phase 4 — Float & Fundamentals Enrichment
**Goal**: Attach float per symbol and optional sector/industry/name.

### Tasks
- Float loader: UI action + CLI; `float_asof` policy (“newer wins”).
- Fundamentals stub (FMP): hydrate name/sector/industry when key present; cache.
- Tests: float overwrite policy; symbol normalization.

### DoD
- `symbols.float` populated for provided tickers; fundamentals filled when configured.

---

## Phase 5 — GUI v1: Fast Table You Can Live In
**Goal**: A filterable, sortable grid for daily use.

### Tasks
- `QAbstractTableModel` backed by **chunked DB queries**; DB‑side sorting when possible.
- Filters: date range, symbol, side, P&L >/<, has‑OHLCV.
- Column chooser dialog; persist per‑user prefs.
- Import wizard: choose CSV → dry run → confirm → progress → summary → prompt backfill.
- Non‑blocking UX: `QThread`/`QtConcurrent`; status bar progress; error toasts + “open logs”.

### DoD
- 40k‑row DB feels instant to scroll/sort/filter.
- Import from UI works end‑to‑end; prev_close + OHLCV show in the grid.

---

## Phase 6 — Derived Metrics & Journal Analytics
**Goal**: Useful columns + light analytics.

### Tasks
- Derived per‑day metrics: `%Gap` (open vs prev_close), `%Range` ((H-L)/prev_close), `%CloseChange`.
- Optional ATR‑like rolling range; precompute or view.
- Trade stats: R‑multiple, win/loss, avg gain/loss, hit rate by symbol/profile/date buckets.
- Analytics panel that responds to filters; export current view to CSV.

### DoD
- New columns toggleable in the grid.
- Analytics panel updates instantly and matches query filters.

---

## Phase 7 — Profiles, Settings, Backup/Restore
**Goal**: Multi‑profile support and clean settings UX.

### Tasks
- Profiles via multiple DB files (simplest) or `profiles` table + FK.
- Profile switcher; per‑profile preferences.
- Settings UI: keys, DB path, perf toggles, default filters/columns.
- Backup/restore: zip DB + settings + logs; restore with migration (Alembic).

### DoD
- Switching profiles requires no restart; preferences persist per profile.
- Backup/restore round‑trip succeeds; migrations apply cleanly.

---

## Phase 8 — Resilience & Performance Hardening
**Goal**: Jobs that don’t freeze the UI; handles large data comfortably.

### Tasks
- Lightweight **job queue** for imports/backfills (cancel/retry; progress per job).
- Virtualized views/streaming fetch; bound large unfiltered queries.
- Periodic `ANALYZE` and `PRAGMA optimize`.
- Structured logging to rotating files; “Copy diagnostics” button.

### DoD
- Jobs are cancelable/resumable; UI stays responsive.
- 100k+ `daily_prices` and 40k trades remain smooth.

---

## Phase 9 — QA, Automation, and Docs
**Goal**: Ship‑quality verifiability and onboarding.

### Tasks
- Tests: pytest‑qt GUI smoke; DAO integration on temp DB; property tests; ingest golden files.
- CI: GitHub Actions running ruff + mypy + pytest (Windows/3.12).
- Docs: README quick start + screenshots; `docs/` for workflows & troubleshooting.
- Code hygiene: pre‑commit enforced; CHANGELOG via releases.

### DoD
- Green CI on `main`.
- New dev can clone, follow README, and run the app successfully.

---

## Phase 10 — Packaging & Release
**Goal**: Distributable Windows app.

### Tasks
- PyInstaller spec (hidden imports for PySide6); embed version from git tag; icon.
- CI artifact on tags; optional code signing if available.

### DoD
- Non‑dev can download a release and run the app on Windows without setup.

---

## TL;DR Execution Order
1. **P1** Data layer + Alembic  
2. **P2** CSV ingest (idempotent)  
3. **P3** Backfill engine (Polygon + prev_close)  
4. **P4** Float & fundamentals  
5. **P5** GUI v1 (fast table, import wizard)  
6. **P6** Derived metrics + analytics  
7. **P7** Profiles + settings + backup/restore  
8. **P8** Resilience/perf (jobs, cancel, optimize)  
9. **P9** QA/CI + docs  
10. **P10** Packaging & releases
