from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    in_path = ROOT / "probe_out_tables" / "instruction_table_sh4.json"
    out_csv = ROOT / "probe_out_tables" / "opcode_key_map_sh4.csv"
    out_json = ROOT / "probe_out_tables" / "opcode_key_map_sh4.json"
    data = json.loads(in_path.read_text())
    rows = [
        {
            "index": row["index"],
            "raw_key": row.get("raw_key", ""),
            "mnemonic": row["mnemonic"],
            "suffix": row["suffix"],
            "operand": row["operand"],
            "encoder": row["enc"],
            "cpu_mask": f"0x{row['cpu_mask']:08X}",
            "secondary_mask": f"0x{row['secondary_mask']:08X}",
        }
        for row in data["rows"]
    ]
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    out_json.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"wrote {len(rows)} rows to {out_csv} and {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
