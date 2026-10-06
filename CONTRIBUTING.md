# Contributing

This started as a single team's ISO review tracker, but the underlying pattern — **a Google Sheet, synced on a schedule, rendered as a static GitHub Pages dashboard, with zero backend** — is generic. Contributions that make that pattern easier to reuse are very welcome: a second example config, a cleaner way to map columns, better docs, bug fixes, accessibility fixes, anything.

## Before you start

For anything beyond a small fix, open an issue first describing what you want to change — it saves a rewritten PR later. For typos, docs, or an obvious bug, a PR straight away is fine.

## Project shape

```
config.json                 # sheet id, lot → tab-gid map, status keywords
scripts/build_summary.py    # fetch each tab as CSV → apply rules → write site/data/summary.json
site/index.html             # the dashboard itself — single file, no build step, no framework
.github/workflows/deploy.yml  # cron (3h) + manual dispatch → run the sync → commit the data → deploy
```

There's no build tooling. `site/index.html` is read and edited directly; `scripts/build_summary.py` is plain Python 3.12 with only the standard library (`csv`, `urllib`, `hashlib`, `datetime`, `zoneinfo`) — no dependencies to install.

## Running the sync locally

```bash
python3 scripts/build_summary.py
```

This fetches whatever sheet/tabs are in `config.json`, applies the rules, and writes `site/data/summary.json`. Open `site/index.html` with a local server (`python3 -m http.server` from `site/`) to see it rendered — opening the file directly won't load the JSON due to `file://` CORS rules.

## Adapting this to your own sheet

The column mapping (`Severity`, `Status`, `Assigned To`, `Modeller response`, …) and the "closed"/"hold" keyword lists live in `config.json` and the `col()`/`summarise()` functions in `scripts/build_summary.py`. If you're pointing this at a differently-shaped sheet, that's the only place to touch — the sync, the dashboard, and the GitHub Actions workflow don't need any other changes.

## Pull requests

- Keep `scripts/build_summary.py` dependency-free (standard library only) — that's what lets the workflow run with nothing but `actions/setup-python`.
- Run the script locally against a sheet (even a toy one) before opening a PR that touches the sync logic, and mention what you tested in the PR description.
- For UI changes, a before/after screenshot in the PR makes review much faster.

## Code of conduct

Be respectful, assume good faith, keep feedback about the work rather than the person. That's the whole policy.
