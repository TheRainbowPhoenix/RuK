from __future__ import annotations

import json
from pathlib import Path

from asmsh.assembler import MiniAsmError, assemble_words


ROOT = Path(__file__).resolve().parent


def source_for(text: str) -> list[str]:
    return [
        "\t.CPU SH4ALDSP",
        "\t.SECTION P,CODE",
        "_start:",
        f"\t{text}",
        "\tnop",
        "\t.END",
    ]


def main() -> int:
    accepted = json.loads((ROOT / "probe_out_dsp_matrix" / "accepted.json").read_text())
    failures: list[str] = []
    for item in accepted:
        expected = item["words"]
        try:
            actual = assemble_words(source_for(item["text"]), "SH4ALDSP")
        except MiniAsmError as exc:
            failures.append(f"{item['text']}: raised {exc}")
            continue
        if actual != expected:
            failures.append(f"{item['text']}: expected {expected} actual {actual}")
    print(f"checked={len(accepted)} failures={len(failures)}")
    for failure in failures[:50]:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
