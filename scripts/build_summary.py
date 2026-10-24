"""Fetch each lot tab (sheet must be shared 'Anyone with the link: Viewer'), apply the summary
rules, and write site/data/summary.json.

Two read paths:
  - Sheets API v4 (used when GOOGLE_SHEETS_API_KEY is set): reads the tab's actual cell values
    server-side. An active "Data > Create a filter" on a tab is a UI/display-layer construct —
    the API ignores it and returns every row, exactly as a lead manually opening the sheet
    would see once they cleared the filter. This is the filter-proof path and is what runs in
    production (the key is a GitHub Actions secret, never exposed client-side).
  - Public CSV export (fallback when no key is configured, e.g. local/dev runs): simple and
    credential-free, but reflects whatever the tab's live filtered VIEW shows, so a filter left
    on by a team member working the sheet hides those rows from the export for everyone,
    including us. Fine for a quick local check; not what production should rely on.
"""
import csv, io, json, os, re, sys, urllib.request, urllib.parse, hashlib, datetime, pathlib
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

root = pathlib.Path(__file__).resolve().parent.parent
cfg = json.loads((root / "config.json").read_text())
DONE, HOLD = cfg["done_words"], cfg["hold_words"]
SEV = ["High", "Medium", "Low"]
TODAY_IST = datetime.datetime.now(IST).date().isoformat()
CLOSED_LOG_PATH = root / "site" / "data" / "closed_log.json"
ISSUED_LOG_PATH = root / "site" / "data" / "issued_log.json"
SUMMARY_PATH = root / "site" / "data" / "summary.json"
ADDRESS_THRESHOLD = 3  # a document with this many or fewer open/hold points is "almost ready"

GOOGLE_SHEETS_API_KEY = os.environ.get("GOOGLE_SHEETS_API_KEY", "").strip()
FETCH_METHOD = "sheets_api" if GOOGLE_SHEETS_API_KEY else "csv_export"
_sheet_titles_cache = None   # gid (str) -> title
_title_to_gid_cache = None   # title -> gid (str)

def fetch_url(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode("utf-8")
    if text.lstrip().lower().startswith("<!doctype html") or text.lstrip().startswith("<HTML"):
        raise RuntimeError("got an HTML error page, not data (bad gid/sheet name, bad API key, "
                            "or not shared)")
    return text

def _load_sheet_metadata():
    """Fetch the spreadsheet's tab list once per run (gid <-> title, both directions)."""
    global _sheet_titles_cache, _title_to_gid_cache
    if _sheet_titles_cache is None:
        url = (f"https://sheets.googleapis.com/v4/spreadsheets/{cfg['sheet_id']}"
               f"?fields=sheets.properties&key={GOOGLE_SHEETS_API_KEY}")
        data = json.loads(fetch_url(url))
        props = [s["properties"] for s in data.get("sheets", [])]
        _sheet_titles_cache = {str(p["sheetId"]): p["title"] for p in props}
        _title_to_gid_cache = {p["title"]: str(p["sheetId"]) for p in props}

def _resolve_sheet_title(gid):
    """gid -> tab title, via the spreadsheet's own metadata (not affected by filters)."""
    _load_sheet_metadata()
    title = _sheet_titles_cache.get(str(gid))
    if not title:
        raise RuntimeError(f"gid {gid} not found in this spreadsheet's tab list (Sheets API metadata)")
    return title

def resolve_lot_ref(ref):
    """A config.json lot value is either a numeric gid (string, e.g. "31577278" — the stable,
    rename-proof way to point at a tab) or "title:<Tab Name>" to have the gid looked up by the
    tab's current name via the Sheets API — handy for onboarding a new lot without having to dig
    its gid out of the sheet's URL. Title lookup needs GOOGLE_SHEETS_API_KEY."""
    if isinstance(ref, str) and ref.startswith("title:"):
        if not GOOGLE_SHEETS_API_KEY:
            raise RuntimeError(
                f"this lot is configured by tab title ({ref!r}) but GOOGLE_SHEETS_API_KEY isn't "
                f"set — title lookup needs the Sheets API; use a numeric gid instead for a "
                f"key-less run, or set the key"
            )
        _load_sheet_metadata()
        title = ref[len("title:"):]
        gid = _title_to_gid_cache.get(title)
        if not gid:
            raise RuntimeError(f"no tab named {title!r} found in the spreadsheet (checked via Sheets API)")
        return gid
    return str(ref)

def fetch_via_api(gid):
    """Sheets API v4 values.get — the filter-proof read. valueRenderOption=FORMATTED_VALUE
    mirrors what CSV export would show (so downstream parsing in summarise() doesn't need to
    change), the difference is this bypasses the tab's live filtered view entirely."""
    title = _resolve_sheet_title(gid)
    range_ = urllib.parse.quote(f"'{title.replace(chr(39), chr(39) * 2)}'")
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{cfg['sheet_id']}/values/{range_}"
           f"?key={GOOGLE_SHEETS_API_KEY}&valueRenderOption=FORMATTED_VALUE&majorDimension=ROWS")
    raw_json = fetch_url(url)
    values = json.loads(raw_json).get("values", [])
    table = [["" if c is None else str(c) for c in row] for row in values]
    return table, raw_json

def fetch_via_csv(gid):
    """Public CSV export by numeric gid only. (gviz / sheet-name lookups silently fall back to
    the FIRST tab when they can't match, which previously produced duplicated lots.) Subject to
    whatever filter is currently active on the tab — see module docstring."""
    text = fetch_url(f"https://docs.google.com/spreadsheets/d/{cfg['sheet_id']}/export?format=csv&gid={gid}")
    return list(csv.reader(io.StringIO(text))), text

def fetch(gid):
    if GOOGLE_SHEETS_API_KEY:
        return fetch_via_api(gid)
    return fetch_via_csv(gid)

def col(header, name, fallback):
    low = [h.strip().lower() for h in header]
    return low.index(name) if name in low else fallback

def natkey(s):
    """Natural sort so 'DOC-2' sorts before 'DOC-10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

def _norm(s):
    """Normalise a doc/line string for cross-source matching (lot trackers vs. the static
    booklet-mapping workbook): collapse whitespace, uppercase, strip."""
    return re.sub(r"\s+", " ", (s or "").strip()).upper()

def summarise(lot, table):
    h = table[0]
    iM, iN = col(h, "severity", 12), col(h, "status", 13)
    iP, iQ = col(h, "assigned to", 15), col(h, "modeller responce", col(h, "modeller response", 16))
    iCmt, iDoc = col(h, "comment no.", 0), col(h, "document no.", 1)
    iLine = col(h, "line number", 2)
    sample = {"header_cols": len(h), "header": h[:20],
              "iM": iM, "iN": iN, "iP": iP, "iQ": iQ, "iCmt": iCmt, "iDoc": iDoc, "iLine": iLine,
              "rows_at": {}}
    for i in [1, 100, 300, 500, 800, 1200, 1700, 2000]:
        if i < len(table):
            r = table[i]
            rr = r + [""] * (max(iM, iN, iP, iQ) + 1 - len(r))
            sample["rows_at"][i + 1] = {"colA": r[0][:20], "severity": rr[iM], "assignedTo": rr[iP]}
    stats = {}
    raw_rows = len(table) - 1
    named_rows = 0       # column P non-blank, regardless of severity
    no_severity = 0       # named but severity not High/Medium/Low -> excluded, flagged for review
    row_states = []        # per-row identity + current closed state, for day-over-day diffing
    # Document-level tracking is independent of assignee/severity: a document is only "ready to
    # issue" once EVERY comment against it is closed, regardless of who owns which comment.
    docs = {}
    line_rows = []  # every row with both doc + line populated, for cross-lot booklet matching
    for i, r in enumerate(table[1:], start=2):
        r = r + [""] * (max(iM, iN, iP, iQ, iCmt, iDoc, iLine) + 1 - len(r))
        status_l, resp_l = r[iN].strip().lower(), r[iQ].strip().lower()
        is_closed = status_l == "closed" or any(w in resp_l for w in DONE)

        docno = r[iDoc].strip()
        if docno:
            line = r[iLine].strip()
            d = docs.setdefault(docno, {"total": 0, "open": 0, "lines_all": [], "lines_open": []})
            d["total"] += 1
            d["lines_all"].append(line)
            if not is_closed:
                d["open"] += 1
                d["lines_open"].append(line)
            if line:
                line_rows.append({"doc": docno, "line": line, "closed": is_closed, "lot": lot})

        names = [n.strip() for n in r[iP].split("/") if n.strip()]
        if not names:
            continue
        named_rows += 1
        sev = r[iM].strip().capitalize()
        if sev not in SEV:
            no_severity += 1
            continue
        who = " ".join(w.capitalize() for w in names[-1].split())  # normalise casing so "DHARMA"/"Dharma" merge
        b = stats.setdefault(who, {s: [0, 0, 0, 0] for s in SEV})[sev]  # assigned, closed, open, hold
        b[0] += 1
        if is_closed: b[1] += 1
        elif any(w in resp_l for w in HOLD): b[3] += 1
        else: b[2] += 1
        key = f"{lot}|{r[iCmt].strip() or i}|{r[iDoc].strip()}"  # row number as fallback if Comment No. is blank
        row_states.append({"key": key, "who": who, "lot": lot, "closed": is_closed})
    rows = []
    for who, s in sorted(stats.items()):
        H, M, L = s["High"], s["Medium"], s["Low"]
        tot, cl = H[0] + M[0] + L[0], H[1] + M[1] + L[1]
        rows.append([who, lot, H[0], H[1], H[2], M[0], M[1], M[2], L[0], L[1], L[2],
                     H[3], M[3], L[3], tot, cl, tot - cl, 0])  # last col filled in later: completed today
    counted = sum(r[14] for r in rows)
    diag = {"raw_rows": raw_rows, "named_rows": named_rows, "counted": counted,
            "excluded_no_severity": no_severity, "excluded_blank_name": raw_rows - named_rows,
            "debug": sample}
    return rows, diag, row_states, docs, line_rows

def classify_documents(docs):
    """docs: {docno: {total, open, lines_all, lines_open}} -> ready / address / needs_work doc-number lists."""
    ready = sorted((d for d, v in docs.items() if v["open"] == 0), key=natkey)
    address = sorted((d for d, v in docs.items() if 0 < v["open"] <= ADDRESS_THRESHOLD), key=natkey)
    needs_work = sorted((d for d, v in docs.items() if v["open"] > ADDRESS_THRESHOLD), key=natkey)
    return ready, address, needs_work

def build_lot_documents(lot, docs, issued_log):
    ready, address, needs_work = classify_documents(docs)
    ready_issued = [d for d in ready if f"{lot}|{d}" in issued_log]
    ready_pending = [d for d in ready if f"{lot}|{d}" not in issued_log]

    def lines_for(doclist, key):
        out = []
        for d in doclist:
            out.extend(docs[d][key])
        return out

    return {
        "total_documents": len(docs),
        "ready_pending": {"count": len(ready_pending), "docs": ready_pending,
                           "lines": lines_for(ready_pending, "lines_all")},
        "ready_issued": {"count": len(ready_issued), "docs": ready_issued,
                          "lines": lines_for(ready_issued, "lines_all")},
        "address": {"count": len(address), "docs": address,
                    "lines": lines_for(address, "lines_open"),
                    "detail": [{"doc": d, "open": docs[d]["open"]} for d in address]},
        "needs_work": {"count": len(needs_work), "docs": needs_work},
    }

BOOKLET_MAPPING_PATH = root / "data" / "booklet_mapping.json"

def load_booklet_mapping():
    """Static (doc, line) -> Booklet No. mapping, extracted once from the user's ISO booklet
    workbook. Returns None if the file isn't present (booklet feature silently disabled)."""
    if not BOOKLET_MAPPING_PATH.exists():
        return None
    return json.loads(BOOKLET_MAPPING_PATH.read_text())

def build_booklet_readiness(booklet_mapping, all_line_rows):
    """A booklet is ready only when EVERY (doc, line) pair mapped to it is closed, across ALL
    lots combined — booklets routinely span more than one lot. A mapped pair that has no
    matching row in any lot's tracker at all is "blocked_missing": it was never captured by any
    lot, so it can't silently count as either open or closed."""
    if booklet_mapping is None:
        return None
    # index live rows by normalised (doc, line) -> {"closed": bool, "lots": [lot, ...]}
    live = {}
    for r in all_line_rows:
        key = (_norm(r["doc"]), _norm(r["line"]))
        entry = live.setdefault(key, {"closed": True, "lots": []})
        entry["lots"].append(r["lot"])
        if not r["closed"]:
            entry["closed"] = False  # any open occurrence of this pair keeps it open

    booklets = {}
    unresolved = []
    for item in booklet_mapping.get("resolved", []):
        bno = item["booklet_no"]
        b = booklets.setdefault(bno, {
            "booklet_no": bno, "booklet_type": item.get("booklet_type", ""),
            "total": 0, "closed": 0, "open_items": [], "missing_items": [],
        })
        key = (_norm(item["doc"]), _norm(item["line"]))
        b["total"] += 1
        found = live.get(key)
        if found is None:
            b["missing_items"].append({"doc": item["doc"], "line": item["line"]})
        elif found["closed"]:
            b["closed"] += 1
        else:
            b["open_items"].append({"doc": item["doc"], "line": item["line"],
                                     "found_in_lots": sorted(set(found["lots"]))})

    for bno, b in booklets.items():
        missing = len(b["missing_items"])
        open_ = len(b["open_items"])
        if missing > 0:
            b["status"] = "blocked_missing"
        elif open_ == 0:
            b["status"] = "ready"
        else:
            b["status"] = "not_ready"

    for item in booklet_mapping.get("unresolved", []):
        key = (_norm(item["doc"]), _norm(item["line"]))
        found = live.get(key)
        unresolved.append({
            "doc": item["doc"], "line": item["line"],
            "suggested_booklet_no": item.get("suggested_booklet_no", ""),
            "closed": (found["closed"] if found else None),
            "found_in_lots": (sorted(set(found["lots"])) if found else []),
        })

    totals = {
        "booklets": len(booklets),
        "ready": sum(1 for b in booklets.values() if b["status"] == "ready"),
        "not_ready": sum(1 for b in booklets.values() if b["status"] == "not_ready"),
        "blocked_missing": sum(1 for b in booklets.values() if b["status"] == "blocked_missing"),
        "total_items": sum(b["total"] for b in booklets.values()),
        "total_missing": sum(len(b["missing_items"]) for b in booklets.values()),
    }
    return {"totals": totals, "list": booklets, "unresolved": unresolved}

# --- Load previous sync so a single bad read (duplicate tab, or a filter hiding rows on the
# sheet) can fall back to last-known-good data for just that lot, instead of corrupting the
# whole dashboard or silently under-counting. ---
prev = json.loads(SUMMARY_PATH.read_text()) if SUMMARY_PATH.exists() else {}
prev_status = prev.get("status", {})
prev_rows_by_lot = {}
for r in prev.get("rows", []):
    prev_rows_by_lot.setdefault(r[1], []).append(r)
prev_documents = prev.get("documents", {})
prev_docs_raw = prev.get("_docs_raw", {})  # internal, not meant for the frontend; see below
prev_line_rows_by_lot = {}
for lr in prev.get("_line_rows_raw", []):
    prev_line_rows_by_lot.setdefault(lr["lot"], []).append(lr)

issued_log = json.loads(ISSUED_LOG_PATH.read_text()) if ISSUED_LOG_PATH.exists() else {}

rows, status, hashes, all_row_states, docs_raw_by_lot, all_line_rows = [], {}, {}, [], {}, []
for lot, lot_cfg in cfg["lots"].items():
    try:
        lot_gid = resolve_lot_ref(lot_cfg)
        table, raw_text = fetch(lot_gid)
        h = hashlib.sha256(raw_text.encode()).hexdigest()[:12]
        dup = next((other for other, oh in hashes.items() if oh == h), None)
        if dup:
            raise RuntimeError(f"fetched content is byte-identical to '{dup}' — gid/sheet_name for "
                                f"'{lot}' is almost certainly wrong and is pulling the same tab")
        hashes[lot] = h
        lot_rows, diag, row_states, docs_raw, line_rows = summarise(lot, table)

        prev_raw = prev_status.get(lot, {}).get("raw_rows")
        if prev_raw is not None and diag["raw_rows"] < prev_raw:
            # Row count should only ever grow (or hold steady). Over the CSV-export path a drop
            # almost always means a filter (an actual Data > Create a filter, not a filter
            # *view*) is live on the tab, which makes the export silently omit hidden rows. Over
            # the Sheets-API path that can't happen — the API reads the tab's real values
            # regardless of any filter — so a drop there means rows were actually deleted or the
            # tab was restructured, and still deserves a stop-and-check rather than a silent
            # undercount.
            if FETCH_METHOD == "sheets_api":
                raise RuntimeError(
                    f"row count dropped from {prev_raw} to {diag['raw_rows']} on '{lot}' — this "
                    f"was read via the Sheets API, which isn't affected by filters, so this looks "
                    f"like rows were actually deleted or the tab was restructured; refusing this "
                    f"read and keeping the last known-good data for '{lot}' until it's checked"
                )
            raise RuntimeError(
                f"row count dropped from {prev_raw} to {diag['raw_rows']} — looks like a filter "
                f"is active on the '{lot}' tab, which hides rows from the CSV export too; "
                f"refusing this read and keeping the last known-good data for '{lot}'. Set "
                f"GOOGLE_SHEETS_API_KEY to read filter-proof instead."
            )

        rows += lot_rows
        all_row_states += row_states
        docs_raw_by_lot[lot] = docs_raw
        all_line_rows += line_rows
        diag["content_hash"] = h
        diag["gid"] = lot_gid
        diag["fetch_method"] = FETCH_METHOD
        status[lot] = diag
        print(f"[{lot}] raw_rows={diag['raw_rows']} named_rows={diag['named_rows']} "
              f"counted={diag['counted']} excluded_no_severity={diag['excluded_no_severity']} "
              f"excluded_blank_name={diag['excluded_blank_name']} documents={len(docs_raw)} hash={h}")
    except Exception as e:
        status[lot] = {"error": str(e)}
        # Fall back to the previous sync's rows/documents for this lot only, so a transient bad
        # read for one lot never erases or under-counts that lot on the live dashboard.
        if lot in prev_rows_by_lot or lot in prev_documents:
            status[lot]["stale_data_from_previous_sync"] = True
            rows += prev_rows_by_lot.get(lot, [])
            if lot in prev_docs_raw:
                docs_raw_by_lot[lot] = prev_docs_raw[lot]
        print(f"[{lot}] ERROR: {e}", file=sys.stderr)

ok_lots = [l for l, s in status.items() if "error" not in s]
if not ok_lots:
    sys.exit("No lot could be read; aborting so the previously deployed site is left untouched.")
if len(ok_lots) < len(cfg["lots"]):
    print(f"WARNING: only {ok_lots} succeeded; some lots are missing from this build.", file=sys.stderr)
    print("Skipping the closed-today log this run so a partial fetch can't wrongly mark rows "
          "from the missing lot(s) as reopened.", file=sys.stderr)
    for row in rows:
        row.append(0)  # col 18: completed yesterday (unknown this run, keep row shape consistent)
else:
    # --- "Completed Today" tracking ---
    # The sheet has no close-date column, so we keep our own log: the first day each row is
    # ever observed closed gets recorded, and that date sticks even if the sheet is re-synced
    # many times today or re-read tomorrow. A row that's currently open is simply absent.
    first_run = not CLOSED_LOG_PATH.exists()
    old_log = json.loads(CLOSED_LOG_PATH.read_text()) if not first_run else {}
    new_log = {}
    for r in all_row_states:
        if not r["closed"]:
            continue
        if r["key"] in old_log:
            new_log[r["key"]] = old_log[r["key"]]  # keep original close date
        else:
            # On the very first run we don't know when these were actually closed, so they're
            # dated "baseline" (never equals a real date) instead of inflating day one's count.
            new_log[r["key"]] = "baseline" if first_run else TODAY_IST
    CLOSED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLOSED_LOG_PATH.write_text(json.dumps(new_log, indent=1))

    YESTERDAY_IST = (datetime.date.fromisoformat(TODAY_IST) - datetime.timedelta(days=1)).isoformat()
    completed_today, completed_yesterday = {}, {}
    for r in all_row_states:
        d = new_log.get(r["key"])
        if d == TODAY_IST:
            completed_today[(r["lot"], r["who"])] = completed_today.get((r["lot"], r["who"]), 0) + 1
        elif d == YESTERDAY_IST:
            completed_yesterday[(r["lot"], r["who"])] = completed_yesterday.get((r["lot"], r["who"]), 0) + 1
    for row in rows:
        row[17] = completed_today.get((row[1], row[0]), 0)
        row.append(completed_yesterday.get((row[1], row[0]), 0))  # col 18: completed yesterday, for context after the midnight reset
    print(f"Completed today ({TODAY_IST}):", {f"{k[1]} ({k[0]})": v for k, v in completed_today.items()} or "none")
    print(f"Completed yesterday ({YESTERDAY_IST}):", {f"{k[1]} ({k[0]})": v for k, v in completed_yesterday.items()} or "none")

# --- Combined view: same rows, aggregated per assignee across every lot (Lot 1-4, ignoring
# lot segregation) so the reviewer can also see one line per person for the whole register. ---
COMBINED_LABEL = "All Lots (combined)"
combined_map = {}
for r in rows:
    who, vals = r[0], r[2:]
    if who not in combined_map:
        combined_map[who] = [0] * len(vals)
    combined_map[who] = [a + b for a, b in zip(combined_map[who], vals)]
combined_rows = [[who, COMBINED_LABEL] + vals for who, vals in sorted(combined_map.items())]

# --- Issuance view: per lot, which documents are fully closed (ready to issue / already
# issued), which are almost there (<=3 open points, "address these"), and which still need
# real work. Independent of assignee on purpose. ---
documents_out = {lot: build_lot_documents(lot, docs, issued_log) for lot, docs in docs_raw_by_lot.items()}

# --- Booklet Issuance view: static (doc, line) -> Booklet No. mapping (from the user's ISO
# booklet workbook) crossed against every lot's live rows, irrespective of which lot a given
# comment happens to live in. Falls back to the previous sync's line-rows for any lot that
# errored this run, same stale-data protection as the Summary/Issuance views. ---
for lot in cfg["lots"]:
    if lot not in docs_raw_by_lot and lot in prev_line_rows_by_lot:
        all_line_rows += prev_line_rows_by_lot[lot]
booklet_mapping = load_booklet_mapping()
booklets_out = build_booklet_readiness(booklet_mapping, all_line_rows)

out = root / "site" / "data" / "summary.json"
out.write_text(json.dumps({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           "preliminary": False, "today": TODAY_IST, "status": status, "rows": rows,
                           "combined": combined_rows, "documents": documents_out,
                           "booklets": booklets_out,
                           "_docs_raw": docs_raw_by_lot,
                           "_line_rows_raw": all_line_rows}, indent=1))
(root / "site" / "config.json").write_text(json.dumps(cfg, indent=1))  # keep client-side refresh in sync
print("wrote", out)
print("TOTAL_ASSIGNED_ACROSS_LOTS", sum(r[14] for r in rows))
print("DOCUMENTS", {lot: d["total_documents"] for lot, d in documents_out.items()})
print("READY_TO_ISSUE_PENDING", {lot: d["ready_pending"]["count"] for lot, d in documents_out.items()})
if booklets_out:
    print("BOOKLETS", booklets_out["totals"])
