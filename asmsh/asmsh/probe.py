from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ASMSH = Path(r"C:\Path\to\asmsh.exe")


LISTING_WORD_RE = re.compile(
    r"^\s*(?P<seq>\d+)\s+"
    r"(?:(?P<addr>[0-9A-F]{8})\s+)?"
    r"(?:(?P<word>[0-9A-F]{4}|[0-9A-F]{8})\s+)?"
    r"(?P<srcseq>\d+)\s+(?P<src>.*)$"
)
DIAG_RE = re.compile(r"^(?P<file>.+?)\((?P<line>\d+)\)\s+:\s+(?P<code>\d+)\s+\((?P<sev>[EWF])\)\s+(?P<msg>.*)$")


@dataclass
class ProbeResult:
    name: str
    cpu: str
    source: list[str]
    returncode: int
    words: list[str]
    diagnostics: list[dict[str, str]]
    listing_path: str
    object_path: str


def make_source(cpu: str, body: list[str]) -> list[str]:
    return [
        f"\t.CPU {cpu}",
        "\t.SECTION P,CODE",
        "\t.EXPORT _start",
        "_start:",
        *[f"\t{line}" if line and not line.endswith(":") else line for line in body],
        "\t.END",
    ]


def parse_listing(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    words: list[str] = []
    diagnostics: list[dict[str, str]] = []
    if not path.exists():
        return words, diagnostics
    for line in path.read_text(errors="replace").splitlines():
        diag = DIAG_RE.match(line)
        if diag:
            diagnostics.append(diag.groupdict())
            continue
        match = LISTING_WORD_RE.match(line)
        if match and match.group("word"):
            word = match.group("word").upper()
            if len(word) == 8:
                words.extend([word[:4], word[4:]])
            else:
                words.append(word)
    return words, diagnostics


def run_probe(name: str, cpu: str, body: list[str], out_dir: Path) -> ProbeResult:
    src = out_dir / f"{name}.src"
    lis = out_dir / f"{name}.lis"
    obj = out_dir / f"{name}.obj"
    source = make_source(cpu, body)
    src.write_text("\n".join(source) + "\n")
    cmd = [
        str(ASMSH),
        "-Nologo",
        f"-CPU={cpu}",
        f"-List={lis}",
        f"-Object={obj}",
        str(src),
    ]
    proc = subprocess.run(cmd, cwd=out_dir, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    words, diagnostics = parse_listing(lis)
    return ProbeResult(
        name=name,
        cpu=cpu,
        source=source,
        returncode=proc.returncode,
        words=words,
        diagnostics=diagnostics,
        listing_path=str(lis),
        object_path=str(obj),
    )


def default_cases() -> list[tuple[str, str, list[str]]]:
    cases: list[tuple[str, str, list[str]]] = []
    for n in range(16):
        cases.append((f"mov_imm_r{n}", "SH1", [f"MOV #{n},R{n}"]))
        cases.append((f"add_imm_r{n}", "SH1", [f"ADD #{n},R{n}"]))
    for m in range(4):
        for n in range(4):
            cases.append((f"mov_r{m}_r{n}", "SH1", [f"MOV R{m},R{n}"]))
            cases.append((f"add_r{m}_r{n}", "SH1", [f"ADD R{m},R{n}"]))
    cases.extend(
        [
            ("nop", "SH1", ["NOP"]),
            ("rts_nop", "SH1", ["RTS", "NOP"]),
            ("bra_zero", "SH1", ["BRA done", "NOP", "done:", "RTS", "NOP"]),
            ("bra_forward_2", "SH1", ["BRA done", "NOP", "NOP", "done:", "RTS", "NOP"]),
            ("mov_imm_neg1", "SH1", ["MOV #-1,R0"]),
            ("add_imm_neg1", "SH1", ["ADD #-1,R0"]),
            ("sh4aldsp_nop", "SH4ALDSP", ["NOP", "RTS", "NOP"]),
        ]
    )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "probe_out")
    parser.add_argument("--json", type=Path, default=ROOT / "probe_out" / "results.json")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    results = [run_probe(name, cpu, body, args.out) for name, cpu, body in default_cases()]
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps([asdict(r) for r in results], indent=2))

    failed = [r for r in results if r.diagnostics]
    print(f"probes={len(results)} diagnostics={len(failed)} json={args.json}")
    for r in failed[:20]:
        print(f"{r.name}: {r.diagnostics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
