# /// script
# requires-python = ">=3.10"
# ///
"""Create the reviewer codes and the matching sync tokens.

  uv run tools/make_codes.py --names "Anna,Ben,Cleo,Dev,Emi"   # first time
  uv run tools/make_codes.py --show                            # print them again

Writes tools/codes.json, which is git-ignored and must stay private: each code
decrypts the submissions file. Re-running with --force replaces every code, so
reviewers would need new ones and data/submissions.enc.json must be rebuilt.
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


def show(codes: dict) -> None:
    print("Reviewer codes (send each one privately, with the site URL):")
    for rid, info in codes.items():
        print(f"  {rid}  {info.get('name', ''):<20} {info['code']}")
    print("\nPaste this block into backend/Code.gs:")
    print("const TOKENS = {")
    for rid, info in codes.items():
        print(f"  {rid}: '{info['token']}',")
    print("};")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--names", default="", help="comma-separated reviewer names, in order R1..Rn")
    ap.add_argument("--n", type=int, default=5, help="number of reviewers (default 5)")
    ap.add_argument("--show", action="store_true", help="print the existing codes and tokens")
    ap.add_argument("--force", action="store_true", help="replace existing codes")
    a = ap.parse_args()
    path = HERE / "codes.json"
    if a.show:
        if not path.exists():
            raise SystemExit("No tools/codes.json yet. Run without --show first.")
        show(json.loads(path.read_text()))
        return
    if path.exists() and not a.force:
        raise SystemExit("tools/codes.json exists. Use --show to print it, or --force to replace all codes.")
    names = [n.strip() for n in a.names.split(",")] if a.names else []
    codes = {}
    for i in range(1, a.n + 1):
        c = new_code(i)
        codes[f"R{i}"] = {"name": names[i - 1] if i - 1 < len(names) else "", "code": c, "token": token(c)}
    path.write_text(json.dumps(codes, indent=2) + "\n")
    print(f"Wrote {path} (git-ignored).\n")
    show(codes)


if __name__ == "__main__":
    main()
