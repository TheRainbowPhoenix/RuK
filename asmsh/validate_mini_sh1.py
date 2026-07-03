from __future__ import annotations

import argparse
import json
from pathlib import Path

from asmsh.assembler import compare_listing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-dir", type=Path, default=Path("probe_out"))
    parser.add_argument("--results", type=Path, default=Path("probe_out/results.json"))
    args = parser.parse_args()
    data = json.loads(args.results.read_text())
    failures = []
    checked = 0
    for row in data:
        if row["cpu"] != "SH1":
            continue
        checked += 1
        result = compare_listing(args.probe_dir / f"{row['name']}.src", args.probe_dir / f"{row['name']}.lis")
        if not result["ok"]:
            failures.append(result)
    print(f"checked={checked} failures={len(failures)}")
    for failure in failures[:20]:
        print(json.dumps(failure, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
