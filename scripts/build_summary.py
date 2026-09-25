"""Fetch each lot tab as CSV (sheet must be shared 'Anyone with the link: Viewer'),
apply the summary rules, and write site/data/summary.json. No credentials needed."""
import csv, io, json, sys, urllib.request, datetime, pathlib

root = pathlib.Path(__file__).resolve().parent.parent
cfg = json.loads((root / "config.json").read_text())
DONE, HOLD = cfg["done_words"], cfg["hold_words"]
SEV = ["High", "Medium", "Low"]

def fetch(gid):
    url = f"https://docs.google.com/spreadsheets/d/{cfg['sheet_id']}/export?format=csv&gid={gid}"
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode("utf-8")
    if text.lstrip().lower().startswith("<!doctype html"):
        raise RuntimeError("sheet is not publicly readable")
    return list(csv.reader(io.StringIO(text)))

def col(header, name, fallback):
    low = [h.strip().lower() for h in header]
    return low.index(name) if name in low else fallback

def summarise(lot, table):
    h = table[0]
    iM, iN = col(h, "severity", 12), col(h, "status", 13)
    iP, iQ = col(h, "assigned to", 15), col(h, "modeller response", 16)
    stats = {}
    for r in table[1:]:
        r = r + [""] * (max(iM, iN, iP, iQ) + 1 - len(r))
        names = [n.strip() for n in r[iP].split("/") if n.strip()]
        sev = r[iM].strip().capitalize()
        if not names or sev not in SEV:
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
    return rows

rows, status = [], {}
for lot, gid in cfg["lots"].items():
    try:
        rows += summarise(lot, fetch(gid)); status[lot] = "ok"
    except Exception as e:
        status[lot] = f"error: {e}"; print(lot, status[lot], file=sys.stderr)
if not any(v == "ok" for v in status.values()):
    sys.exit("No lot could be read; keeping the previous data.")
out = root / "site" / "data" / "summary.json"
out.write_text(json.dumps({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           "preliminary": False, "status": status, "rows": rows}, indent=1))
(root / "site" / "config.json").write_text(json.dumps(cfg, indent=1))  # keep client-side refresh in sync
print("wrote", out, status)
