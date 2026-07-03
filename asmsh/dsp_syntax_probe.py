from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from asmsh.probe import ASMSH, parse_listing


ROOT = Path(__file__).resolve().parent


@dataclass
class DspProbe:
    text: str
    returncode: int
    words: list[str]
    diagnostics: list[dict[str, str]]


CASES = [
    "MOVS.L @R4+, A1",
    "MOVS.L @R4+,A1",
    "MOVS.W @R5+, X0",
    "MOVS.W @R5, X1",
    "MOVS.L A1, @R4+",
    "MOVS.W A1, @R4",
    "MOVX.W @R5, Y0 NOPY",
    "MOVX.W @R5,Y0,NOPY",
    "MOVY.W @R5, X0 NOPX",
    "LDS R6, Y1",
    "LDS R6,A0",
    "LDRS dsp_l1",
    "LDRE dsp_l2",
    "LDRC #32",
    "1: PSUB Y0, A1, Y0",
    "PSUB A1, Y1, Y0",
    "PMULS X1, Y0, M0",
    "PADD A1, M0, Y0",
    "PDEC A1, Y1",
    "PABS X0, X0",
    "PCMP X0, Y1",
    "PCOPY Y0, A1",
    "DCT PCOPY Y0, A1",
    "DCF PCOPY X0, A1",
    "PSTS MACH, A1",
    "PSUB A1, Y1, Y0 PMULS X1, Y0, M0",
    "DCT PCOPY Y0, A1 MOVX.W @R5, Y0 NOPY",
]


def source_for(text: str) -> str:
    lines = [
        "\t.CPU SH4ALDSP",
        "\t.SECTION P,CODE",
        "_start:",
        f"\t{text}",
        "dsp_l1:",
        "\tnop",
        "dsp_l2:",
        "\tnop",
        "\t.END",
        "",
    ]
    return "\n".join(lines)


def run_probe(text: str, index: int, out_dir: Path) -> DspProbe:
    stem = f"dsp_{index:03d}"
    src = ROOT / f"{stem}.src"
    lis = ROOT / f"{stem}.lis"
    obj = ROOT / f"{stem}.obj"
    src.write_text(source_for(text))
    proc = subprocess.run(
        [str(ASMSH), "-Nologo", "-CPU=SH4ALDSP", f"-List={lis.name}", f"-Object={obj.name}", src.name],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    words, diagnostics = parse_listing(lis)
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{stem}.stdout.txt").write_text(proc.stdout)
    return DspProbe(text, proc.returncode, words, diagnostics)


def main() -> int:
    out_dir = ROOT / "probe_out_dsp"
    results = [run_probe(text, i, out_dir) for i, text in enumerate(CASES)]
    (out_dir / "results.json").write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")
    for r in results:
        state = "OK" if not r.diagnostics else "NO"
        print(f"{state} {r.text}: rc={r.returncode} words={r.words} diag={r.diagnostics[:1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
