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
    symbols = obj.symbols()
    if symbols:
        print("symbols:")
        for i, symbol in enumerate(symbols):
            print(
                f"  {i}: {symbol.name or '<null>'} value=0x{symbol.value:X} "
                f"info=0x{symbol.info:X} shndx=0x{symbol.shndx:X}"
            )
    relocs = obj.relocations(args.section)
    if relocs:
        print(f".rela{args.section}:")
        for reloc in relocs:
            print(
                f"  off=0x{reloc.offset:X} sym={reloc.symbol}({reloc.symbol_index}) "
                f"type=0x{reloc.reloc_type:X} addend={reloc.addend}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
