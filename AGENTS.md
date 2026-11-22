# AGENTS.md

Guidance for coding agents working on the Biomedical Internship Tracker.

## Layout

- `companies.toml`: target season and the companies read on each refresh.
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
- Tests mock HTTP; never call live job boards from tests or CI.
- Don't change `tracker/ids.py` without a migration: every listing ID would change.
- New platforms must be added to `PLATFORMS`, the schema's `platform` enum and
  the tests together.
- Treat everything from job boards as untrusted: escape it when rendering and
  never follow URLs it supplies outside the company's origin.
- Requests to job boards send only the generic user agent in `tracker/http.py`.
