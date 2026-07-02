# SectorC-SH4: A C Compiler for SH-4

A port of [SectorC](https://github.com/xorvoid/sectorc) — the world's
smallest C compiler — targeting the SuperH SH-4 architecture.

## What it does

SectorC-SH4 compiles a small subset of C into SH-4 machine code that
runs on the RuK emulator (or real SH-4 hardware).  The compiler itself
is written in Python, making it easy to understand and extend.

## Supported C subset

```
program     = (var_decl | func_decl)+
var_decl    = "int" identifier ";"
func_decl   = "void" func_name "{" statement* "}"
statement   = "if(" expr "){" statement* "}"
            | "while(" expr "){" statement* "}"
            | func_name ";"
            | assign_expr ";"
assign_expr = deref? identifier "=" expr
deref       = "*(int*)"
expr        = unary (op unary)?
unary       = deref identifier
            | "&" identifier
            | "(" expr ")"
            | identifier
            | integer
op          = "+" | "-" | "*" | "&" | "|" | "^" | "<<" | ">>"
            | "==" | "!=" | "<" | ">" | "<=" | ">="
```

Comments: `// line` and `/* block */` are supported.

## SH-4 code generation

The compiler uses a simple stack-machine model:
- `r0` = accumulator (holds expression results)
- `r1` = secondary register (right operand)
- `r14` = frame pointer / variable base
- `r15` = stack pointer (for push/pop)

Variables are stored in a global data area starting at a fixed address.
Functions are called via `BSR` / `RTS`.  Control flow uses `BT`/`BF`.

## Usage

```python
from sectorc import SectorC

compiler = SectorC()
assembly = compiler.compile(source_code)
# 'assembly' is SH-4 assembly text that can be assembled with
# ruk.tools.assembler.assemble()
```

## Running in the emulator

```python
from ruk.tools.assembler import assemble
from ruk.classpad import Classpad

binary = assemble(assembly, start_addr=0x8C000000)
cp.ram.write_bin(0, binary)
cp.cpu.pc = 0x8C000000
# Run...
```

## Files

- `sectorc.py` — The Python-based C-to-SH4 compiler
- `test_sectorc.py` — Tests: compile, assemble, run, verify output
- `examples/` — Example C programs (hello, triangle, sine wave)
