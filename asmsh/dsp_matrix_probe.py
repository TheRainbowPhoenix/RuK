from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from asmsh.probe import ASMSH, parse_listing


ROOT = Path(__file__).resolve().parent
ADDR_REGS = ["R4", "R5", "R2", "R3"]
DATA_REGS = ["A1", "A0", "Y0", "Y1", "M0", "M1", "X0", "A1G", "X1", "A0G"]


@dataclass
class MatrixResult:
    text: str
    returncode: int
    words: list[str]
    diagnostics: list[dict[str, str]]


def movs_cases() -> list[str]:
    cases: list[str] = []
    for ar in ADDR_REGS:
        for dr in DATA_REGS:
            cases.extend(
                [
                    f"MOVS.W @{ar}, {dr}",
                    f"MOVS.W {dr}, @{ar}",
                    f"MOVS.L @{ar}, {dr}",
                    f"MOVS.L {dr}, @{ar}",
                    f"MOVS.W @{ar}+, {dr}",
                    f"MOVS.W {dr}, @{ar}+",
                    f"MOVS.L @{ar}+, {dr}",
                    f"MOVS.L {dr}, @{ar}+",
                    f"MOVS.W @-{ar}, {dr}",
                    f"MOVS.W {dr}, @-{ar}",
                    f"MOVS.L @-{ar}, {dr}",
                    f"MOVS.L {dr}, @-{ar}",
                ]
            )
    return cases


def dsp_op_cases() -> list[str]:
    regs = ["X0", "X1", "Y0", "Y1", "A0", "A1", "M0", "M1"]
    dests = ["X0", "Y0", "A0", "A1", "M0", "M1"]
    cases: list[str] = []
    for a in regs:
        for b in regs:
            for d in dests:
                for op in ["PADD", "PSUB", "PMULS"]:
                    cases.append(f"{op} {a}, {b}, {d}")
            for op in ["PCMP", "PDEC", "PABS", "PCOPY"]:
                cases.append(f"{op} {a}, {b}")
    for d in dests:
        cases.extend([f"PSTS MACH, {d}", f"PSTS MACL, {d}", f"DCT PCOPY Y0, {d}", f"DCF PCOPY X0, {d}"])
    cases.extend(
        [
            "PSUB A1, Y1, Y0 PMULS X1, Y0, M0",
            "PADD A1, M0, Y0 PMULS X1, Y0, M0",
            "PADD A0, M0, A0 PMULS A1, X0, A1",
            "DCT PCOPY Y0, A1 MOVX.W @R5, Y0 NOPY",
        ]
    )
    return cases


def source_for(text: str) -> str:
    return "\n".join(
        [
            "\t.CPU SH4ALDSP",
            "\t.SECTION P,CODE",
            "_start:",
            f"\t{text}",
            "\tnop",
            "\t.END",
            "",
        ]
    )


def run_case(text: str, stem: str) -> MatrixResult:
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
    return MatrixResult(text, proc.returncode, words, diagnostics)


def main() -> int:
    out_dir = ROOT / "probe_out_dsp_matrix"
    out_dir.mkdir(exist_ok=True)
    cases = movs_cases() + dsp_op_cases()
    results = [run_case(text, f"dspm_{i:04d}") for i, text in enumerate(cases)]
    accepted = [r for r in results if not r.diagnostics]
    (out_dir / "results.json").write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")
    (out_dir / "accepted.json").write_text(json.dumps([asdict(r) for r in accepted], indent=2) + "\n")
    print(f"cases={len(results)} accepted={len(accepted)} rejected={len(results)-len(accepted)}")
    for r in accepted[:80]:
        print(f"OK {r.text}: {r.words}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
