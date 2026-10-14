# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl>=3.1", "cryptography>=42"]
# ///
"""Build data/submissions.enc.json from the Microsoft Forms Excel export.

  uv run tools/build_data.py path/to/export.xlsx --list-columns   # see the headers
  uv run tools/build_data.py path/to/export.xlsx                  # build

Which columns are shown, and under which label, is set in tools/columns.json.
The output is encrypted; each code in tools/codes.json can open it. Names,
e-mail addresses and every column not listed in columns.json are left out.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
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


def read_sheet(path: str, sheet: str | None):
    # Normal (not read-only) mode: it scans the cells themselves instead of
    # trusting the workbook's declared dimensions, which online exports get wrong.
    wb = load_workbook(path, data_only=True)
    ws = pick_sheet(wb, sheet)
    rows = ws.iter_rows(values_only=True)
    headers = [("" if h is None else str(h).strip()) for h in next(rows, ())]
    data = []
    for r in rows:
        if r is None or all(v is None or str(v).strip() == "" for v in r):
            continue
        r = list(r) + [None] * (len(headers) - len(r))
        data.append(r)
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx")
    ap.add_argument("--sheet", help="worksheet name (default: first sheet)")
    ap.add_argument("--list-columns", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "submissions.enc.json"))
    ap.add_argument("--columns", default=str(HERE / "columns.json"))
    ap.add_argument("--codes", default=str(HERE / "codes.json"))
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

    subs, skipped = [], 0
    for r in rows:
        rid = clean(r[id_col])
        if not rid:
            skipped += 1
            continue
        try:
            label = cols.get("id_format", "{}").format(int(float(rid)))
        except ValueError:
            label = rid
        rec = {"id": label}
        for f, ci in field_cols:
            rec[f["key"]] = clean(r[ci])
        if any(not rec[k] for k in required):
            skipped += 1
            continue
        subs.append(rec)
    subs.sort(key=lambda s: s["id"])

    payload = {
        "fields": [{"key": f["key"], "label": f["label"], "long": bool(f.get("long"))} for f in cols["fields"]],
        "submissions": subs,
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
