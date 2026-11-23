# AGENTS.md

Guidance for coding agents working on the Biomedical Internship Tracker.

## Layout

- `companies.toml`: target season, the companies read on each refresh, and each
  company's program page (shown when it has no readable open postings).
- `tracker/sources/`: one module per job-board platform; each exposes
  `fetch(client, company) -> list[Lead]`.
- `tracker/screen.py`: the eligibility rules (US, internship/summer co-op, STEM,
  target year, not PhD-only).
- `tracker/reconcile.py`: how a run updates, closes and reopens listings.
- `tracker/listing.schema.json`: the record format for `data/listings.json`.
- `tracker/render.py`: README block and `CLOSED.md`.

## Commands

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest -q
python -m tracker validate
python -m tracker render --check
```

## Rules

- Never hand-edit `data/listings.json`, `data/status.json`, `CLOSED.md` or the
  generated block in `README.md`. Use `python -m tracker refresh`, `render` or
  `close`.
- An empty read fails when the company has `EMPTY_READ_GUARD` open listings or
  its last good read (`last_good_fetched` in `data/status.json`) fetched
  `EMPTY_FETCH_GUARD` postings; both live in `tracker/pipeline.py`. If a board
  really is empty, accept it with `python -m tracker reset-baseline "<company>"`
  in a reviewed pull request, not by editing `status.json`. When you move a
  company to a reader that fetches nothing (e.g. `careers_page`), run
  `reset-baseline` for it in the same pull request, or its first empty read
  fails every day.
- Tests mock HTTP; never call live job boards from tests or CI.
- Don't change `tracker/ids.py` without a migration: every listing ID would change.
- New platforms must be added to `PLATFORMS`, the schema's `platform` enum and
  the tests together.
- Treat everything from job boards as untrusted: escape it when rendering and
  never follow URLs it supplies outside the company's origin.
- Requests to job boards send only the generic user agent in `tracker/http.py`.
- Don't read Workday's jobs API (`*.myworkdayjobs.com/wday/cxs/…`) or work
  around a board's bot protection. A company that posts only on Workday stays on
  `careers_page` with its program page. See `docs/adr/0001-no-workday-jobs-api.md`.

## Agent skills

### Issue tracker

Issues are tracked in this repo's GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
