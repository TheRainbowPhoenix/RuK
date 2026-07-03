from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from asmsh.assembler import assemble_words
from asmsh.probe import ASMSH, parse_listing
from asmsh.rawbin import resolve_local_words, words_to_raw
from asmsh.renesas_obj import read_renesas_object


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "samples" / "sh4_raw_triangle.src"


@dataclass
class BuildResult:
    reference_returncode: int
    python_returncode: int
    reference_words: list[str]
    python_words: list[str]
    reference_raw_words: list[str]
    python_raw_words: list[str]
    reference_bin: Path
    python_bin: Path

    @property
    def same_object_words(self) -> bool:
        return self.reference_words == self.python_words

    @property
    def same_raw_words(self) -> bool:
        return self.reference_raw_words == self.python_raw_words


def object_words(path: Path) -> list[str]:
    return read_renesas_object(path).words("P")


def run_reference(source: Path, cpu: str, stem: str) -> tuple[int, list[str]]:
    listing = ROOT / f"{stem}_ref.lis"
    obj = ROOT / f"{stem}_ref.obj"
    cmd = [
        str(ASMSH),
        "-Nologo",
        f"-CPU={cpu}",
        f"-List={listing.name}",
        f"-Object={obj.name}",
        str(source.relative_to(ROOT)),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    words, diagnostics = parse_listing(listing)
    errors = [d for d in diagnostics if d.get("sev") == "E"]
    if errors:
        details = "; ".join(f"{d['line']}:{d['code']} {d['msg']}" for d in errors)
        raise RuntimeError(f"reference asmsh produced errors: {details}")
    return proc.returncode, object_words(obj)


def run_python(source: Path, cpu: str, stem: str) -> tuple[int, list[str], list[str]]:
    listing = ROOT / f"{stem}_py.lis"
    obj = ROOT / f"{stem}_py.obj"
    flat = ROOT / f"{stem}_py_flat.bin"
    cmd = [
        sys.executable,
        "-m",
        "asmsh",
        "-Nologo",
        f"-CPU={cpu}",
        f"-List={listing}",
        f"-Object={obj}",
        str(source.relative_to(ROOT)),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    words, diagnostics = parse_listing(listing)
    errors = [d for d in diagnostics if d.get("sev") == "E"]
    if errors:
        details = "; ".join(f"{d['line']}:{d['code']} {d['msg']}" for d in errors)
        raise RuntimeError(f"python asmsh produced errors: {details}")
    flat_cmd = [
        sys.executable,
        "-m",
        "asmsh",
        "-Nologo",
        f"-CPU={cpu}",
        "-Flat",
        f"-Object={flat}",
        str(source.relative_to(ROOT)),
    ]
    flat_proc = subprocess.run(flat_cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if flat_proc.returncode != 0:
        raise RuntimeError(flat_proc.stdout)
    raw_words = [flat.read_bytes()[i : i + 2].hex().upper() for i in range(0, flat.stat().st_size, 2)]
    return proc.returncode, object_words(obj), raw_words


def build(source: Path, cpu: str = "SH4", stem: str = "raw_triangle") -> BuildResult:
    source_lines = source.read_text().splitlines()
    ref_code, ref_words = run_reference(source, cpu, stem)
    py_code, py_words, py_flat_words = run_python(source, cpu, stem)
    ref_raw_words = resolve_local_words(source_lines, ref_words, cpu)
    py_raw_words = assemble_words(source_lines, cpu, resolve_symbols=True)
    if py_raw_words != py_flat_words:
        raise RuntimeError("python -Flat output differs from direct resolved assembly")
    ref_bin = ROOT / f"{stem}_ref.bin"
    py_bin = ROOT / f"{stem}_py.bin"
    ref_bin.write_bytes(words_to_raw(ref_raw_words))
    py_bin.write_bytes(words_to_raw(py_raw_words))
    return BuildResult(
        reference_returncode=ref_code,
        python_returncode=py_code,
        reference_words=ref_words,
        python_words=py_words,
        reference_raw_words=ref_raw_words,
        python_raw_words=py_raw_words,
        reference_bin=ref_bin,
        python_bin=py_bin,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--cpu", default="SH4")
    parser.add_argument("--stem", default="raw_triangle")
    args = parser.parse_args()
    result = build(args.source.resolve(), args.cpu, args.stem)
    print(f"reference rc={result.reference_returncode} words={len(result.reference_words)}")
    print(f"python    rc={result.python_returncode} words={len(result.python_words)}")
    print(f"object/listing parity={result.same_object_words}")
    print(f"raw parity={result.same_raw_words}")
    print(f"reference raw={result.reference_bin} bytes={result.reference_bin.stat().st_size}")
    print(f"python raw={result.python_bin} bytes={result.python_bin.stat().st_size}")
    return 0 if result.same_object_words and result.same_raw_words else 1


if __name__ == "__main__":
    raise SystemExit(main())
