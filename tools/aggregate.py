# /// script
# requires-python = ">=3.10"
# ///
"""Summarise the scores for the programme chair.

  uv run tools/aggregate.py scores.csv [more.csv ...] > summary.csv

Input: the "scores" sheet exported as CSV from the Google Sheet, and/or the CSV
files reviewers download from the site. The newest record per reviewer and
submission wins. Co-author records never count as scores.
"""
import csv
import statistics
import sys
from collections import defaultdict

CRIT = ["fit", "accessibility", "quality", "novelty"]
RECS = ["talk_top", "talk", "poster", "hackathon", "reject"]


def truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def main(paths: list[str]) -> None:
    latest = {}
    for p in paths:
        with open(p, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                key = (r.get("reviewer", ""), r.get("submission", ""))
                if not key[1]:
                    continue
                try:
                    t = float(r.get("saved_at") or 0)
                except ValueError:
                    t = 0.0
                if key not in latest or t >= latest[key][0]:
                    latest[key] = (t, r)

    by_sub = defaultdict(list)
    for (rev, sub), (_, r) in latest.items():
        by_sub[sub].append((rev, r))

    w = csv.writer(sys.stdout)
    w.writerow(["submission", "n_reviews", "n_scored"] + [f"mean_{c}" for c in CRIT] + ["mean_overall"]
               + [f"votes_{x}" for x in RECS] + ["coi_coauthor", "coi_knows", "reviewers", "notes"])
    for sub in sorted(by_sub):
        rows = by_sub[sub]
        scored = [r for _, r in rows if truthy(r.get("complete")) and r.get("coi") != "coauthor"]
        means = []
        for c in CRIT:
            vals = [float(r[c]) for r in scored if r.get(c) not in (None, "")]
            means.append(round(statistics.mean(vals), 2) if vals else "")
        allv = [float(r[c]) for r in scored for c in CRIT if r.get(c) not in (None, "")]
        overall = round(statistics.mean(allv), 2) if allv else ""
        recs = [r.get("recommendation", "") for r in scored]
        w.writerow([sub, len(rows), len(scored)] + means + [overall]
                   + [recs.count(x) for x in RECS]
                   + [sum(1 for _, r in rows if r.get("coi") == "coauthor"),
                      sum(1 for _, r in rows if r.get("coi") == "knows"),
                      " ".join(rev for rev, _ in sorted(rows)),
                      " | ".join(f"{rev}: {r.get('note', '')}" for rev, r in sorted(rows) if r.get("note"))])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
