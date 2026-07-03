from __future__ import annotations

from pathlib import Path

from asmsh.assembler import compare_listing


ROOT = Path(__file__).resolve().parent


def main() -> int:
    result = compare_listing(ROOT / "all_sh4_nonfpu.src", ROOT / "all_sh4_nonfpu.lis", "SH4")
    failures = 0 if result["ok"] else 1
    print(f"checked={len(result['expected'])} failures={failures}")
    if failures:
        print(f"expected={result['expected']}")
        print(f"actual={result['actual']}")
        print(f"diagnostics={result['diagnostics']}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
