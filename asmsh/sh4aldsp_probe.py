from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from asmsh.probe import run_probe


ROOT = Path(__file__).resolve().parent


def cases() -> list[tuple[str, list[str]]]:
    return [
        ("clrdmxy", ["CLRDMXY"]),
        ("clrs", ["CLRS"]),
        ("sets", ["SETS"]),
        ("setdmx", ["SETDMX"]),
        ("setdmy", ["SETDMY"]),
        ("ldtlb", ["LDTLB"]),
        ("synco", ["SYNCO"]),
        ("trace", ["TRACE"]),
        ("dt_r0", ["DT R0"]),
        ("braf_r0", ["BRAF R0"]),
        ("bsrf_r0", ["BSRF R0"]),
        ("shad_r1_r0", ["SHAD R1,R0"]),
        ("shld_r1_r0", ["SHLD R1,R0"]),
        ("dmuls_l", ["DMULS.L R1,R0"]),
        ("dmulu_l", ["DMULU.L R1,R0"]),
        ("mul_l", ["MUL.L R1,R0"]),
        ("pref_at_r0", ["PREF @R0"]),
        ("prefi_at_r0", ["PREFI @R0"]),
        ("icbi_at_r0", ["ICBI @R0"]),
        ("ocbi_at_r0", ["OCBI @R0"]),
        ("ocbp_at_r0", ["OCBP @R0"]),
        ("ocbwb_at_r0", ["OCBWB @R0"]),
        ("movca_l", ["MOVCA.L R0,@R1"]),
        ("movli_l", ["MOVLI.L @R1,R0"]),
        ("movco_l", ["MOVCO.L R0,@R1"]),
        ("movua_l_load", ["MOVUA.L @R1,R0"]),
        ("movua_l_disp", ["MOVUA.L @R0+,R1"]),
        ("setrc_imm", ["SETRC #4"]),
        ("ldrc_imm", ["LDRC #4"]),
        ("ldre_imm", ["LDRE #4"]),
        ("ldrs_imm", ["LDRS #4"]),
    ]


def main() -> int:
    out_dir = ROOT / "probe_out_sh4aldsp"
    out_dir.mkdir(exist_ok=True)
    results = [run_probe(name, "SH4ALDSP", body, out_dir) for name, body in cases()]
    (out_dir / "results.json").write_text(json.dumps([asdict(r) for r in results], indent=2))
    accepted = [r for r in results if not r.diagnostics]
    rejected = [r for r in results if r.diagnostics]
    print(f"cases={len(results)} accepted={len(accepted)} rejected={len(rejected)}")
    for r in accepted:
        print(f"OK {r.name}: {' '.join(r.words)}")
    for r in rejected:
        print(f"NO {r.name}: {r.diagnostics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
