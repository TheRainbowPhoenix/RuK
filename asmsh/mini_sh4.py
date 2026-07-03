from __future__ import annotations

import argparse
import json
from pathlib import Path

from asmsh.assembler import assemble_words, compare_listing


def main() -> int:
    parser = argparse.ArgumentParser(description="SH4 non-FPU mini assembler wrapper")
    parser.add_argument("source", type=Path)
    parser.add_argument("--listing", type=Path)
    parser.add_argument("--bin", type=Path, help="write raw big-endian instruction bytes")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.listing:
        result = compare_listing(args.source, args.listing, "SH4")
        if args.bin:
            args.bin.write_bytes(b"".join(int(word, 16).to_bytes(2, "big") for word in result["actual"]))
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"ok={result['ok']} expected={result['expected']} actual={result['actual']}")
        return 0 if result["ok"] else 1

    words = assemble_words(args.source.read_text().splitlines(), "SH4")
    if args.bin:
        args.bin.write_bytes(b"".join(int(word, 16).to_bytes(2, "big") for word in words))
    print(" ".join(words))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
