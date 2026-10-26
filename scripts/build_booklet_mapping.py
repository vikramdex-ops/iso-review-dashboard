"""Regenerate data/booklet_mapping.json from the booklet workbook (FST_ISO_Booklet_Mapping_v*.xlsx).

Offline tool (needs openpyxl): run it locally whenever a revised workbook arrives, review the
printed checks, and commit the JSON. The sync itself (build_summary.py) only reads the JSON.

    pip install openpyxl
    python3 scripts/build_booklet_mapping.py path/to/FST_ISO_Booklet_Mapping_v2.xlsx

Rules applied (agreed with the project owner, 2026-10-26):
  1. Demolition booklets are excluded from issuance readiness entirely (any booklet whose type
     starts with "Demolition"). They are listed under "excluded_booklets" for transparency only.
  2. The document number comes from the workbook's cleaned "DRAWING NO." column, never the
     "as typed" text (which carries sheet suffixes such as "-01; -02").
  3. A document belongs to one booklet (the workbook's own source-file check). Where a document's
     lines are split across booklets, the line ID (service code + line number, e.g. "D-16977")
     decides, so size/spec/typo differences in tracker line text don't break the match.
  4. Pipe spec family is cross-checked: every GRE line (spec starting "AP") must be in a GRE
     booklet (1755 for area 01, 1722 for area 39) and no non-GRE line may be. The six documents
     the workbook flags as "BREAKS one-line-one-booklet" (2005, 2100, 2134, 2136, 2139, 2140)
     are all GRE area-01 lines, so they are assigned to 1755 by this rule.
  5. Owner-confirmed decisions are recorded in CONFIRMED below and applied last.
  6. A tracker row logged under a different document number is accepted as an alias only when
     the line ID matches exactly AND that other document is not itself in the mapping.
"""
import json, re, sys, datetime, collections, pathlib

try:
    import openpyxl
except ImportError:
    sys.exit("pip install openpyxl first")

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "booklet_mapping.json"
DOC_RE = re.compile(r"P12513-12-\d{2}-15-\d{4}")
LID_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{1,3})-?(\d{4,5})(?!\d)")
SPEC_RE = re.compile(r"-([A-Z]{2})\d[A-Z][0-9O][A-Z0-9]")
GRE_BOOKLET = {"01": "P12513-12-01-15-1755", "39": "P12513-12-39-15-1722"}

# Owner-confirmed booklet decisions: (doc, line_id) -> booklet
CONFIRMED = {
    ("P12513-12-01-15-1678", "D-15260"): ("P12513-12-01-15-1755",
        "Workbook suggestion confirmed by the project owner on 2026-10-26; also GRE spec (rule 4)."),
}
# Tracker aliases verified 2026-10-26 (rule 6): mapped doc -> {line_id: tracker doc}
ALIASES = {
    "P12513-12-01-15-1675": {"NN-12203": "P12513-12-01-15-1963"},   # workbook remark: DRAWING NO. cell reads 1963
    "P12513-12-01-15-1751": {"NN-12077": "P12513-12-01-15-1748"},   # workbook 'as typed' reads 1748
    "P12513-12-39-15-1626": {"D-15647": "P12513-12-39-15-1629"},    # tracker logs this line under 39-15-1629
}


def line_ids(text):
    return sorted({f"{a}-{b}" for a, b in LID_RE.findall((text or "").upper())})


def spec_family(text):
    m = SPEC_RE.search((text or "").upper() + "-")
    return m.group(1) if m else ""


def main(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Booklet Mapping (Doc+Line)"]
    hdr = [c.value for c in ws[1]]
    rows = [dict(zip(hdr, r)) for r in ws.iter_rows(min_row=2, values_only=True) if any(r)]

    excluded = collections.OrderedDict()
    types, items, decisions, problems = {}, [], [], []
    for r in rows:
        btype = (r["Booklet (Line List Type)"] or "").strip()
        bno = (r["Booklet No."] or "").strip()
        if btype.startswith("Demolition"):
            e = excluded.setdefault(bno, {"booklet_type": btype, "items": 0})
            e["items"] += 1
            continue
        doc = str(r["DRAWING NO."] or "").strip()
        line = str(r["Line Number"] or "").strip()
        if not DOC_RE.fullmatch(doc):
            problems.append(f"row {r['#']}: unexpected document number {doc!r}")
            continue
        ids = line_ids(line)
        if len(ids) != 1:
            problems.append(f"row {r['#']}: line {line!r} yields line IDs {ids}")
            continue
        lid = ids[0]
        basis = "workbook"
        if (doc, lid) in CONFIRMED:
            bno, note = CONFIRMED[(doc, lid)]
            basis = "confirmed"
            decisions.append({"doc": doc, "line": line, "booklet_no": bno, "basis": note})
        elif not bno:
            problems.append(f"row {r['#']}: no booklet and no confirmed decision for {doc} / {line}")
            continue
        area = doc.split("-")[2]
        fam = spec_family(line)
        if fam == "AP" and bno != GRE_BOOKLET.get(area):
            old = bno
            bno = GRE_BOOKLET[area]
            basis = "gre_rule"
            decisions.append({"doc": doc, "line": line, "booklet_no": bno,
                              "basis": f"GRE line (spec {fam}...) in area {area}; workbook listed {old[-4:]} "
                                       f"but flags it as breaking one-line-one-booklet; every other GRE line "
                                       f"in the workbook sits in {bno[-4:]}."})
        elif fam != "AP" and bno in GRE_BOOKLET.values():
            problems.append(f"row {r['#']}: non-GRE line {line} mapped to GRE booklet {bno}")
        if btype:
            types[bno] = btype
        it = {"doc": doc, "line": line, "line_id": lid, "booklet_no": bno}
        alias = ALIASES.get(doc, {}).get(lid)
        if alias:
            it["alias_docs"] = [alias]
        items.append((it, basis))

    # one item per (doc, line_id); identical duplicates collapse, conflicting ones are errors
    seen, final = {}, []
    for it, basis in items:
        k = (it["doc"], it["line_id"])
        if k in seen:
            if seen[k]["booklet_no"] != it["booklet_no"]:
                problems.append(f"{k} mapped to both {seen[k]['booklet_no']} and {it['booklet_no']}")
            continue
        it["booklet_type"] = types.get(it["booklet_no"], "")
        seen[k] = it
        final.append(it)

    mapped_docs = {it["doc"] for it in final}
    for it in final:
        for a in it.get("alias_docs", []):
            if a in mapped_docs:
                problems.append(f"alias {a} for {it['doc']} is itself a mapped document (rule 6)")

    per_doc = collections.defaultdict(set)
    for it in final:
        per_doc[it["doc"]].add(it["booklet_no"])
    split_docs = {d: sorted(b) for d, b in per_doc.items() if len(b) > 1}

    if problems:
        print("PROBLEMS — fix before committing:", *problems, sep="\n  ")
        sys.exit(1)

    out = {
        "_source": f"{pathlib.Path(path).name}, sheet 'Booklet Mapping (Doc+Line)'; rebuilt by scripts/build_booklet_mapping.py",
        "_generated": datetime.date.today().isoformat(),
        "_version": 3,
        "_rules": [l.strip() for l in __doc__.split("Rules applied")[1].splitlines()[1:] if l.strip()],
        "excluded_booklets": excluded,
        "split_documents": split_docs,
        "decisions": decisions,
        "items": final,
        "unresolved": [],
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    c = collections.Counter(it["booklet_no"] for it in final)
    print(f"wrote {OUT}: {len(final)} items in {len(c)} booklets; excluded {sum(e['items'] for e in excluded.values())} "
          f"demolition items in {len(excluded)} booklets; {len(decisions)} decisions; split docs {split_docs}")
    for b, n in sorted(c.items()):
        print(f"  {b}  {n:4d}  {types.get(b, '')}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "FST_ISO_Booklet_Mapping_v2.xlsx")
