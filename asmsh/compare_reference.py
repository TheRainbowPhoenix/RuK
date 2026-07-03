from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from asmsh.probe import ASMSH, parse_listing
from asmsh.renesas_obj import read_renesas_object


ROOT = Path(__file__).resolve().parent


@dataclass
class CompareCase:
    name: str
    cpu: str
    source: str
    stem: str


@dataclass
class CompareResult:
    name: str
    cpu: str
    source: str
    reference_returncode: int
    python_returncode: int
    reference_words: list[str]
    python_words: list[str]
    reference_object_words: list[str]
    python_object_words: list[str]
    reference_relocations: list[tuple[int, str, int, int]]
    python_relocations: list[tuple[int, str, int, int]]
    reference_diagnostics: list[dict[str, str]]
    python_diagnostics: list[dict[str, str]]
    same_success: bool
    same_words: bool
    same_object_words: bool
    same_relocations: bool


CASES = [
    CompareCase("sh4_nonfpu", "SH4", "all_sh4_nonfpu.src", "s4n"),
    CompareCase("sh4_touch_poll", "SH4", "samples/sh4_touch_poll.src", "s4t"),
    CompareCase("sh4_triangle", "SH4", "samples/sh4_triangle.src", "s4g"),
    CompareCase("sh4_fibonacci", "SH4", "samples/sh4_fibonacci.src", "fib"),
    CompareCase("sh4_gcd", "SH4", "samples/sh4_gcd.src", "gcd"),
    CompareCase("sh4_checksum", "SH4", "samples/sh4_checksum.src", "sum"),
    CompareCase("sh4_memcopy", "SH4", "samples/sh4_memcopy.src", "cpy"),
    CompareCase("sh4_reloc_probe", "SH4", "samples/sh4_reloc_probe.src", "relp"),
    CompareCase("sh4aldsp_probe", "SH4ALDSP", "samples/sh4aldsp_probe.src", "s4d"),
    CompareCase("sh4aldsp_dsp_confirmed", "SH4ALDSP", "samples/sh4aldsp_dsp_confirmed.src", "dspc"),
    CompareCase("dsp_sigmadelta2_raw_negative", "SH4ALDSP", "samples/dsp_sigmadelta2.raw.src", "dspn"),
]


def obj_words(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return read_renesas_object(path).words("P")
    except Exception:
        return []


def obj_relocations(path: Path) -> list[tuple[int, str, int, int]]:
    if not path.exists():
        return []
    try:
        return [
            (reloc.offset, reloc.symbol, reloc.reloc_type, reloc.addend)
            for reloc in read_renesas_object(path).relocations("P")
        ]
    except Exception:
        return []


def run_reference(case: CompareCase, out_dir: Path) -> tuple[int, list[str], list[dict[str, str]], list[str], list[tuple[int, str, int, int]]]:
    lis = ROOT / f"cmp_{case.stem}_r.lis"
    obj = ROOT / f"cmp_{case.stem}_r.obj"
    lis_arg = lis.name
    obj_arg = obj.name
    cmd = [
        str(ASMSH),
        "-Nologo",
        f"-CPU={case.cpu}",
        f"-List={lis_arg}",
        f"-Object={obj_arg}",
        case.source,
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    words, diagnostics = parse_listing(lis)
    return proc.returncode, words, diagnostics, obj_words(obj), obj_relocations(obj)


def run_python(case: CompareCase, out_dir: Path) -> tuple[int, list[str], list[dict[str, str]], list[str], list[tuple[int, str, int, int]]]:
    lis = ROOT / f"cmp_{case.stem}_p.lis"
    obj = ROOT / f"cmp_{case.stem}_p.obj"
    cmd = [
        sys.executable,
        "-m",
        "asmsh",
        "-Nologo",
        f"-CPU={case.cpu}",
        f"-List={lis}",
        f"-Object={obj}",
        case.source,
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    words, diagnostics = parse_listing(lis)
    return proc.returncode, words, diagnostics, obj_words(obj), obj_relocations(obj)


def run_case(case: CompareCase, out_dir: Path) -> CompareResult:
    ref_code, ref_words, ref_diag, ref_obj_words, ref_relocs = run_reference(case, out_dir)
    py_code, py_words, py_diag, py_obj_words, py_relocs = run_python(case, out_dir)
    return CompareResult(
        name=case.name,
        cpu=case.cpu,
        source=case.source,
        reference_returncode=ref_code,
        python_returncode=py_code,
        reference_words=ref_words,
        python_words=py_words,
        reference_object_words=ref_obj_words,
        python_object_words=py_obj_words,
        reference_relocations=ref_relocs,
        python_relocations=py_relocs,
        reference_diagnostics=ref_diag,
        python_diagnostics=py_diag,
        same_success=(ref_code == 0) == (py_code == 0),
        same_words=ref_words == py_words,
        same_object_words=ref_obj_words == py_obj_words,
        same_relocations=ref_relocs == py_relocs,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "compare_out")
    parser.add_argument("--json", type=Path, default=ROOT / "compare_out" / "results.json")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    results = [run_case(case, args.out) for case in CASES]
    args.json.write_text(json.dumps([asdict(result) for result in results], indent=2) + "\n")
    failures = [
        result
        for result in results
        if not (result.same_success and result.same_words and result.same_object_words and result.same_relocations)
    ]
    for result in results:
        print(
            f"{result.name}: success={result.same_success} words={result.same_words} "
            f"obj={result.same_object_words} relocs={result.same_relocations} "
            f"ref={result.reference_returncode}/{len(result.reference_words)} "
            f"py={result.python_returncode}/{len(result.python_words)}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
