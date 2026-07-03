from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from asmsh.probe import run_probe


ROOT = Path(__file__).resolve().parent


def main() -> int:
    out_dir = ROOT / "probe_out_trace"
    out_dir.mkdir(exist_ok=True)
    bodies = []
    candidates = [
        "TRACE",
        "TRACE #0",
        "TRACE #1",
        "TRACE #15",
        "TRACE R0",
        "TRACE @R0",
        "TRACE @R0+",
        "TRACE R0,R1",
        "TRACE #0,R0",
        "TRACE @R0,R1",
    ]
    for text in candidates:
        bodies.append((text.lower().replace(" ", "_").replace("#", "imm").replace("@", "at").replace(",", "_"), [text]))
    results = [run_probe(name, "SH4", body, out_dir) for name, body in bodies]
    (out_dir / "results.json").write_text(json.dumps([asdict(r) for r in results], indent=2))
    for r in results:
        state = "OK" if not r.diagnostics else "NO"
        print(f"{state} {r.source[-2].strip()}: words={r.words} diagnostics={r.diagnostics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
