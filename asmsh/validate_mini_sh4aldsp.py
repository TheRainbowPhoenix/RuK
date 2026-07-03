from __future__ import annotations

import json
from pathlib import Path

from asmsh.assembler import MiniAsmError, assemble_words


ROOT = Path(__file__).resolve().parent


def main() -> int:
    results = json.loads((ROOT / "probe_out_sh4aldsp" / "results.json").read_text())
    failures: list[str] = []
    checked = 0
    skipped = 0
    for item in results:
        if item["diagnostics"]:
            skipped += 1
            continue
        checked += 1
        try:
            actual = assemble_words(item["source"], "SH4ALDSP")
        except MiniAsmError as exc:
            failures.append(f"{item['name']}: raised {exc}")
            continue
        if actual != item["words"]:
            failures.append(f"{item['name']}: expected {item['words']} actual {actual}")
    print(f"checked={checked} failures={len(failures)} skipped={skipped}")
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
