# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl>=3.1"]
# ///
"""Write a fake Microsoft Forms export, to try the site before real data exists.

  uv run tools/fake_export.py /tmp/fake_export.xlsx
"""
import random
import sys

from openpyxl import Workbook

HEADERS = ["ID", "Start time", "Completion time", "Email", "Name", "Career stage", "Job type",
           "History with PSE", "Title", "Abstract", "Proposal format"]
STAGES = ["PhD student", "Postdoc", "Assistant professor", "Associate professor", "Professor", "Other"]
JOBS = ["University", "Research institute", "Industry", "Independent"]
HISTORY = ["First time", "Attended before", "Presented before"]
FORMATS = ["Talk", "Poster", "Either", "Hackathon"]
TOPICS = ["replication", "retraction", "peer review", "p-hacking", "AI scientists", "error detection",
          "statistical power", "measurement error", "trust in science", "preregistration"]
VERBS = ["examine", "model", "trace", "measure", "question", "compare", "simulate", "reconstruct"]


def abstract(rng: random.Random, i: int) -> str:
    t1, t2 = rng.sample(TOPICS, 2)
    title = f"Fake abstract {i}: {t1.capitalize()} and {t2}"
    body = (
        f"We {rng.choice(VERBS)} how {t1} interacts with {t2} across {rng.randint(3, 40)} fields. "
        f"Using {rng.choice(['a simulation', 'a reanalysis', 'an argument from the philosophy of science', 'a survey of researchers', 'a large corpus'])}, "
        f"we find that {rng.choice(['errors propagate faster than corrections', 'the usual remedy does not generalise', 'the problem is structural rather than individual', 'a simple check removes most false positives'])}. "
        f"We discuss what this means for {rng.choice(['journals', 'funders', 'metascience', 'AI-assisted research'])}."
    )
    return f"{title}\n\n{body}"


def main(path: str) -> None:
    rng = random.Random(9)
    wb = Workbook()
    ws = wb.active
    ws.title = "Form1"
    ws.append(HEADERS)
    for i in range(1, 13):
        row = [i, "2026-10-01 10:00:00", "2026-10-01 10:20:00", f"person{i}@example.org", f"Person {i}",
               rng.choice(STAGES), rng.choice(JOBS), rng.choice(HISTORY), f"Title {i}",
               abstract(rng, i) if i != 7 else "", rng.choice(FORMATS)]
        ws.append(row)
    wb.save(path)
    print(f"Wrote {path} (12 rows, one with an empty abstract)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
