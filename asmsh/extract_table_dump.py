from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TABLE_RE = re.compile(r"\[table-json:(?P<tag>[^\]]+)\]\s+(?P<json>\{.*\})")


def extract(path: Path, tag: str = "finish") -> dict:
    found: dict[str, dict] = {}
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be"):
        text = raw.decode(encoding, errors="ignore")
        if "[table-json:" in text:
            break
    else:
        text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        match = TABLE_RE.search(line)
        if not match:
            continue
        found[match.group("tag")] = json.loads(match.group("json"))
    if tag not in found:
        raise SystemExit(f"tag {tag!r} not found in {path}")
    return found[tag]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--tag", default="finish")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    data = extract(args.log, args.tag)
    text = json.dumps(data, indent=2)
    if args.out:
      args.out.write_text(text + "\n")
    else:
      print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
