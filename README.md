<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0a0b0e,60:15171c,100:0a0b0e&height=230&section=header&text=As-Built%20ISO%20Review&fontSize=46&fontColor=f2f0ea&fontAlignY=38&desc=Live%20Status%20Register&descAlignY=56&descSize=18&descColor=d7a34f&animation=fadeIn" width="100%" alt="As-Built ISO Review — Live Status Register" />

<img src="https://readme-typing-svg.demolab.com?font=Georgia&size=20&duration=3200&pause=1100&color=D7A34F&center=true&vCenter=true&width=760&lines=Synced+every+3+hours+-+zero+manual+pushes%2C+ever;4+lots%2C+one+register%2C+one+source+of+truth;Assignee+parsing+%2B+severity+%2B+closed-hold+logic%2C+all+automatic;Built+for+reviewers%2C+not+spreadsheets" alt="tagline" />

<br>

[![Deploy](https://github.com/vikramdex-ops/iso-review-dashboard/actions/workflows/deploy.yml/badge.svg)](https://github.com/vikramdex-ops/iso-review-dashboard/actions/workflows/deploy.yml)
[![Live Dashboard](https://img.shields.io/badge/live%20dashboard-view%20now-d7a34f?style=for-the-badge&logo=githubpages&logoColor=white)](https://vikramdex-ops.github.io/iso-review-dashboard/)
![Sync interval](https://img.shields.io/badge/auto--sync-every%203h-6fcf7c?style=flat-square)
![Lots tracked](https://img.shields.io/badge/lots%20tracked-4-6fb3e0?style=flat-square)
![Source](https://img.shields.io/badge/source-Google%20Sheets-34a853?style=flat-square&logo=googlesheets&logoColor=white)
![No backend](https://img.shields.io/badge/backend-none%20needed-8b8d96?style=flat-square)
![Last commit](https://img.shields.io/github/last-commit/vikramdex-ops/iso-review-dashboard?style=flat-square&color=d7a34f&label=last%20sync)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/vikramdex-ops/iso-review-dashboard?style=flat-square&color=d7a34f)](https://github.com/vikramdex-ops/iso-review-dashboard/stargazers)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-6fcf7c?style=flat-square)](CONTRIBUTING.md)

<br>

### 🔗 [**Open the live dashboard →**](https://vikramdex-ops.github.io/iso-review-dashboard/)

<sub>`vikramdex-ops.github.io/iso-review-dashboard` — bookmark it, no login needed</sub>

</div>

<br>

<p align="center">
  <a href="#what-this-is">What this is</a> ·
  <a href="#how-it-stays-current">How it stays current</a> ·
  <a href="#the-rules-behind-the-numbers">The rules behind the numbers</a> ·
  <a href="#on-the-dashboard">On the dashboard</a> ·
  <a href="#project-layout">Project layout</a> ·
  <a href="#adding-another-lot">Adding a lot</a> ·
  <a href="#faq">FAQ</a>
</p>

<img src="assets/banner.svg" alt="dashboard ledger preview" width="100%" />

<br>

## What this is

A single static page that always shows the current state of the ISO review register — who owns what, how much is closed, open, or on hold, split by severity and by lot, with a combined cross-lot view per reviewer. No one touches the Google Sheet export manually, no one re-runs a script, no one pushes code to refresh it. A scheduled job does that every 3 hours, and a **Refresh now** button on the page does it on demand.

The sheet stays the single source of truth. This repo only mirrors it, honestly, into something a lead can glance at.

<table align="center">
<tr>
<td align="center" width="25%">

**📋 4 Lots**
<br><sub>Lot 1 – Lot 4, same rules</sub>

</td>
<td align="center" width="25%">

**⏱ Every 3 hours**
<br><sub>cron-driven, no manual trigger</sub>

</td>
<td align="center" width="25%">

**🧮 Zero guesswork**
<br><sub>rules applied mechanically</sub>

</td>
<td align="center" width="25%">

**🪵 Fully auditable**
<br><sub>every sync is a git commit</sub>

</td>
</tr>
</table>

<br>

## Who this is for

The rules in this repo are specific to one ISO review register, but the shape of the problem isn't: **"I have a Google Sheet someone updates, and I need a live status page for people who shouldn't need sheet access."** Status trackers, intake logs, review registers, punch lists — anything where the sheet is the real database and a dashboard is just the window into it.

If that's your situation, the parts worth taking are:

- a sync script that reads tabs by numeric `gid` (not name — Google silently swaps tabs on a name mismatch, see [`build_summary.py`](scripts/build_summary.py))
- a content-hash guard against accidentally reading the same tab twice
- an all-or-nothing sync so a bad fetch never overwrites a good dashboard
- a GitHub Actions workflow that does the fetch → commit → deploy loop on a schedule, for free, with no server

Swap the column mapping and keyword rules for your own sheet's shape (see [Adding another lot](#adding-another-lot) and [`CONTRIBUTING.md`](CONTRIBUTING.md)) and the rest holds.

<br>

## How it stays current

```mermaid
flowchart LR
    A[("Google Sheet\nLot 1 · Lot 2 · Lot 3 · Lot 4")] -->|CSV export, by gid| B["build_summary.py"]
    B -->|apply business rules| C["site/data/summary.json"]
    C --> D["GitHub Pages"]
    E["GitHub Actions\ncron · every 3h"] -.triggers.-> B
    F["Refresh now button"] -.re-reads latest sync.-> D
    D --> G["👤 Your lead, anywhere"]

    style A fill:#15171c,stroke:#2a2d36,color:#f2f0ea
    style B fill:#15171c,stroke:#2a2d36,color:#f2f0ea
    style C fill:#15171c,stroke:#2a2d36,color:#f2f0ea
    style D fill:#15171c,stroke:#d7a34f,color:#f2f0ea
    style E fill:#0a0b0e,stroke:#2a2d36,color:#8b8d96
    style F fill:#0a0b0e,stroke:#2a2d36,color:#8b8d96
    style G fill:#15171c,stroke:#6fcf7c,color:#f2f0ea
```

Every run is guarded, not best-effort:

- **Fetched by numeric tab `gid` only** — never by sheet name, which Google silently substitutes with the wrong tab on a mismatch.
- **Content-hash checked across lots** — if two lots ever fetch byte-identical CSV, the run fails loudly instead of quietly duplicating a lot.
- **All-or-nothing per sync** — if any lot can't be read, the previous deployed site is left untouched rather than publishing partial numbers.
- **The sync itself is committed back to the repo** (`site/data/summary.json`, `closed_log.json`) — every number on the dashboard is auditable against real git history, not a black box.

<br>

## The rules behind the numbers

Everything the dashboard shows is derived mechanically from the sheet — no manual tagging.

| Rule | Logic |
|---|---|
| **Who owns a comment** | Column **P** (`Assigned To`). If two names appear separated by `/`, the **later** name is the actual assignee. |
| **Severity** | Column **M** (`Severity`) — High / Medium / Low. |
| **Closed / Completed** | Column **N** (`Status`) = `Closed`, **or** column **Q** (`Modeller response`) contains *updated, completed, done, ignored,* etc. — even while Status still reads Open. |
| **On Hold** | Column **Q** contains `RDB` or `HOLD`. |
| **Open** | Anything not matched above. |
| **Completed Today / Yesterday** | A persisted first-seen-closed log timestamps each row the moment it's first observed closed (IST calendar day), so "today's" closures are exact — not a quirk of when the sheet happened to update. |

<br>

## On the dashboard

- **Overview strip** — total assigned, closed, open, on hold, at a glance before anything else.
- **Per-lot breakdown** — Lot 1 · Lot 2 · Lot 3 · Lot 4, filterable by chip, each row keyed by reviewer.
- **Combined (by person)** — the same reviewer's numbers rolled up across *all four lots* in one line, for when lot boundaries don't matter and ownership does.
- **Severity ledger** — proportional High / Medium / Low bars per person.
- **Refresh now** — pulls the latest committed sync on demand, no redeploy required.
- **Sheet reconciliation line** — states plainly how many rows were read vs. counted vs. excluded, so a mismatch is visible, not hidden.

<details>
<summary><b>Full column set (19 columns per row)</b></summary>

<br>

`Assigned To` · `Lot Category` · `Assigned/Closed/Open — High` · `Assigned/Closed/Open — Medium` · `Assigned/Closed/Open — Low` · `Hold — High/Medium/Low` · `Overall Total Assigned` · `Overall Closed` · `Overall Open` · `Completed Today` · `Completed Yesterday`

</details>

<br>

## Project layout

```
iso-review-dashboard/
├── config.json                  # sheet id, lot → gid map, status keywords
├── scripts/
│   └── build_summary.py         # fetch → apply rules → write summary.json
├── site/
│   ├── index.html                # the dashboard itself (single file, no build step)
│   └── data/
│       ├── summary.json          # latest synced snapshot (committed every run)
│       └── closed_log.json       # per-row first-closed date, for day-aware counts
└── .github/workflows/deploy.yml  # cron (3h) + manual dispatch → sync → commit → deploy
```

## Adding another lot

Add one entry to `config.json` — the tab's numeric `gid`, same sheet:

```json
"lots": { "Lot 5": "123456789" }
```

Nothing else changes. The combined view, the chips, and the totals strip all pick it up on the next sync.

<br>

## FAQ

<details>
<summary><b>Does this need a backend, database, or paid hosting?</b></summary>
<br>No. The sync runs in GitHub Actions (free for public repos), the output is one JSON file, and the page is static HTML served by GitHub Pages (also free). The only moving part is the Google Sheet itself.
</details>

<details>
<summary><b>Does Claude / this repo have write access to my Google Sheet?</b></summary>
<br>No — it only reads the published CSV export of each tab (the sheet must be shared "Anyone with the link → Viewer"). Nothing is ever written back to the sheet.
</details>

<details>
<summary><b>What if the sheet structure doesn't match mine?</b></summary>
<br>Edit the column mapping and keyword lists in <code>config.json</code> / <code>scripts/build_summary.py</code> — see <a href="#who-this-is-for">Who this is for</a> and <a href="CONTRIBUTING.md">CONTRIBUTING.md</a>. Nothing else in the pipeline needs to change.
</details>

<details>
<summary><b>Can I self-host this for my own team?</b></summary>
<br>Yes — it's MIT licensed. Fork it, point <code>config.json</code> at your own sheet, and GitHub Actions + Pages do the rest on your own repo.
</details>

<br>

## Built with

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/GitHub%20Actions-cron%20%2B%20dispatch-2088FF?style=flat-square&logo=githubactions&logoColor=white" />
  <img src="https://img.shields.io/badge/GitHub%20Pages-static%20hosting-222?style=flat-square&logo=github&logoColor=white" />
  <img src="https://img.shields.io/badge/Vanilla-HTML%2FCSS%2FJS-F7DF1E?style=flat-square&logo=javascript&logoColor=black" />
  <img src="https://img.shields.io/badge/Google%20Sheets-CSV%20export-34A853?style=flat-square&logo=googlesheets&logoColor=white" />
</p>

<div align="center">
<sub>No server. No database. No vendor lock-in. The sheet stays the source of truth — this is just the window into it.</sub>
</div>

<br>

## Star history

<a href="https://star-history.com/#vikramdex-ops/iso-review-dashboard&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=vikramdex-ops/iso-review-dashboard&type=Date&theme=dark" />
    <img src="https://api.star-history.com/svg?repos=vikramdex-ops/iso-review-dashboard&type=Date" alt="Star History Chart" width="100%" />
  </picture>
</a>

<div align="center">

If the sheet-to-dashboard pattern here saves you from building your own, a ⭐ helps the next person find it.

<br><br>

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0a0b0e,60:15171c,100:0a0b0e&height=110&section=footer" width="100%" />

</div>
