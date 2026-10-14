# /// script
# requires-python = ">=3.10"
# ///
"""Create the reviewer codes and the matching sync tokens.

  uv run tools/make_codes.py --names "Anna,Ben,Cleo,Dev,Emi,Finn"        # first time, one code per name
  uv run tools/make_codes.py --add 1 --names "Gus"                          # one more reviewer later
  uv run tools/make_codes.py --show                                         # print them again

Writes tools/codes.json, which is git-ignored and must stay private: each code
decrypts the submissions file. After any change, rebuild the data file
(./update.sh <export.xlsx>) so the new codes can open it, and paste the printed
TOKENS block into backend/Code.gs and redeploy the web app.

--force replaces every code, so all reviewers would need new ones; --add keeps
the existing codes and appends new reviewers after the highest number.
"""
import argparse
import hashlib
import json
import secrets
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no i, l, o, 0, 1
TOKEN_PREFIX = "pse9-sync:"  # same string as in app.js


def new_code(i: int) -> str:
    groups = ["".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3)]
    return f"pse9-r{i}-" + "-".join(groups)


def token(code: str) -> str:
    return hashlib.sha256((TOKEN_PREFIX + code).encode()).hexdigest()


def entry(i: int, name: str) -> dict:
    c = new_code(i)
    return {"name": name, "code": c, "token": token(c)}


def show(codes: dict) -> None:
    print("Reviewer codes (send each one privately, with the site URL):")
    for rid, info in codes.items():
        print(f"  {rid}  {info.get('name', ''):<20} {info['code']}")
    print("\nPaste this block into backend/Code.gs (then redeploy the web app):")
    print("const TOKENS = {")
    for rid, info in codes.items():
        print(f"  {rid}: '{info['token']}',")
    print("};")
    print("\nThen rebuild the data file so every code can open it:  ./update.sh <export.xlsx>")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--names", default="", help="comma-separated reviewer names, in order")
    ap.add_argument("--n", type=int, default=0, help="number of reviewers to create (default: one per name, or 5)")
    ap.add_argument("--add", type=int, default=0, help="append this many reviewers, keeping existing codes")
    ap.add_argument("--show", action="store_true", help="print the existing codes and tokens")
    ap.add_argument("--force", action="store_true", help="replace all existing codes")
    a = ap.parse_args()
    path = HERE / "codes.json"
    names = [n.strip() for n in a.names.split(",")] if a.names else []

    if a.show:
        if not path.exists():
            raise SystemExit("No tools/codes.json yet. Run without --show first.")
        show(json.loads(path.read_text()))
        return

    if a.add:
        if not path.exists():
            raise SystemExit("No tools/codes.json yet. Create the first codes without --add.")
        codes = json.loads(path.read_text())
        numbers = [int(k[1:]) for k in codes if k.startswith("R") and k[1:].isdigit()]
        start = (max(numbers) if numbers else 0) + 1
        for j, i in enumerate(range(start, start + a.add)):
            codes[f"R{i}"] = entry(i, names[j] if j < len(names) else "")
        path.write_text(json.dumps(codes, indent=2) + "\n")
        print(f"Added {a.add} reviewer(s) to {path}.\n")
        show(codes)
        return

    if path.exists() and not a.force:
        raise SystemExit("tools/codes.json exists. Use --show to print it, --add to append a reviewer, or --force to replace all codes.")
    n = a.n or (len(names) if names else 5)
    codes = {f"R{i}": entry(i, names[i - 1] if i - 1 < len(names) else "") for i in range(1, n + 1)}
    path.write_text(json.dumps(codes, indent=2) + "\n")
    print(f"Wrote {path} (git-ignored).\n")
    show(codes)


if __name__ == "__main__":
    main()
