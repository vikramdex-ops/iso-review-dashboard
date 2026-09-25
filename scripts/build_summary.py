"""Fetch each lot tab as CSV (sheet must be shared 'Anyone with the link: Viewer'),
apply the summary rules, and write site/data/summary.json. No credentials needed."""
import csv, io, json, sys, urllib.request, urllib.parse, hashlib, datetime, pathlib

root = pathlib.Path(__file__).resolve().parent.parent
cfg = json.loads((root / "config.json").read_text())
DONE, HOLD = cfg["done_words"], cfg["hold_words"]
SEV = ["High", "Medium", "Low"]

def fetch_url(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode("utf-8")
    if text.lstrip().lower().startswith("<!doctype html") or text.lstrip().startswith("<HTML"):
        raise RuntimeError("got an HTML error page, not CSV (bad gid/sheet name or not shared)")
    return text

def fetch(lot_cfg):
    """lot_cfg is either a bare gid (legacy) or {"gid":.., "sheet_name":..}.
    Tries sheet-name addressing first (robust to gid drift), falls back to gid."""
    if isinstance(lot_cfg, str):
        lot_cfg = {"gid": lot_cfg}
    errs = []
    if lot_cfg.get("sheet_name"):
        try:
            name = urllib.parse.quote(lot_cfg["sheet_name"])
            text = fetch_url(f"https://docs.google.com/spreadsheets/d/{cfg['sheet_id']}/gviz/tq?tqx=out:csv&sheet={name}")
            return list(csv.reader(io.StringIO(text))), text
        except Exception as e:
            errs.append(f"by name: {e}")
    if lot_cfg.get("gid"):
        try:
            text = fetch_url(f"https://docs.google.com/spreadsheets/d/{cfg['sheet_id']}/export?format=csv&gid={lot_cfg['gid']}")
            return list(csv.reader(io.StringIO(text))), text
        except Exception as e:
            errs.append(f"by gid: {e}")
    raise RuntimeError("; ".join(errs) or "no gid or sheet_name configured")

def col(header, name, fallback):
    low = [h.strip().lower() for h in header]
    return low.index(name) if name in low else fallback

def summarise(lot, table):
    h = table[0]
    iM, iN = col(h, "severity", 12), col(h, "status", 13)
    iP, iQ = col(h, "assigned to", 15), col(h, "modeller response", 16)
    stats = {}
    raw_rows = len(table) - 1
    named_rows = 0       # column P non-blank, regardless of severity
    no_severity = 0       # named but severity not High/Medium/Low -> excluded, flagged for review
    for r in table[1:]:
        r = r + [""] * (max(iM, iN, iP, iQ) + 1 - len(r))
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
        if status == "closed" or any(w in resp for w in DONE): b[1] += 1
        elif any(w in resp for w in HOLD): b[3] += 1
        else: b[2] += 1
    rows = []
    for who, s in sorted(stats.items()):
        H, M, L = s["High"], s["Medium"], s["Low"]
        tot, cl = H[0] + M[0] + L[0], H[1] + M[1] + L[1]
        rows.append([who, lot, H[0], H[1], H[2], M[0], M[1], M[2], L[0], L[1], L[2],
                     H[3], M[3], L[3], tot, cl, tot - cl])
    counted = sum(r[14] for r in rows)
    diag = {"raw_rows": raw_rows, "named_rows": named_rows, "counted": counted,
            "excluded_no_severity": no_severity, "excluded_blank_name": raw_rows - named_rows}
    return rows, diag

rows, status, hashes = [], {}, {}
for lot, lot_cfg in cfg["lots"].items():
    try:
        table, raw_text = fetch(lot_cfg)
        h = hashlib.sha256(raw_text.encode()).hexdigest()[:12]
        dup = next((other for other, oh in hashes.items() if oh == h), None)
        if dup:
            raise RuntimeError(f"fetched content is byte-identical to '{dup}' — gid/sheet_name for "
                                f"'{lot}' is almost certainly wrong and is pulling the same tab")
        hashes[lot] = h
        lot_rows, diag = summarise(lot, table)
        rows += lot_rows
        diag["content_hash"] = h
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

out = root / "site" / "data" / "summary.json"
out.write_text(json.dumps({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           "preliminary": False, "status": status, "rows": rows}, indent=1))
(root / "site" / "config.json").write_text(json.dumps(cfg, indent=1))  # keep client-side refresh in sync
print("wrote", out)
print("TOTAL_ASSIGNED_ACROSS_LOTS", sum(r[14] for r in rows))
