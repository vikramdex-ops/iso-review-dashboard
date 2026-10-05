"""Fetch each lot tab as CSV (sheet must be shared 'Anyone with the link: Viewer'),
apply the summary rules, and write site/data/summary.json. No credentials needed."""
import csv, io, json, sys, urllib.request, urllib.parse, hashlib, datetime, pathlib
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

def fetch_url(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode("utf-8")
    if text.lstrip().lower().startswith("<!doctype html") or text.lstrip().startswith("<HTML"):
        raise RuntimeError("got an HTML error page, not CSV (bad gid/sheet name or not shared)")
    return text

def fetch(gid):
    """Export by numeric gid only. (gviz / sheet-name lookups silently fall back to the
    FIRST tab when they can't match, which produced duplicated lots.)"""
    text = fetch_url(f"https://docs.google.com/spreadsheets/d/{cfg['sheet_id']}/export?format=csv&gid={gid}")
    return list(csv.reader(io.StringIO(text))), text

def col(header, name, fallback):
    low = [h.strip().lower() for h in header]
    return low.index(name) if name in low else fallback

def summarise(lot, table):
    h = table[0]
    iM, iN = col(h, "severity", 12), col(h, "status", 13)
    iP, iQ = col(h, "assigned to", 15), col(h, "modeller responce", col(h, "modeller response", 16))
    iCmt, iDoc = col(h, "comment no.", 0), col(h, "document no.", 1)
    sample = {"header_cols": len(h), "header": h[:20],
              "iM": iM, "iN": iN, "iP": iP, "iQ": iQ,
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
    for i, r in enumerate(table[1:], start=2):
        r = r + [""] * (max(iM, iN, iP, iQ, iCmt, iDoc) + 1 - len(r))
        names = [n.strip() for n in r[iP].split("/") if n.strip()]
        if not names:
            continue
        named_rows += 1
        sev = r[iM].strip().capitalize()
        if sev not in SEV:
            no_severity += 1
            continue
        who = " ".join(w.capitalize() for w in names[-1].split())  # normalise casing so "DHARMA"/"Dharma" merge
        status, resp = r[iN].strip().lower(), r[iQ].strip().lower()
        b = stats.setdefault(who, {s: [0, 0, 0, 0] for s in SEV})[sev]  # assigned, closed, open, hold
        b[0] += 1
        is_closed = status == "closed" or any(w in resp for w in DONE)
        if is_closed: b[1] += 1
        elif any(w in resp for w in HOLD): b[3] += 1
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
    return rows, diag, row_states

rows, status, hashes, all_row_states = [], {}, {}, []
for lot, lot_cfg in cfg["lots"].items():
    try:
        table, raw_text = fetch(lot_cfg)
        h = hashlib.sha256(raw_text.encode()).hexdigest()[:12]
        dup = next((other for other, oh in hashes.items() if oh == h), None)
        if dup:
            raise RuntimeError(f"fetched content is byte-identical to '{dup}' — gid/sheet_name for "
                                f"'{lot}' is almost certainly wrong and is pulling the same tab")
        hashes[lot] = h
        lot_rows, diag, row_states = summarise(lot, table)
        rows += lot_rows
        all_row_states += row_states
        diag["content_hash"] = h
        diag["gid"] = lot_cfg
        status[lot] = diag
        print(f"[{lot}] raw_rows={diag['raw_rows']} named_rows={diag['named_rows']} "
              f"counted={diag['counted']} excluded_no_severity={diag['excluded_no_severity']} "
              f"excluded_blank_name={diag['excluded_blank_name']} hash={h}")
    except Exception as e:
        status[lot] = {"error": str(e)}
        print(f"[{lot}] ERROR: {e}", file=sys.stderr)

ok_lots = [l for l, s in status.items() if "error" not in s]
if not ok_lots:
    sys.exit("No lot could be read; aborting so the previously deployed site is left untouched.")
if len(ok_lots) < len(cfg["lots"]):
    print(f"WARNING: only {ok_lots} succeeded; some lots are missing from this build.", file=sys.stderr)
    print("Skipping the closed-today log this run so a partial fetch can't wrongly mark rows "
          "from the missing lot(s) as reopened.", file=sys.stderr)
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

    completed_today = {}  # (lot, who) -> count
    for r in all_row_states:
        if new_log.get(r["key"]) == TODAY_IST:
            completed_today[(r["lot"], r["who"])] = completed_today.get((r["lot"], r["who"]), 0) + 1
    for row in rows:
        row[17] = completed_today.get((row[1], row[0]), 0)
    print(f"Completed today ({TODAY_IST}):", {f"{k[1]} ({k[0]})": v for k, v in completed_today.items()} or "none")

out = root / "site" / "data" / "summary.json"
out.write_text(json.dumps({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           "preliminary": False, "today": TODAY_IST, "status": status, "rows": rows}, indent=1))
(root / "site" / "config.json").write_text(json.dumps(cfg, indent=1))  # keep client-side refresh in sync
print("wrote", out)
print("TOTAL_ASSIGNED_ACROSS_LOTS", sum(r[14] for r in rows))
