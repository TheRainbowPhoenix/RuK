from __future__ import annotations

import argparse
from pathlib import Path

from asmsh.renesas_obj import read_renesas_object


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("object", type=Path)
    parser.add_argument("--section", default="P")
    args = parser.parse_args()
    obj = read_renesas_object(args.object)
    for section in obj.sections:
        print(f"{section.name or '<null>'}: type={section.sh_type} off=0x{section.offset:X} size=0x{section.size:X}")
    words = obj.words(args.section)
    if words:
        print(f"{args.section} words:", " ".join(words))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
