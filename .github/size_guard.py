"""Fail if a tracked file is over 1 MB (unless allowlisted) or the tree exceeds TREE_BUDGET_MB."""
import fnmatch, os, subprocess, sys
from pathlib import Path

LIMIT = 1_000_000
budget = float(os.environ.get("TREE_BUDGET_MB", "30")) * 1_000_000
allow = []
f = Path(__file__).with_name("size-allowlist.txt")
if f.exists():
    allow = [l.strip() for l in f.read_text().splitlines() if l.strip() and not l.startswith("#")]
files = subprocess.check_output(["git", "ls-files", "-z"], text=True).split("\0")
total, bad = 0, []
for name in filter(None, files):
    p = Path(name)
    if not p.is_file():
        continue
    n = p.stat().st_size
    total += n
    if n > LIMIT and not any(fnmatch.fnmatch(name, g) for g in allow):
        bad.append((name, n))
for name, n in bad:
    print(f"too large: {name} ({n} bytes)")
if total > budget:
    bad.append(("tree", total))
    print(f"tree is {total} bytes; budget {int(budget)}")
print(f"tracked bytes: {total}")
sys.exit(1 if bad else 0)
