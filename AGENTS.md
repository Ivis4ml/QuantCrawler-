# AGENTS.md

Guidance for AI coding agents (Codex, Cursor, Claude Code, etc.) working in this
repository. Keep changes consistent with the conventions below. The detailed
design rationale lives in `CLAUDE.md` (Chinese); this file is the practical,
vendor-neutral quick reference. Chinese mirror: `AGENTS.zh.md`.

## How agents load this file

- **OpenAI Codex (CLI / cloud):** auto-reads `AGENTS.md` at the repo root. Just run
  `codex` (or `codex "your task"`) from this directory. Codex also merges a global
  `~/.codex/AGENTS.md` and any nested `AGENTS.md` in subdirs (more specific wins).
  Global settings (model, approval policy, sandbox) go in `~/.codex/config.toml`,
  not here. No extra wiring needed — placing this file at the root is enough.
- **Cursor / Windsurf / Aider / Jules and most agent tools:** also read `AGENTS.md`
  at the root automatically.
- **Claude Code:** reads `CLAUDE.md` (the authoritative, more detailed design doc).
  Keep `AGENTS.md` and `CLAUDE.md` consistent when you change project facts.

Keep this file at the repository root, concise, and current. If you change commands,
structure, or conventions, update this file (and `CLAUDE.md`) in the same change.

## What this project is

**QuantCrawler** — a crawler that collects, from 20+ top finance/quant journals,
papers published 2020–2026 that are about **secondary markets, market
microstructure, high-frequency trading, or quantitative factors**, records full
metadata in SQLite, and downloads the **open-access** PDF when one legally exists.

Single-purpose Python CLI. No web server, no framework.

## Hard constraints (do not violate)

- **Open access only.** Download only legally-open copies: publisher OA, arXiv,
  SSRN/NBER/RePEc preprints surfaced by OpenAlex or Unpaywall. For paywalled
  papers, record metadata + DOI only. **Never bypass, scrape around, or defeat a
  paywall / Cloudflare challenge.** A 403 is recorded as `failed`, not worked around.
- **Be a polite API citizen.** All OpenAlex/Unpaywall/Crossref requests carry the
  `mailto` from `config/settings.yaml`. Per-host rate limiting is mandatory;
  arXiv is pinned to ~1 rps. Do not raise concurrency without keeping per-host caps.
- **Idempotent & resumable.** Every stage must be safe to re-run; progress lives
  in SQLite, re-runs only process unfinished rows. Preserve this when editing.

## Setup & run

```bash
pip install -r requirements.txt          # deps: httpx, pyyaml (rest is stdlib)
python --version                         # developed on 3.13; needs 3.11+

# Pipeline (each stage is idempotent / resumable):
python -m quantcrawler resolve-sources   # ISSN -> OpenAlex Source ID (cached in DB)
python -m quantcrawler harvest           # enumerate works, rebuild abstracts, cite counts, relevance filter
python -m quantcrawler select            # mark top-N per (journal, year) by citations (optional cap)
python -m quantcrawler resolve-pdfs      # locate OA PDF via Unpaywall + arXiv (concurrent)
python -m quantcrawler download          # concurrent streaming download into data/pdfs/
python -m quantcrawler report            # write paper_list.csv, download_worklist.csv, summary.md
python -m quantcrawler reconcile         # mark on-disk PDFs as downloaded (for private PDF handoff)
python -m quantcrawler run               # all of the above in order
python -m quantcrawler stats             # print catalog counts

# Common flags:
#   --journal SLUG     limit to one journal (slug from config/journals.yaml)
#   --config DIR --data DIR   override config/data dirs
#   download --limit N --retry-failed
#   -v                 debug logging (place BEFORE the subcommand)

python tests/test_units.py               # unit tests (no network); currently 16/16
```

## Repository layout

```
config/
  journals.yaml          21 journals: slug, name, issn, category, include_all, source_id, metadata_source
  settings.yaml          mailto, since/until window, themes (finance/general/exclude keywords+topics),
                         http + download (rate limits, workers, max_pdf_bytes), download_scope, top_per_year
quantcrawler/
  __main__.py / cli.py   argparse CLI entrypoint (python -m quantcrawler ...)
  config.py              load_settings(); Settings + Journal dataclasses
  models.py              Paper dataclass (one row of the papers table)
  db.py                  SQLite Catalog: schema, introspective migration, upsert, select_top_per_year, counts
  http.py                HttpClient + HostRateLimiter (thread-safe, per-host); retry/backoff; stream_to_file
  openalex.py            source resolution, cursor-paged works iteration, abstract reconstruction, pdf candidates
  crossref.py            Crossref harvest path for journals OpenAlex covers poorly (Review of Finance)
  relevance.py           RelevanceFilter — category-aware quant-relevance classification
  downloader.py          streaming PDF download, %PDF validation, size cap, sha256, atomic write
  pipeline.py            orchestration of every stage (resolve-sources/harvest/select/resolve-pdfs/download/report)
  resolvers/
    __init__.py          resolve_candidates() — combine Unpaywall + arXiv
    unpaywall.py         best_oa() prefers url_for_pdf over landing url
    arxiv.py             title-match against arXiv (q-fin/stat/econ), returns pdf url
tests/test_units.py      pure-logic unit tests (relevance, select, http parsing, migration, etc.)
data/                    runtime artifacts (gitignored): catalog.sqlite, pdfs/<journal>/<year>/<doi>.pdf, reports/
CLAUDE.md                full design doc + plan (Chinese, authoritative)
Journals.md              the 21 journals with descriptions
warmup_brief.html        standalone intern onboarding page
```

## Architecture in one paragraph

Two metadata paths feed one SQLite catalog: **OpenAlex** (default, by Source ID +
date window) and **Crossref** (fallback for `metadata_source: crossref` journals).
`harvest` classifies each work via `RelevanceFilter` and stores `is_quant`,
`relevance_reason`, `cited_by_count`, and any OpenAlex OA pdf url. `select`
optionally caps to top-N per (journal, year) by citations. `resolve-pdfs` fills in
OA urls via **Unpaywall** then **arXiv** (concurrent, arXiv-rate-limited).
`download` streams PDFs concurrently into `data/pdfs/`, validating the `%PDF`
magic and computing sha256. `report` emits the full paper list, a worklist of
everything not downloaded, and a summary.

## Relevance filter (the subtle part)

`RelevanceFilter.evaluate(include_all, category, title, abstract, primary_topic, topics)`:
- `include_all: true` journals (pure quant, e.g. Quantitative Finance) → always in.
- **Finance keyword** match → in, for any journal (strong signal).
- `category == "management_stats"` (JASA, MS, OR, Econometrica, J. Econometrics,
  JBES) → **stops here**: only finance keywords count. This prevents harvesting
  generic statistics/ML/OR papers that would otherwise dominate by citation count.
- Finance-native journals → finance topics + general method topics/keywords also count.
- `exclude_topics` drops papers whose `primary_topic` is corporate finance /
  banking / macro / household etc., unless a finance keyword already matched.

Keyword lists live in `config/settings.yaml` (`finance_keywords`,
`general_keywords`, `finance_topics`, `general_topics`, `exclude_topics`). Tune
there, not in code.

## Data model (papers table)

Single source of truth for columns: `_PAPERS_COLUMNS` in `db.py` (drives both
CREATE TABLE and auto-migration of older DBs). Key fields:
`openalex_id` (PK), `doi`, `title`, `authors` (JSON), `journal_slug`,
`publication_year`, `abstract`, `primary_topic`, `topics` (JSON), `cited_by_count`,
`is_quant`, `relevance_reason`, `selected`, `pdf_source`
(openalex/unpaywall/arxiv/none), `pdf_url`, `pdf_landing`, `pdf_path`, `sha256`,
`download_status` (pending/downloaded/paywalled/failed), `error`.

To add a column: append to `_PAPERS_COLUMNS`; migration is automatic. JSON-encoded
columns must be listed in `_JSON_FIELDS`. Fields that the harvest must NOT clobber
on re-run (download results, `selected`) are in the `preserve` set in `upsert_papers`.

## Conventions

- Python 3.11+, stdlib-first. Only third-party deps: `httpx`, `pyyaml`. Do not add
  dependencies without strong reason.
- Concurrency uses `concurrent.futures.ThreadPoolExecutor`; **worker threads do
  network/file IO only, the main thread does all SQLite writes** (sqlite connection
  is single-thread). Keep this split.
- No emoji in code or comments. Plain punctuation, no em dashes.
- Comments and the design doc are in Chinese; code identifiers in English. Match the
  surrounding style when editing a file.
- Add a unit test in `tests/test_units.py` for new pure logic; tests must not hit
  the network.

## Two-machine handoff

PDFs and `catalog.sqlite` are gitignored (copyright: "open to read" != "licensed to
redistribute"). Share them privately, not via the public repo. The receiver drops
`data/pdfs/` + `data/catalog.sqlite` into their clone and continues — already-downloaded
papers are skipped (status `downloaded` is never re-selected; the downloader also skips
when the target file already exists). If only PDFs are shared (no DB), run `harvest`
then `reconcile` to mark on-disk PDFs as downloaded. See `HANDOFF.md`.

## Current state (snapshot)

- 21 journals configured; window 2020–2026; `download_scope: all`.
- Harvest done: **4,590** relevant papers in the catalog (`paper_list.csv`).
- Download in progress; free-OA hit rate is ~10–20% (publisher direct links are
  mostly Cloudflare-blocked → recorded as `failed`/`paywalled`). The bulk needs
  institutional/campus-network access — that worklist is `download_worklist.csv`.
- Unit tests: 16/16 passing.

## Known follow-ups (not yet implemented)

See the checklist at the end of `CLAUDE.md`. Notably: persist all OpenAlex OA
candidates (`pdf_candidates` column) for a fuller fallback chain; arXiv DOI-based
matching + looser title threshold; keyword plural/inflection recall; Paper Digest
seed corpus connector (`seeds/paperdigest.py`).
