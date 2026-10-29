# Project Handoff — `iso-review-dashboard`

**Purpose of this file**: let a brand-new Claude session (same account, a different account, or
a different AI assistant entirely) pick up this project and keep working on it without the
person having to re-explain everything from scratch. It is deliberately kept in the repo itself
(not only in any one Claude account's memory) so it travels with the project wherever it's cloned.

**This file intentionally contains no secrets.** Every credential the project needs is named
below along with where it lives and how to (re)create it — never its value. See "Secrets" below.

---

## 1. What this is

A static dashboard that reads an "As-Built ISO Review Register" Google Sheet (one tab per
"Lot") and shows, per reviewer and per document:
- how many review comments are assigned, closed, open, or on hold, broken down by severity
- which documents are fully closed and ready to issue, which need a little more work, and which
  still need real work — independent of who the comments are assigned to
- "Booklet Issuance" readiness — ISO booklets are a fixed set of (Document No., Line Number)
  pairs that can span multiple lots; a booklet is only "ready" once every pair mapped to it is
  closed everywhere, and the dashboard flags any mapped pair that's missing from every lot's
  tracker entirely (never captured) so it can be chased down before the booklet is claimed done

It refreshes itself automatically — a GitHub Action reads the sheet every 45 minutes (plus on every
push, plus on demand), computes everything, and redeploys. This runs entirely on GitHub's servers;
nobody's PC needs to be on. A page left open re-reads the published sync every 5 minutes (and when
its tab regains focus), so it never sits on stale data, and its **Refresh now** button runs a fresh
sync from the sheet on the spot (≈1–2 minutes) instead of waiting for the next slot. **Nobody should ever need to write or
push code just to get fresh numbers onto the site.**

- **Live site**: https://vikramdex-ops.github.io/iso-review-dashboard/
- **Repo**: https://github.com/vikramdex-ops/iso-review-dashboard
- **Source Google Sheet**: `1pu7jJDQ8a2e7PIjiv1Bqw7NVzeOKzJLlA_fMmmyBzTY`

## 2. Architecture (zero backend, by design)

```
Google Sheet (one tab per Lot)
      │  Sheets API v4 (filter-proof — see §4)
      ▼
scripts/build_summary.py          (runs in GitHub Actions)
      │  writes
      ▼
site/data/summary.json            (committed back to the repo for auditability)
      │  served statically
      ▼
site/index.html                   (single self-contained page, fetches summary.json)
      │
      ▼
GitHub Pages                      (the live site)
```

- `.github/workflows/deploy.yml` — the whole pipeline. Triggers: `push` to `main`, `schedule`
  (every 45 minutes via four staggered crons `7 0-21/3`, `52 0-21/3`, `37 1-22/3`, `22 2-23/3`, i.e.
  00:07, 00:52, 01:37, 02:22 … UTC), `workflow_dispatch` (manual "run now"), and `issues: opened` for
  issues titled `[refresh] …` — that is the page's **Refresh now** button (§5): it opens such an issue
  with the same Issues-only `ISSUE_PAT`, the workflow syncs + deploys and then closes the issue, and the
  page watches `summary.json` until the new `updated` timestamp lands. Any other new issue skips the job
  and gets a throwaway concurrency group, so it can never cancel a deploy in progress. The 7-minute offset
  is deliberate — see §7 (GitHub drops scheduled runs most at :00/:15/:30/:45).
- `.github/workflows/issue-intake.yml` — handles the "mark documents as issued" write path (§5).
- No database, no server, no API you have to host. The only moving part is the Python script and
  two small JSON files it maintains (`closed_log.json`, `issued_log.json`) in `site/data/`.

## 3. Business rules (the actual logic, not just "see the code")

- **Column layout is FIXED, not detected by header text**, for every lot: A = Comment No.,
  B = Document No., C = Line Number, M = Severity, N = Status, P = Assigned To,
  Q = Modeller Response. See §7 for why this matters — it was the site of a real bug.
- **Assignee**: column P. If two names are joined by `/` (e.g. `"Dharma/Kowshik"`), the LATER
  name owns the comment.
- **Severity**: column M, must be exactly High / Medium / Low (case-insensitive, capitalised on
  read). Anything else (blank, "OK", typos) is excluded and counted under
  `excluded_no_severity` in that lot's diagnostics — not silently dropped, but not shown either.
- **Closed**: Status (column N) is literally "Closed", OR the Modeller Response (column Q)
  contains any of `done_words` from `config.json` (currently: updated, complete, completed,
  ignore, ignored, done, closed, incorporated) — case-insensitive substring match.
- **On hold**: Modeller Response contains any of `hold_words` (currently: rdb, hold). Hold items
  are NOT closed — they still count under "Overall Open".
- **Document-level (Issuance screen)**: a document (column B) is "ready to issue" only when
  EVERY comment against it — any assignee — is closed. `ADDRESS_THRESHOLD = 3`: a document with
  ≤3 open/hold points left is "address these", otherwise "needs more work".
- **Booklet-level** (revised 2026-10-26): a static mapping (`data/booklet_mapping.json`, v3, built
  from the owner's `FST_ISO_Booklet_Mapping_v3.xlsx` by `scripts/build_booklet_mapping.py`) lists the
  (Document No., Line) items in each ISO booklet. **Demolition booklets (1913, 1914, 39-1677,
  39-1678) are excluded from issuance entirely** (owner decision). Matching: a document that
  belongs to one booklet is matched on the document number alone across every lot (the
  workbook's source-file check: one document = one booklet); the documents whose lines are split
  between booklets (`split_documents`: 1675, 1679) are matched on document + line ID (service code
  + line number, e.g. `D-16977`), which is immune to size/spec/hyphen/typo differences in tracker
  line text. `alias_docs` cover three lines the trackers log under another document number
  (1963→1675, 1748→1751, 39-1629→39-1626), accepted only because the line ID matches exactly and
  the other document is not itself mapped. Readiness is tracked by **document**, not by comment rows or line items
  (owner decision 2026-10-26): a document is closed once every comment against it, in every lot,
  is closed; open while any comment is open/on hold; **not yet in any lot** when no lot has
  reviewed it (holds the booklet back, but is not a mapping error). A booklet is ready to issue
  only when all of its documents are closed. The Booklet screen's document tracker lists every
  booklet document with its line(s), status, open/total comments, lots and the workbook's
  extraction-plan status (`plan_status`), filterable and copyable. Decisions applied on top of the workbook are
  recorded in the JSON (`decisions`) and shown on the dashboard: 1678 → 1755 (owner-confirmed), and
  2005/2100/2134/2136/2139/2140 → 1755 (GRE "AP" spec lines; the workbook flags them as breaking
  one-line-one-booklet, and every other GRE line in the workbook sits in 1755/1722). **Designer remarks
  (workbook v3, 2026-10-26)**: rows whose Doc+Line Status reads "Superseded" or "Deleted" are dropped
  from readiness and listed under `superseded` in the JSON — 2604 → 2137 and 2605 → 2138 (the lines are
  tracked under those documents), 1675 VG-11904 → 1672, and 1710 deleted by the RLM; 2046 was renamed
  2143 (the drawing's title block reads 2143). Result: 464 booklet documents, 31 not yet in any lot
  (owner-confirmed count, 2026-10-26). To apply a
  revised workbook: `pip install openpyxl && python3 scripts/build_booklet_mapping.py <file.xlsx>`
  — it refuses to write if any check fails.
- **"Completed Today / Yesterday"**: there's no close-date column in the sheet, so
  `site/data/closed_log.json` records the first IST calendar day each (lot, comment) row is ever
  observed closed. A first-ever run tags everything "baseline" instead of inflating day one.
- **Row-count regression guard**: if a lot's row count ever drops versus its last successful
  sync, that lot's new read is REJECTED and the previous sync's data is kept for that lot only
  (with a visible warning), rather than silently under-counting. See §4 for why this is needed
  and how the Sheets API avoids triggering it falsely.
- **Duplicate-tab detection**: each lot's raw fetched content is SHA-256 hashed per run; if two
  lots hash identically, that's treated as a misconfigured gid pulling the same tab twice, and
  the second one errors out loudly instead of silently duplicating data.

## 4. Why Sheets API, not CSV export

`scripts/build_summary.py` can read a tab two ways:
- **Sheets API v4** (`spreadsheets.values.get`, used when `GOOGLE_SHEETS_API_KEY` is set) — reads
  the tab's real values server-side. An active "Data > Create a filter" on the tab (which team
  members use while working) is a UI/display construct the API ignores entirely. **This is the
  production path and must stay configured.**
- **Public CSV export** (fallback when no key is set) — reflects the tab's live FILTERED view, so
  a filter left on by someone working the sheet silently hides rows from the export for
  everyone, including the sync. Fine for a quick local check only.

## 5. "Mark as issued" write path

The Issuance screen's "Mark these as issued" button needs to durably remember that a batch of
documents was already issued, without a real backend. It does this by:
1. The public page POSTs a GitHub Issue via the REST API, using a fine-grained PAT scoped to
   ONLY `Issues: write` on this one repo (named `ISSUE_PAT` as a repo secret — see §6).
2. `.github/workflows/issue-intake.yml` triggers on that issue being opened, parses it, records
   the documents into `site/data/issued_log.json`, re-runs the sync, commits, and closes the
   issue with a confirmation comment.
3. The committed `site/index.html` always contains the literal placeholder `__ISSUE_PAT__` — the
   REAL token is substituted only into the deploy artifact at build time by `deploy.yml`
   (`sed -i "s/__ISSUE_PAT__/$ISSUE_PAT/" site/index.html`), AFTER the git-commit step, so the
   real value never enters git history. **Do not "fix" this by committing a real token — that is
   intentional and load-bearing for keeping the secret out of git.**

This was a deliberate, explicitly-chosen trade-off: the token is visible to anyone who opens dev
tools on the public page, but its scope (Issues-write, one repo) limits the blast radius of a
leak to "can open/close issues here" — it cannot touch code, workflows, or any other repo.

The same token powers **Refresh now**: the page opens a `[refresh] …` issue, `deploy.yml` reacts to it
with a full sync + deploy and closes it. A leaked token can therefore also trigger extra syncs — harmless
(each run just re-reads the sheet; `cancel-in-progress` collapses bursts). Without the secret the button
falls back to re-reading the latest published sync.

## 6. Secrets (names and purpose only — see "Setting these up fresh" to recreate them)

| Secret (GitHub Actions repo secret) | Used for | If missing |
|---|---|---|
| `GOOGLE_SHEETS_API_KEY` | Sheets API v4 reads (filter-proof) | Falls back to CSV export (filter-vulnerable) — the dashboard will visibly flag which method ran |
| `ISSUE_PAT` | the "mark as issued" write path (§5) | The button falls back to opening a prefilled GitHub issue form for manual submission instead of writing automatically |

Neither value is retrievable by anyone once set — GitHub Actions secrets are write-only. Nobody
(including Claude, including the project owner) can "export" these; they can only be rotated.

**Setting these up fresh** (e.g. in a new Google/GitHub account):
- `GOOGLE_SHEETS_API_KEY`: Google Cloud Console → enable the "Google Sheets API" on a project →
  Credentials → Create API key → restrict it to the Sheets API. The target spreadsheet must be
  shared "Anyone with the link: Viewer" (or the key's service context must have read access).
- `ISSUE_PAT`: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
  tokens → New token, scoped to this repo only, permission `Issues: Read and write`, nothing else.
- Add both under the repo's Settings → Secrets and variables → Actions → New repository secret,
  with exactly the names in the table above.

**If you were asked to export a "complete backup including all credential values"**: don't.
Compiling live secrets into a portable document — even at the account owner's own request, even
for migrating to another of their own accounts — is a real exfiltration-shaped risk regardless of
stated intent, and it's unnecessary: everything above is enough for a fresh setup to work without
ever moving a live secret through a document, a chat, or an export file. If any credential has
ever been pasted in plaintext in a chat with an AI assistant, treat it as compromised and rotate
it, independent of anything else.

## 7. Known bugs found and fixed (read before assuming something that looks odd is new)

- **Lot 1/Lot 2 duplicate-tab bug** (2026-10, early): a wrong gid caused Lot 1 and Lot 2 to read
  the same underlying tab. Fixed by the duplicate-content-hash check (§3) plus moving off
  unreliable gviz/sheet-name lookups.
- **Filtered-view undercounting**: see §4 — fully resolved by the Sheets API migration.
- **"Synced 3h ago" while syncs were running** (2026-10-28): two causes, neither a broken pipeline
  (it runs on GitHub, not on anyone's PC). (a) The page loaded `summary.json` once and never again, so a
  tab left open showed its load-time data forever — fixed by polling every 5 minutes + on tab focus.
  (Follow-up, 2026-10-29: **Refresh now** used to only re-read that same published file, so it could
  never show anything newer than the last scheduled sync — it now triggers a real sync, see §2.)
  (b) GitHub does not guarantee `schedule` runs; on 2026-10-27 only ~13 of 32 slots ran, worst gap ~2h50m,
  every run that did fire succeeded. Mitigated by moving the crons off the quarter-hour (:07/:52/:37/:22).
  If every slot must fire, the remaining option is an external trigger (e.g. a Google Apps Script
  time-driven trigger calling `workflow_dispatch` with a token that has `Actions: write`) — not set up.
- **Lot 1 header-label shift** (2026-10-24): Lot 1's header ROW had "Document No.", "Severity",
  "Status", "Assigned to", "Modeller Responce" each typed ONE CELL to the right of the column
  they actually label (a data-entry defect in that one tab, not a code bug — Lots 2-7's headers
  are fine). The code used to resolve these columns by matching header TEXT, which silently read
  the wrong column for Lot 1 specifically — e.g. "severity" was actually reading the Status
  text, "assigned to" was reading the Modeller Response text. **Fixed by switching to the fixed
  column-letter positions in §3 for every lot, unconditionally** — do not reintroduce
  header-name matching for these fields without re-checking every lot's actual header row first.

## 8. Repo layout

```
config.json                  sheet_id, lot name -> tab gid (or "title:<tab name>"), done/hold word lists
scripts/build_summary.py     the entire sync + business-rule engine (see §3)
data/booklet_mapping.json    static Document+Line -> Booklet No. mapping (built from the mapping workbook, v3)
scripts/build_booklet_mapping.py  offline: workbook (.xlsx) -> data/booklet_mapping.json (needs openpyxl)
scripts/apply_issued.py      records "Mark as issued" batches into issued_log.json (§5)
site/index.html              the whole frontend (cinematic single-page dashboard, no build step)
site/data/summary.json       the latest computed output (committed by the Action for auditability)
site/data/closed_log.json    first-closed-date ledger, for "Completed Today/Yesterday"
site/data/issued_log.json    which documents have been marked issued (§5)
.github/workflows/deploy.yml       the sync + deploy pipeline
.github/workflows/issue-intake.yml the "mark as issued" write path
```

## 9. Current status / what's pending

This section is a snapshot — for the live, continuously-updated version of this, see the
project's own notes doc if you have access to it (`claude/filter-proof-reads-fix.md` in the
claude.ai Project "Auto Comments completion Dashboard summary", if you're continuing in the same
Claude account/org). If you don't have access to that, everything essential is here and in git
history (`git log`).

As of the last update to this file:
- 9 lots are live (Lot 1 – Lot 9), each read via the Sheets API, fixed-column parsing.
- Lot 9 (tab `lot-09`, gid 23469838) added 2026-10-26. Header in row 1 like every other lot; column P "Assigned To" inserted so Modeller Response sits in Q. Whole documents per person, 13 docs split 3/3/2/3/2 (Hemnath, Dharma, Murukeshwari, Karthikeyan, Kowshik), comment counts balanced as evenly as that split allows.
- Summary, Issuance, and Booklet Issuance screens are all live and wired to real data.
- Booklet Issuance (as of 2026-10-28): 5 booklets, 464 documents, 0 ready; 31 documents not yet in
  any lot. Of those, 30 were extracted, verified against title blocks and packed for checking
  (`Missing 31 FST ISO - For Checking` on the team share, PDF + RLM per document); 2116 is pending
  the 3D team, and 1679's D-16977 line has an RLM but no extraction yet.
- README, CONTRIBUTING, banner and this file reflect Lot 9, the 45-minute schedule (:07 offset),
  document-based booklet readiness and the v3 mapping.
- No other known open bugs at the time of writing.

## 10. How to resume work in a brand-new Claude session

Paste something like this as your first message in the new session:

> I have an existing project at github.com/vikramdex-ops/iso-review-dashboard (live at
> vikramdex-ops.github.io/iso-review-dashboard). Clone it and read HANDOFF.md at the repo root
> first — it has the full architecture, business rules, and current status. Then [describe the
> specific change you want]. Don't re-ask me things HANDOFF.md already answers.

Claude should then: add/clone the repo, read `HANDOFF.md` in full before touching anything, check
`git log` for anything more recent than this file's "Current status" section, and proceed. If a
secret is needed (§6) and missing, it should say so and point you to the setup steps rather than
guessing or asking you to paste a value into chat.
