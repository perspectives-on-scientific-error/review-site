# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl>=3.1", "cryptography>=42"]
# ///
"""Build data/submissions.enc.json from the Microsoft Forms Excel export (.xlsx or .csv).

  uv run tools/build_data.py path/to/export.xlsx --list-columns   # see the headers
  uv run tools/build_data.py path/to/export.xlsx                  # build

Which columns are shown, and under which label, is set in tools/columns.json.
The output is encrypted; each code in tools/codes.json can open it. Names,
e-mail addresses and every column not listed in columns.json are left out.

Each reviewer gets their own order (see reviewer_orders). The build reads who
has scored what from the score sheet (syncUrl in config.js), so rebuilding
also re-balances the remaining work.
"""
import argparse
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import os
import random
import re
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ITERATIONS = 300_000


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def pick_sheet(wb, sheet: str | None):
    """The named sheet, or the sheet with the most rows (Forms exports sometimes carry extra sheets)."""
    if sheet:
        return wb[sheet]
    return max(wb.worksheets, key=lambda ws: ws.max_row)


def read_csv(path: str):
    """A CSV saved from Excel: UTF-8 if saved as "CSV UTF-8", otherwise Windows-1252."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
        print("Note: CSV is not UTF-8 (read as Windows-1252). Excel has already replaced characters such as "
              "−, ő or ć with '?'; export as .xlsx or \"CSV UTF-8\" to keep them.")
    rows = csv.reader(io.StringIO(text, newline=""))
    headers = [h.strip() for h in next(rows, [])]
    data = []  # (excel_row_number, values); the header is row 1, as when the file is opened in Excel
    for n, r in enumerate(rows, start=2):
        if all(v.strip() == "" for v in r):
            continue
        r = r + [""] * (len(headers) - len(r))
        data.append((n, r))
    name = Path(path).stem
    return headers, data, name, [(name, len(data) + 1, len(headers))]


def read_sheet(path: str, sheet: str | None):
    if path.lower().endswith(".csv"):
        return read_csv(path)
    # Normal (not read-only) mode: it scans the cells themselves instead of
    # trusting the workbook's declared dimensions, which online exports get wrong.
    wb = load_workbook(path, data_only=True)
    ws = pick_sheet(wb, sheet)
    rows = ws.iter_rows(values_only=True)
    headers = [("" if h is None else str(h).strip()) for h in next(rows, ())]
    data = []  # (excel_row_number, values); the header is row 1
    for n, r in enumerate(rows, start=2):
        if r is None or all(v is None or str(v).strip() == "" for v in r):
            continue
        r = list(r) + [None] * (len(headers) - len(r))
        data.append((n, r))
    return headers, data, ws.title, [(w.title, w.max_row, w.max_column) for w in wb.worksheets]


def find_col(headers: list[str], match: str) -> int:
    low = [h.lower() for h in headers]
    m = match.lower()
    exact = [i for i, h in enumerate(low) if h == m]
    if len(exact) == 1:
        return exact[0]
    part = [i for i, h in enumerate(low) if m in h]
    if len(part) == 1:
        return part[0]
    if not part:
        raise SystemExit(f'No column matches "{match}". Run with --list-columns and edit tools/columns.json.')
    names = "; ".join(headers[i] for i in part)
    raise SystemExit(f'"{match}" matches several columns ({names}). Make it more specific in tools/columns.json.')


def clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def fetch_progress(codes: dict) -> dict[str, dict[str, bool]] | None:
    """{reviewer: {submission: counts}} for every completed review in the score sheet.
    counts is False for co-authors, who mark the submission done without scoring it.
    None if there is no sheet or it cannot be reached."""
    m = re.search(r"syncUrl:\s*['\"]([^'\"]+)['\"]", (ROOT / "config.js").read_text())
    if not m:
        return None
    done = {}
    try:
        for rid, info in sorted(codes.items()):
            q = urllib.parse.urlencode({"reviewer": rid, "token": info["token"]})
            with urllib.request.urlopen(f"{m.group(1)}?{q}", timeout=60) as res:
                j = json.load(res)
            if not j.get("ok"):
                raise RuntimeError(f"{rid}: {j.get('error')}")
            done[rid] = {str(r["submission"]): r.get("coi") != "coauthor"
                         for r in j.get("records", []) if str(r.get("complete")).lower() == "true"}
    except Exception as e:  # noqa: BLE001 - any failure means: order without progress
        print(f"Warning: could not read the score sheet ({e}); ordering as if nothing were scored yet.")
        return None
    return done


def reviewer_orders(ids: list[str], pinned: list[str], reviewers: list[str], done: dict,
                    inactive: set[str] = frozenset()) -> tuple[dict, list[int]]:
    """One order per reviewer: the pinned submissions, then what they have already scored,
    then the rest. The rest is dealt in turns: each reviewer takes the submission with the
    fewest reviews so far (ties in their own fixed random order), so if everyone works at a
    similar pace every submission gets a 1st review, then a 2nd, before any gets a 3rd.
    Inactive reviewers are left out of the dealing; their lists start with the submissions
    that have the fewest reviews now. Also returns, for k = 1, 2, 3, how many more scores per
    active reviewer (besides the pinned ones) give every submission k reviews."""
    rest = [i for i in ids if i not in pinned]
    count = Counter(s for d in done.values() for s, counts in d.items() if counts)
    now = Counter(count)
    rank = {r: {s: n for n, s in enumerate(random.Random(f"pse9:{r}").sample(rest, len(rest)))} for r in reviewers}
    todo = {r: set(rest) - set(done.get(r, {})) for r in reviewers}
    active = [r for r in reviewers if r not in inactive]
    picks = {r: [] for r in reviewers}
    reached = []
    while True:
        while len(reached) < 3 and rest and min(count[s] for s in rest) > len(reached):
            reached.append(max(len(picks[r]) for r in active))
        if not any(todo[r] for r in active):
            break
        for r in active:
            if todo[r]:
                s = min(todo[r], key=lambda s: (count[s], rank[r][s]))
                todo[r].remove(s)
                picks[r].append(s)
                count[s] += 1
    for r in inactive:
        picks[r] = sorted(todo[r], key=lambda s: (now[s], rank[r][s]))
    orders = {r: pinned + [s for s in rest if s in done.get(r, {})] + picks[r] for r in reviewers}
    return orders, reached


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx")
    ap.add_argument("--sheet", help="worksheet name (default: first sheet)")
    ap.add_argument("--list-columns", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "submissions.enc.json"))
    ap.add_argument("--columns", default=str(HERE / "columns.json"))
    ap.add_argument("--codes", default=str(HERE / "codes.json"))
    ap.add_argument("--inactive", default="", help="reviewers who have stopped, e.g. R5,R6: the others' "
                    "orders are balanced without them")
    a = ap.parse_args()

    headers, rows, used, sheets = read_sheet(a.xlsx, a.sheet)
    if a.list_columns:
        print("Sheets (name, rows, columns):", ", ".join(f"{n} {r}x{c}" for n, r, c in sheets))
        print(f"Reading sheet: {used}\n")
        for i, h in enumerate(headers):
            print(f"{i:3d}  {h}")
        print(f"\n{len(rows)} data rows")
        return

    cols = json.loads(Path(a.columns).read_text())
    codes_path = Path(a.codes)
    if not codes_path.exists():
        raise SystemExit("tools/codes.json not found. Run: uv run tools/make_codes.py --names \"...\"")
    codes = json.loads(codes_path.read_text())

    id_col = find_col(headers, cols["id"])
    field_cols = [(f, find_col(headers, f["match"])) for f in cols["fields"]]
    print(f"Sheet {used!r}: {len(rows)} rows. Columns used (edit tools/columns.json if wrong):")
    print(f'  id            <- "{headers[id_col]}"')
    for f, ci in field_cols:
        print(f'  {f["key"]:<13} <- "{headers[ci]}"')
    required = [f["key"] for f in cols["fields"] if f.get("required")]
    # "exclude": Forms IDs never shown to reviewers (e.g. test responses).
    excluded = {str(x) for x in cols.get("exclude", [])}

    subs, skipped = [], 0
    for excel_row, r in rows:
        rid = clean(r[id_col])
        if not rid or rid in excluded:
            skipped += 1
            continue
        try:
            label = cols.get("id_format", "{}").format(int(float(rid)))
        except ValueError:
            label = rid
        rec = {"id": label, "_row": excel_row}
        for f, ci in field_cols:
            rec[f["key"]] = clean(r[ci])
        if any(not rec[k] for k in required):
            skipped += 1
            continue
        subs.append(rec)
    subs.sort(key=lambda s: s["id"])

    # "show_first": Excel row numbers from the export whose submissions every
    # reviewer sees first, in the given order (e.g. a calibration abstract).
    first = []
    for want in cols.get("show_first", []):
        hit = next((s for s in subs if s["_row"] == int(want)), None)
        if hit is None:
            raise SystemExit(f"show_first: no submission in Excel row {want}.")
        print(f'Shown first: Excel row {want} -> {hit["id"]}')
        first.append(hit)
    subs = first + [s for s in subs if s not in first]
    for s in subs:
        del s["_row"]

    done = fetch_progress(codes) or {}
    if done:
        print("Already scored (complete):", ", ".join(f"{r} {len(d)}" for r, d in sorted(done.items())))
    inactive = {r.strip().upper() for r in a.inactive.split(",") if r.strip()}
    if inactive - set(codes):
        raise SystemExit(f"--inactive: unknown reviewer(s) {', '.join(sorted(inactive - set(codes)))}.")
    orders, reached = reviewer_orders([s["id"] for s in subs], [s["id"] for s in first], sorted(codes), done, inactive)
    who = "each reviewer" if not inactive else f"each reviewer except {', '.join(sorted(inactive))}"
    for k, n in enumerate(reached, start=1):
        print(f"Every submission has {k} review{'s' if k > 1 else ''} once {who} scores {n} more (besides the pinned one).")

    payload = {
        "fields": [{"key": f["key"], "label": f["label"], "long": bool(f.get("long"))} for f in cols["fields"]],
        "submissions": subs,
        "order": orders,
    }
    plain = json.dumps(payload, ensure_ascii=False).encode()
    data_key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    ciphertext = AESGCM(data_key).encrypt(iv, plain, None)

    keys = []
    for rid, info in sorted(codes.items()):
        salt = os.urandom(16)
        kek = hashlib.pbkdf2_hmac("sha256", info["code"].encode(), salt, ITERATIONS, 32)
        wiv = os.urandom(12)
        wrapped = AESGCM(kek).encrypt(wiv, data_key, None)
        keys.append({"reviewer": rid, "salt": b64(salt), "iv": b64(wiv), "wrapped": b64(wrapped)})

    pkg = {
        "version": 1,
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "count": len(subs),
        "kdf": {"name": "PBKDF2", "hash": "SHA-256", "iterations": ITERATIONS},
        "keys": keys,
        "iv": b64(iv),
        "ciphertext": b64(ciphertext),
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pkg, indent=1) + "\n")
    print(f"Wrote {out.relative_to(ROOT)}: {len(subs)} submissions, {skipped} rows skipped, {len(keys)} reviewer keys.")


if __name__ == "__main__":
    main()
