from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from .assembler import MiniAsmError, assemble, cpu_from_source, normalize_cpu
from .renesas_obj import write_renesas_object, words_to_bytes


@dataclass
class AsmshArgs:
    source: Path | None
    cpu: str | None
    listing: Path | None
    object_path: Path | None
    nologo: bool
    flat_object: bool


def parse_asmsh_args(argv: list[str]) -> AsmshArgs:
    source: Path | None = None
    cpu: str | None = None
    listing: Path | None = None
    object_path: Path | None = None
    nologo = False
    flat_object = False
    for arg in argv:
        if arg.startswith("-") or arg.startswith("/"):
            opt = arg[1:]
            name, sep, value = opt.partition("=")
            lname = name.lower()
            if lname == "cpu" and sep:
                cpu = normalize_cpu(value)
            elif lname == "list" and sep:
                listing = Path(value)
            elif lname == "object" and sep:
                object_path = Path(value)
            elif lname == "nologo":
                nologo = True
            elif lname in {"flat", "flatobject", "raw"}:
                flat_object = True
            else:
                raise MiniAsmError(f"unsupported option {arg}")
        else:
            source = Path(arg)
    return AsmshArgs(source, cpu, listing, object_path, nologo, flat_object)


def format_listing(source: Path, words: list[str], diagnostics: list[str]) -> str:
    lines = [
        "ASMSH-PY LISTING",
        "",
    ]
    for word_index, word in enumerate(words):
        lines.append(f"{word_index + 1:5d} {word_index * 2:08X} {word} {word_index + 1:5d} .word 0x{word}")
    lines.extend(diagnostics)
    return "\n".join(lines) + "\n"


def write_object_words(path: Path, words: list[str]) -> None:
    path.write_bytes(words_to_bytes(words))


def run(argv: list[str]) -> int:
    args = parse_asmsh_args(argv)
    if args.source is None:
        raise MiniAsmError("missing source file")
    lines = args.source.read_text(errors="replace").splitlines()
    cpu = args.cpu or cpu_from_source(lines) or "SH1"
    diagnostics: list[str] = []
    words: list[str] = []
    result = None
    return_code = 0
    try:
        result = assemble(lines, cpu, resolve_symbols=args.flat_object)
        words = result.words
    except MiniAsmError as exc:
        diagnostics.append(f"{args.source}(1) : 300 (E) {exc}")
        return_code = 2
    if args.listing:
        args.listing.write_text(format_listing(args.source, words, diagnostics))
    if args.object_path and return_code == 0:
        if args.flat_object:
            write_object_words(args.object_path, words)
        else:
            write_renesas_object(
                args.object_path,
                words,
                source_name=args.source.name,
                symbols=result.labels if result else {},
                exports=result.exports if result else set(),
                relocations=result.relocations if result else [],
            )
    if not args.nologo:
        print("ASMSH-PY SuperH assembler clone")
    print(f"  *****TOTAL ERRORS       {1 if return_code else 0}")
    print("  *****TOTAL WARNINGS     0")
    return return_code


def main() -> int:
    try:
        return run(sys.argv[1:])
    except MiniAsmError as exc:
        print(f"asmsh-py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
