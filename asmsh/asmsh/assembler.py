from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .dsp_generated import DSP_OPERATION_WORDS
from .probe import parse_listing


REG_RE = r"R(?:1[0-5]|[0-9])"
DSP_ADDR_CODES = {"R4": 4, "R5": 5, "R2": 6, "R3": 7}
DSP_DATA_CODES = {"A1": 5, "A0": 7, "Y0": 10, "Y1": 11, "M0": 12, "M1": 14, "X0": 8, "A1G": 13, "X1": 9, "A0G": 15}


@dataclass
class ParsedLine:
    source: str
    label: str | None
    op: str | None
    args: list[str]
    address: int | None = None


def strip_comment(raw: str) -> str:
    line = raw
    for marker in (";", "!"):
        if marker in line:
            line = line.split(marker, 1)[0]
    return line.strip()


class MiniAsmError(ValueError):
    pass


@dataclass(frozen=True)
class CpuProfile:
    name: str
    asmsh_id: int
    asmsh_mask: int
    base: str | None = None


CPU_PROFILES = {
    "SH1": CpuProfile("SH1", 1, 0x0001),
    "SH2": CpuProfile("SH2", 2, 0x0002, "SH1"),
    "SH3": CpuProfile("SH3", 3, 0x0004, "SH2"),
    "SHDSP": CpuProfile("SHDSP", 4, 0x0008, "SH2"),
    "SH4": CpuProfile("SH4", 6, 0x0020, "SH3"),
    "SH2E": CpuProfile("SH2E", 7, 0x0040, "SH2"),
    "SH3DSP": CpuProfile("SH3DSP", 8, 0x0080, "SH3"),
    "SH2AFPU": CpuProfile("SH2AFPU", 10, 0x0200, "SH2A"),
    "SH4ALDSP": CpuProfile("SH4ALDSP", 11, 0x0400, "SH4AL"),
    "SH4A": CpuProfile("SH4A", 12, 0x0800, "SH4"),
    "SH4AL": CpuProfile("SH4AL", 13, 0x1000, "SH4A"),
    "SH2A": CpuProfile("SH2A", 14, 0x2000, "SH2"),
}


CPU_ALIASES = {
    "7000": "SH1",
    "7600": "SH2",
    "SH3E": "SH3",
}


def normalize_cpu(cpu: str) -> str:
    key = cpu.strip().upper()
    key = CPU_ALIASES.get(key, key)
    if key not in CPU_PROFILES:
        raise MiniAsmError(f"unsupported CPU profile {cpu!r}")
    return key


def cpu_from_source(lines: list[str]) -> str | None:
    for raw in lines:
        line = strip_comment(raw)
        if not line:
            continue
        parts = line.split(None, 1)
        if parts and parts[0].upper() == ".CPU" and len(parts) > 1:
            return normalize_cpu(parts[1])
    return None


def cpu_inherits(cpu: str, ancestor: str) -> bool:
    current: str | None = normalize_cpu(cpu)
    ancestor = normalize_cpu(ancestor)
    while current:
        if current == ancestor:
            return True
        current = CPU_PROFILES[current].base
    return False


def parse_int(text: str) -> int:
    text = text.strip()
    sign = -1 if text.startswith("-") else 1
    if text[0:1] in "+-":
        text = text[1:]
    if text.lower().startswith("0x"):
        value = int(text, 16)
    elif text.upper().startswith("H'"):
        value = int(text[2:], 16)
    elif text.endswith(("H", "h")):
        value = int(text[:-1], 16)
    else:
        value = int(text, 10)
    return sign * value


def parse_reg(text: str) -> int:
    text = text.strip().upper()
    if not re.fullmatch(REG_RE, text):
        raise MiniAsmError(f"invalid register {text!r}")
    return int(text[1:])


def parse_ctrl(text: str) -> str:
    text = text.strip().upper()
    if text not in {"SR", "GBR", "VBR", "MACH", "MACL", "PR"}:
        raise MiniAsmError(f"invalid control register {text!r}")
    return text


def parse_dsp_imm(text: str) -> int:
    text = text.strip()
    if not text.startswith("#"):
        raise MiniAsmError(f"invalid DSP immediate {text!r}")
    value = parse_int(text[1:])
    if value < 0 or value > 255:
        raise MiniAsmError(f"DSP immediate out of range {text!r}")
    return value


def normalized_statement(raw: str) -> str:
    return re.sub(r"\s+", " ", strip_comment(raw).upper()).replace(" ,", ",").replace(", ", ",").strip()


def split_args(rest: str) -> list[str]:
    args: list[str] = []
    start = 0
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch == "," and depth == 0:
            part = rest[start:i].strip()
            if part:
                args.append(part)
            start = i + 1
    tail = rest[start:].strip()
    if tail:
        args.append(tail)
    return args


def parse_source(lines: list[str]) -> list[ParsedLine]:
    parsed: list[ParsedLine] = []
    for raw in lines:
        line = strip_comment(raw)
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("/"):
            continue
        label = None
        if ":" in line:
            left, right = line.split(":", 1)
            if left.strip():
                label = left.strip()
            line = right.strip()
        if not line:
            parsed.append(ParsedLine(raw, label, None, []))
            continue
        parts = line.split(None, 1)
        op = parts[0].upper()
        rest = parts[1] if len(parts) > 1 else ""
        parsed.append(ParsedLine(raw, label, op, split_args(rest)))
    return parsed


def is_emitting(line: ParsedLine) -> bool:
    if not line.op:
        return False
    if line.op in {".WORD", ".DATA.W"}:
        return True
    if line.op in {".LONG", ".DATA.L"}:
        return True
    if line.op.startswith("."):
        return False
    return True


def emitted_size(line: ParsedLine, pc: int) -> int:
    if not line.op:
        return 0
    if line.op in {".WORD", ".DATA.W"}:
        return 2 * max(1, len(line.args))
    if line.op in {".LONG", ".DATA.L"}:
        return 4 * max(1, len(line.args))
    if line.op == ".ALIGN" and line.args:
        boundary = parse_int(line.args[0])
        return (-pc) % boundary
    if line.op in {"PSUB", "PMULS", "PADD", "PDEC", "PABS", "PCMP", "PCOPY", "DCT", "DCF", "PSTS"}:
        return 4
    return 2 if is_emitting(line) else 0


def first_pass(lines: list[ParsedLine]) -> dict[str, int]:
    pc = 0
    labels: dict[str, int] = {}
    for line in lines:
        if line.label:
            labels[line.label] = pc
        size = emitted_size(line, pc)
        if size:
            line.address = pc
            pc += size
    return labels


def imm8(text: str) -> int:
    return parse_int(text) & 0xFF


def parse_indirect_reg(text: str) -> int | None:
    m = re.fullmatch(r"@(" + REG_RE + r")", text.strip().upper())
    return parse_reg(m.group(1)) if m else None


def parse_postinc(text: str) -> int | None:
    m = re.fullmatch(r"@(" + REG_RE + r")\+", text.strip().upper())
    return parse_reg(m.group(1)) if m else None


def parse_predec(text: str) -> int | None:
    m = re.fullmatch(r"@-(" + REG_RE + r")", text.strip().upper())
    return parse_reg(m.group(1)) if m else None


def parse_disp_reg(text: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"@\(\s*([^,]+)\s*,\s*(" + REG_RE + r")\s*\)", text.strip().upper())
    if not m:
        return None
    return parse_int(m.group(1)), parse_reg(m.group(2))


def parse_disp_gbr(text: str) -> int | None:
    m = re.fullmatch(r"@\(\s*([^,]+)\s*,\s*GBR\s*\)", text.strip().upper())
    return parse_int(m.group(1)) if m else None


def parse_pc_disp(text: str, labels: dict[str, int], pc: int, scale: int, resolve_symbols: bool = False) -> int | None:
    m = re.fullmatch(r"@\(\s*([^,]+)\s*,\s*PC\s*\)", text.strip(), re.IGNORECASE)
    if not m:
        return None
    expr = m.group(1).strip()
    base = (pc + 4) & ~3 if scale == 4 else pc + 4
    if expr in labels:
        # asmsh emits a zero placeholder in the listing for symbolic PC-relative
        # operands; relocation/details live in the object stream.
        if not resolve_symbols:
            return 0
        return (labels[expr] - base) // scale
    return (parse_int(expr) - base) // scale


def parse_literal_disp(text: str, labels: dict[str, int], pc: int, scale: int, resolve_symbols: bool = False) -> int | None:
    disp = parse_pc_disp(text, labels, pc, scale, resolve_symbols)
    if disp is not None:
        return disp
    expr = text.strip()
    if re.fullmatch(REG_RE, expr.upper()):
        return None
    if expr.startswith("@"):
        return None
    if expr in labels:
        if resolve_symbols:
            base = (pc + 4) & ~3 if scale == 4 else pc + 4
            return (labels[expr] - base) // scale
        return 0
    try:
        return (parse_int(expr) - (pc + 4)) // scale
    except ValueError:
        return None


def word_for_dsp_movs(op: str, args: list[str]) -> int | None:
    if len(args) != 2:
        return None
    size_base = 0 if op == "MOVS.W" else 2
    src = args[0].strip().upper()
    dst = args[1].strip().upper()
    if dst in DSP_DATA_CODES:
        dcode = DSP_DATA_CODES[dst]
        if src.startswith("@-") and src[2:] in DSP_ADDR_CODES:
            return 0xF000 | (DSP_ADDR_CODES[src[2:]] << 8) | (dcode << 4) | size_base
        post = parse_postinc(src)
        if post is not None and f"R{post}" in DSP_ADDR_CODES:
            return 0xF000 | (DSP_ADDR_CODES[f"R{post}"] << 8) | (dcode << 4) | (8 + size_base)
        ind = parse_indirect_reg(src)
        if ind is not None and f"R{ind}" in DSP_ADDR_CODES:
            return 0xF000 | (DSP_ADDR_CODES[f"R{ind}"] << 8) | (dcode << 4) | (4 + size_base)
    if src in DSP_DATA_CODES:
        dcode = DSP_DATA_CODES[src]
        if dst.startswith("@-") and dst[2:] in DSP_ADDR_CODES:
            return 0xF000 | (DSP_ADDR_CODES[dst[2:]] << 8) | (dcode << 4) | (1 + size_base)
        post = parse_postinc(dst)
        if post is not None and f"R{post}" in DSP_ADDR_CODES:
            return 0xF000 | (DSP_ADDR_CODES[f"R{post}"] << 8) | (dcode << 4) | (9 + size_base)
        ind = parse_indirect_reg(dst)
        if ind is not None and f"R{ind}" in DSP_ADDR_CODES:
            return 0xF000 | (DSP_ADDR_CODES[f"R{ind}"] << 8) | (dcode << 4) | (5 + size_base)
    return None


def branch_disp(target: str, labels: dict[str, int], pc: int) -> int:
    if target not in labels:
        raise MiniAsmError(f"unknown label {target!r}")
    return (labels[target] - (pc + 4)) // 2


def word_for_sh2plus(line: ParsedLine) -> int | None:
    op = line.op
    args = line.args
    if not op:
        return None
    if len(args) == 1:
        if op == "DT":
            return 0x4010 | (parse_reg(args[0]) << 8)
        if op == "BRAF":
            return 0x0023 | (parse_reg(args[0]) << 8)
        if op == "BSRF":
            return 0x0003 | (parse_reg(args[0]) << 8)
        if op == "TRACE":
            return 0x0043 | (parse_reg(args[0]) << 8)
    if len(args) == 2:
        if op in {"DMULS.L", "DMULU.L"}:
            m = parse_reg(args[0])
            n = parse_reg(args[1])
            return {"DMULS.L": 0x300D, "DMULU.L": 0x3005}[op] | (n << 8) | (m << 4)
        if op == "MUL.L":
            m = parse_reg(args[0])
            n = parse_reg(args[1])
            return 0x0007 | (n << 8) | (m << 4)
    return None


def word_for_sh3plus(line: ParsedLine) -> int | None:
    op = line.op
    args = line.args
    if not op:
        return None
    if not args:
        fixed = {
            "CLRS": 0x0048,
            "SETS": 0x0058,
            "LDTLB": 0x0038,
        }
        if op in fixed:
            return fixed[op]
    if len(args) == 1:
        if op == "PREF":
            n = parse_indirect_reg(args[0])
            if n is not None:
                return 0x0083 | (n << 8)
    if len(args) == 2:
        if op in {"SHAD", "SHLD"}:
            m = parse_reg(args[0])
            n = parse_reg(args[1])
            return {"SHAD": 0x400C, "SHLD": 0x400D}[op] | (n << 8) | (m << 4)
    return None


def word_for_sh4plus(line: ParsedLine) -> int | None:
    op = line.op
    args = line.args
    if not op:
        return None
    if len(args) == 1 and op in {"OCBI", "OCBP", "OCBWB"}:
        n = parse_indirect_reg(args[0])
        if n is not None:
            return {"OCBI": 0x0093, "OCBP": 0x00A3, "OCBWB": 0x00B3}[op] | (n << 8)
    if len(args) == 2:
        if op == "MOVCA.L" and args[0].strip().upper() == "R0":
            n = parse_indirect_reg(args[1])
            if n is not None:
                return 0x00C3 | (n << 8)
    return None


def word_for_sh4aldsp(line: ParsedLine) -> int | None:
    op = line.op
    args = line.args
    if not op:
        return None
    stmt = normalized_statement(line.source)
    if stmt in DSP_OPERATION_WORDS and len(DSP_OPERATION_WORDS[stmt]) == 1:
        return int(DSP_OPERATION_WORDS[stmt][0], 16)
    if stmt == "MOVX.W @R5,Y0 NOPY":
        return 0xF244
    if not args:
        fixed = {
            "CLRDMXY": 0x0088,
            "SETDMX": 0x0098,
            "SETDMY": 0x00C8,
            "SYNCO": 0x00AB,
        }
        if op in fixed:
            return fixed[op]
    if len(args) == 1:
        if op in {"PREFI", "ICBI"}:
            n = parse_indirect_reg(args[0])
            if n is not None:
                return {"PREFI": 0x00D3, "ICBI": 0x00E3}[op] | (n << 8)
        if op == "SETRC":
            return 0x8200 | parse_dsp_imm(args[0])
        if op == "LDRC":
            return 0x8A00 | parse_dsp_imm(args[0])
        if op in {"LDRS", "LDRE"}:
            raise MiniAsmError(f"{op} must be label-relative")
    if len(args) == 2:
        if op == "LDS":
            m = parse_reg(args[0])
            target = args[1].strip().upper()
            if target in {"Y1", "A0"}:
                return {"Y1": 0x40BA, "A0": 0x407A}[target] | (m << 8)
        if op in {"MOVS.W", "MOVS.L"}:
            word = word_for_dsp_movs(op, args)
            if word is not None:
                return word
        if op == "MOVLI.L" and args[1].strip().upper() == "R0":
            n = parse_indirect_reg(args[0])
            if n is not None:
                return 0x0063 | (n << 8)
        if op == "MOVCO.L" and args[0].strip().upper() == "R0":
            n = parse_indirect_reg(args[1])
            if n is not None:
                return 0x0073 | (n << 8)
        if op == "MOVUA.L" and args[1].strip().upper() == "R0":
            m = parse_indirect_reg(args[0])
            if m is not None:
                return 0x40A9 | (m << 8)
    return None


def word_for(line: ParsedLine, labels: dict[str, int], cpu: str = "SH1", resolve_symbols: bool = False) -> int | None:
    op = line.op
    if not op or op.startswith("."):
        return None
    args = line.args
    pc = line.address if line.address is not None else 0
    if op in {".WORD", ".DATA.W"}:
        if len(args) != 1:
            raise MiniAsmError(f"unsupported multi-value directive: {line.source.strip()}")
        return parse_int(args[0]) & 0xFFFF
    if op in {".LONG", ".DATA.L"}:
        raise MiniAsmError(".LONG must be emitted through words_for")
    if op == ".ALIGN":
        return None
    if op == "NOP" and not args:
        return 0x0009
    if op == "RTS" and not args:
        return 0x000B
    if op == "RTE" and not args:
        return 0x002B
    if op == "CLRMAC" and not args:
        return 0x0028
    if op == "CLRT" and not args:
        return 0x0008
    if op == "SETT" and not args:
        return 0x0018
    if op == "DIV0U" and not args:
        return 0x0019
    if op == "SLEEP" and not args:
        return 0x001B
    if op in {"ADD", "ADDC", "ADDV", "SUB", "SUBC", "SUBV", "DIV0S", "DIV1", "CMP/EQ", "CMP/HS", "CMP/GE", "CMP/HI", "CMP/GT", "CMP/STR", "AND", "OR", "TST", "XOR", "XTRCT"} and len(args) == 2:
        if op == "ADD" and args[0].startswith("#"):
            return 0x7000 | (parse_reg(args[1]) << 8) | imm8(args[0][1:])
        if op in {"AND", "OR", "TST", "XOR", "CMP/EQ"} and args[0].startswith("#") and args[1].upper() == "R0":
            bases = {"ADD": 0x7000, "AND": 0xC900, "OR": 0xCB00, "TST": 0xC800, "XOR": 0xCA00, "CMP/EQ": 0x8800}
            return bases[op] | imm8(args[0][1:])
        m = parse_reg(args[0])
        n = parse_reg(args[1])
        bases = {
            "ADD": 0x300C,
            "ADDC": 0x300E,
            "ADDV": 0x300F,
            "SUB": 0x3008,
            "SUBC": 0x300A,
            "SUBV": 0x300B,
            "DIV0S": 0x2007,
            "DIV1": 0x3004,
            "CMP/EQ": 0x3000,
            "CMP/HS": 0x3002,
            "CMP/GE": 0x3003,
            "CMP/HI": 0x3006,
            "CMP/GT": 0x3007,
            "CMP/STR": 0x200C,
            "AND": 0x2009,
            "OR": 0x200B,
            "TST": 0x2008,
            "XOR": 0x200A,
            "XTRCT": 0x200D,
        }
        return bases[op] | (n << 8) | (m << 4)
    if op in {"CMP/PZ", "CMP/PL", "ROTCL", "ROTCR", "ROTL", "ROTR", "SHAL", "SHAR", "SHLL", "SHLL2", "SHLL8", "SHLL16", "SHLR", "SHLR2", "SHLR8", "SHLR16"} and len(args) == 1:
        n = parse_reg(args[0])
        bases = {
            "CMP/PZ": 0x4011,
            "CMP/PL": 0x4015,
            "ROTCL": 0x4024,
            "ROTCR": 0x4025,
            "ROTL": 0x4004,
            "ROTR": 0x4005,
            "SHAL": 0x4020,
            "SHAR": 0x4021,
            "SHLL": 0x4000,
            "SHLL2": 0x4008,
            "SHLL8": 0x4018,
            "SHLL16": 0x4028,
            "SHLR": 0x4001,
            "SHLR2": 0x4009,
            "SHLR8": 0x4019,
            "SHLR16": 0x4029,
        }
        return bases[op] | (n << 8)
    if op in {"EXTS.B", "EXTS.W", "EXTU.B", "EXTU.W", "MULS.W", "MULU.W", "NEG", "NEGC", "NOT", "SWAP.B", "SWAP.W"} and len(args) == 2:
        m = parse_reg(args[0])
        n = parse_reg(args[1])
        bases = {
            "EXTS.B": 0x600E,
            "EXTS.W": 0x600F,
            "EXTU.B": 0x600C,
            "EXTU.W": 0x600D,
            "MULS.W": 0x200F,
            "MULU.W": 0x200E,
            "NEG": 0x600B,
            "NEGC": 0x600A,
            "NOT": 0x6007,
            "SWAP.B": 0x6008,
            "SWAP.W": 0x6009,
        }
        return bases[op] | (n << 8) | (m << 4)
    if op == "MOV" and len(args) == 2:
        if args[0].startswith("#"):
            imm = parse_int(args[0][1:]) & 0xFF
            n = parse_reg(args[1])
            return 0xE000 | (n << 8) | imm
        m = parse_reg(args[0])
        n = parse_reg(args[1])
        return 0x6003 | (n << 8) | (m << 4)
    if op in {"MOV.B", "MOV.W", "MOV.L"} and len(args) == 2:
        size = op[-1]
        if args[0].upper() == "R0":
            d = parse_disp_gbr(args[1])
            if d is not None:
                div = {"B": 1, "W": 2, "L": 4}[size]
                base = {"B": 0xC000, "W": 0xC100, "L": 0xC200}[size]
                return base | (d // div)
        if args[1].upper() == "R0":
            d = parse_disp_gbr(args[0])
            if d is not None:
                div = {"B": 1, "W": 2, "L": 4}[size]
                base = {"B": 0xC400, "W": 0xC500, "L": 0xC600}[size]
                return base | (d // div)
        m = parse_reg(args[0]) if re.fullmatch(REG_RE, args[0].strip().upper()) else None
        n = parse_predec(args[1])
        if m is not None and n is not None:
            return {"B": 0x2004, "W": 0x2005, "L": 0x2006}[size] | (n << 8) | (m << 4)
        n = parse_reg(args[1]) if re.fullmatch(REG_RE, args[1].strip().upper()) else None
        m_post = parse_postinc(args[0])
        if n is not None and m_post is not None:
            return {"B": 0x6004, "W": 0x6005, "L": 0x6006}[size] | (n << 8) | (m_post << 4)
        m_ind = parse_indirect_reg(args[0])
        if n is not None and m_ind is not None:
            return {"B": 0x6000, "W": 0x6001, "L": 0x6002}[size] | (n << 8) | (m_ind << 4)
        n_ind = parse_indirect_reg(args[1])
        if m is not None and n_ind is not None:
            return {"B": 0x2000, "W": 0x2001, "L": 0x2002}[size] | (n_ind << 8) | (m << 4)
        if m == 0:
            dispn = parse_disp_reg(args[1])
            if dispn is not None and size in {"B", "W"}:
                d, nreg = dispn
                return {"B": 0x8000, "W": 0x8100}[size] | (nreg << 4) | (d // (1 if size == "B" else 2))
        if m is not None:
            dispn = parse_disp_reg(args[1])
            if dispn is not None and size == "L":
                d, nreg = dispn
                return 0x1000 | (nreg << 8) | (m << 4) | (d // 4)
        if n == 0:
            dispm = parse_disp_reg(args[0])
            if dispm is not None and size in {"B", "W"}:
                d, mreg = dispm
                return {"B": 0x8400, "W": 0x8500}[size] | (mreg << 4) | (d // (1 if size == "B" else 2))
        if n is not None:
            dispm = parse_disp_reg(args[0])
            if dispm is not None and size == "L":
                d, mreg = dispm
                return 0x5000 | (n << 8) | (mreg << 4) | (d // 4)
        if n is not None and size in {"W", "L"}:
            disp = parse_literal_disp(args[0], labels, pc, 2 if size == "W" else 4, resolve_symbols)
            if disp is not None:
                return {"W": 0x9000, "L": 0xD000}[size] | (n << 8) | (disp & 0xFF)
    if op == "ADD" and len(args) == 2:
        if args[0].startswith("#"):
            imm = parse_int(args[0][1:]) & 0xFF
            n = parse_reg(args[1])
            return 0x7000 | (n << 8) | imm
        m = parse_reg(args[0])
        n = parse_reg(args[1])
        return 0x300C | (n << 8) | (m << 4)
    if op in {"BF", "BT"} and len(args) == 1:
        disp = branch_disp(args[0], labels, pc)
        if disp < -128 or disp > 127:
            raise MiniAsmError(f"{op} displacement out of range")
        return {"BF": 0x8B00, "BT": 0x8900}[op] | (disp & 0xFF)
    if op in {"BRA", "BSR"} and len(args) == 1:
        disp = branch_disp(args[0], labels, pc)
        if disp < -2048 or disp > 2047:
            raise MiniAsmError(f"{op} displacement out of range")
        return {"BRA": 0xA000, "BSR": 0xB000}[op] | (disp & 0x0FFF)
    if op in {"AND.B", "OR.B", "TST.B", "XOR.B"} and len(args) == 2 and args[0].startswith("#") and args[1].upper() == "@(R0,GBR)":
        return {"AND.B": 0xCD00, "OR.B": 0xCF00, "TST.B": 0xCC00, "XOR.B": 0xCE00}[op] | imm8(args[0][1:])
    if op in {"JMP", "JSR"} and len(args) == 1:
        n = parse_indirect_reg(args[0])
        if n is not None:
            return {"JMP": 0x402B, "JSR": 0x400B}[op] | (n << 8)
    if cpu_inherits(cpu, "SH4ALDSP"):
        word = word_for_sh4aldsp(line)
        if word is not None:
            return word
    if op in {"LDC", "LDS", "STC", "STS"} and len(args) == 2:
        a0 = args[0].strip().upper()
        a1 = args[1].strip().upper()
        if op == "LDC":
            m = parse_reg(a0)
            return {"SR": 0x400E, "GBR": 0x401E, "VBR": 0x402E}[parse_ctrl(a1)] | (m << 8)
        if op == "LDS":
            m = parse_reg(a0)
            return {"MACH": 0x400A, "MACL": 0x401A, "PR": 0x402A}[parse_ctrl(a1)] | (m << 8)
        if op == "STC":
            n = parse_reg(a1)
            return {"SR": 0x0002, "GBR": 0x0012, "VBR": 0x0022}[parse_ctrl(a0)] | (n << 8)
        if op == "STS":
            n = parse_reg(a1)
            return {"MACH": 0x000A, "MACL": 0x001A, "PR": 0x002A}[parse_ctrl(a0)] | (n << 8)
    if op in {"LDC.L", "LDS.L"} and len(args) == 2:
        m = parse_postinc(args[0])
        if m is not None:
            if op == "LDC.L":
                return {"SR": 0x4007, "GBR": 0x4017, "VBR": 0x4027}[parse_ctrl(args[1])] | (m << 8)
            return {"MACH": 0x4006, "MACL": 0x4016, "PR": 0x4026}[parse_ctrl(args[1])] | (m << 8)
    if op in {"STC.L", "STS.L"} and len(args) == 2:
        n = parse_predec(args[1])
        if n is not None:
            if op == "STC.L":
                return {"SR": 0x4003, "GBR": 0x4013, "VBR": 0x4023}[parse_ctrl(args[0])] | (n << 8)
            return {"MACH": 0x4002, "MACL": 0x4012, "PR": 0x4022}[parse_ctrl(args[0])] | (n << 8)
    if op == "MAC.W" and len(args) == 2:
        m = parse_postinc(args[0])
        n = parse_postinc(args[1])
        if m is not None and n is not None:
            return 0x400F | (n << 8) | (m << 4)
    if op == "MOVA" and len(args) == 2 and args[1].upper() == "R0":
        disp = parse_pc_disp(args[0], labels, pc, 4, resolve_symbols)
        if disp is not None:
            return 0xC700 | (disp & 0xFF)
    if op == "MOVT" and len(args) == 1:
        return 0x0029 | (parse_reg(args[0]) << 8)
    if op == "TAS.B" and len(args) == 1:
        n = parse_indirect_reg(args[0])
        if n is not None:
            return 0x401B | (n << 8)
    if op == "TRAPA" and len(args) == 1 and args[0].startswith("#"):
        return 0xC300 | imm8(args[0][1:])
    if cpu_inherits(cpu, "SH2"):
        word = word_for_sh2plus(line)
        if word is not None:
            return word
    if cpu_inherits(cpu, "SH3"):
        word = word_for_sh3plus(line)
        if word is not None:
            return word
    if cpu_inherits(cpu, "SH4"):
        word = word_for_sh4plus(line)
        if word is not None:
            return word
    raise MiniAsmError(f"unsupported instruction: {line.source.strip()}")


def words_for_sh4aldsp(line: ParsedLine, labels: dict[str, int]) -> list[int] | None:
    stmt = normalized_statement(line.source)
    if stmt in DSP_OPERATION_WORDS:
        return [int(word, 16) for word in DSP_OPERATION_WORDS[stmt]]
    if line.op in {"LDRS", "LDRE"} and len(line.args) == 1:
        pc = line.address if line.address is not None else 0
        disp = branch_disp(line.args[0], labels, pc)
        return [{"LDRS": 0x8C00, "LDRE": 0x8E00}[line.op] | (disp & 0xFF)]
    return None


def words_for(line: ParsedLine, labels: dict[str, int], cpu: str, resolve_symbols: bool = False) -> list[int]:
    if cpu_inherits(cpu, "SH4ALDSP"):
        dsp_words = words_for_sh4aldsp(line, labels)
        if dsp_words is not None:
            return dsp_words
    if line.op in {".LONG", ".DATA.L"}:
        values = line.args or ["0"]
        words: list[int] = []
        for arg in values:
            value = parse_int(arg) & 0xFFFFFFFF
            words.extend([(value >> 16) & 0xFFFF, value & 0xFFFF])
        return words
    if line.op == ".ALIGN":
        pc = line.address or 0
        count = emitted_size(line, pc)
        return [0x0009] * (count // 2)
    word = word_for(line, labels, cpu, resolve_symbols)
    return [] if word is None else [word]


def assemble_words(lines: list[str], cpu: str | None = None, resolve_symbols: bool = False) -> list[str]:
    cpu = normalize_cpu(cpu or cpu_from_source(lines) or "SH1")
    parsed = parse_source(lines)
    labels = first_pass(parsed)
    words: list[str] = []
    for line in parsed:
        for word in words_for(line, labels, cpu, resolve_symbols):
            words.append(f"{word:04X}")
    return words


def compare_listing(source_path: Path, listing_path: Path, cpu: str | None = None) -> dict[str, object]:
    expected, diagnostics = parse_listing(listing_path)
    actual = assemble_words(source_path.read_text().splitlines(), cpu)
    return {
        "source": str(source_path),
        "listing": str(listing_path),
        "expected": expected,
        "actual": actual,
        "diagnostics": diagnostics,
        "ok": expected == actual and not diagnostics,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--cpu", help="override .CPU directive; default is source .CPU or SH1")
    parser.add_argument("--listing", type=Path)
    parser.add_argument("--bin", type=Path, help="write raw big-endian instruction bytes")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.listing:
        result = compare_listing(args.source, args.listing, args.cpu)
        if args.bin:
            args.bin.write_bytes(b"".join(int(word, 16).to_bytes(2, "big") for word in result["actual"]))
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"ok={result['ok']} expected={result['expected']} actual={result['actual']}")
        return 0 if result["ok"] else 1

    words = assemble_words(args.source.read_text().splitlines(), args.cpu, resolve_symbols=bool(args.bin))
    if args.bin:
        args.bin.write_bytes(b"".join(int(word, 16).to_bytes(2, "big") for word in words))
    print(" ".join(words))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
