"""Parse an 'Issue documents — <lot> — <date>' GitHub issue and record its document numbers
as issued in site/data/issued_log.json. Run by .github/workflows/issue-intake.yml."""
import datetime, json, os, pathlib, re, sys

root = pathlib.Path(__file__).resolve().parent.parent
body = os.environ.get("ISSUE_BODY") or ""
number = os.environ.get("ISSUE_NUMBER") or "0"

lot_m = re.search(r"^Lot:\s*(.+)$", body, re.MULTILINE)
if not lot_m:
    sys.exit("Could not find a 'Lot: <name>' line in the issue body — was this issue opened by the dashboard's 'Mark as issued' button?")
lot = lot_m.group(1).strip()

block_m = re.search(r"```[a-zA-Z]*\n(.*?)```", body, re.DOTALL)
if not block_m:
    sys.exit("Could not find a fenced code block with document numbers in the issue body.")
docs = [line.strip() for line in block_m.group(1).splitlines() if line.strip()]
if not docs:
    sys.exit("No document numbers found inside the fenced code block.")

log_path = root / "site" / "data" / "issued_log.json"
log = json.loads(log_path.read_text()) if log_path.exists() else {}
now = datetime.datetime.now(datetime.timezone.utc).isoformat()

added = []
for d in docs:
    key = f"{lot}|{d}"
    if key not in log:
        log[key] = {"issued_at": now, "issue": int(number)}
        added.append(d)

log_path.parent.mkdir(parents=True, exist_ok=True)
log_path.write_text(json.dumps(log, indent=1, sort_keys=True))

already = len(docs) - len(added)
summary = f"Marked {len(added)} document(s) as issued for {lot}."
if already:
    summary += f" {already} were already marked as issued (no change)."
print(summary)
print("Documents:", ", ".join(docs))

gh_out = os.environ.get("GITHUB_OUTPUT")
if gh_out:
    with open(gh_out, "a") as fh:
        fh.write(f"summary={summary}\n")
        fh.write(f"changed={'true' if added else 'false'}\n")
