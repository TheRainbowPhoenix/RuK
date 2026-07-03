from __future__ import annotations

import subprocess
from pathlib import Path

from extract_table_dump import extract


ROOT = Path(__file__).resolve().parent
ASMSH = Path(r"C:\Path\to\asmsh.exe")
CPUS = ["SH1", "SH2", "SH3", "SHDSP", "SH4", "SH2E", "SH3DSP", "SH2AFPU", "SH4ALDSP", "SH4A", "SH4AL", "SH2A"]


def write_probe_source(path: Path, cpu: str) -> None:
    path.write_text("\n".join([
        f"\t.CPU {cpu}",
        "\t.SECTION P,CODE",
        "_start:",
        "\tNOP",
        "\t.END",
        "",
    ]))


def main() -> int:
    out_dir = ROOT / "probe_out_tables"
    out_dir.mkdir(exist_ok=True)
    for cpu in CPUS:
        src = out_dir / f"table_{cpu.lower()}.src"
        lis = out_dir / f"table_{cpu.lower()}.lis"
        obj = out_dir / f"table_{cpu.lower()}.obj"
        log = out_dir / f"dump_table_{cpu.lower()}.log"
        write_probe_source(src, cpu)
        cmd = [
            "frida",
            "--no-pause",
            "-f",
            str(ASMSH),
            "-l",
            str(ROOT / "dump_instruction_table.js"),
            "--",
            "-Nologo",
            f"-CPU={cpu}",
            f"-List={lis}",
            f"-Object={obj}",
            str(src),
        ]
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        log.write_text(proc.stdout + proc.stderr)
        try:
            table = extract(log)
        except SystemExit as exc:
            print(f"{cpu}: return={proc.returncode} no table ({exc})")
            continue
        (out_dir / f"instruction_table_{cpu.lower()}.json").write_text(__import__("json").dumps(table, indent=2) + "\n")
        print(f"{cpu}: return={proc.returncode} rows={table.get('count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
