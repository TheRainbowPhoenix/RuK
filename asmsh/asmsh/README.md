# asmsh Python clone

This package is the centralized Python porting workspace for the legacy Renesas/Hitachi `asmsh.exe` behavior.

## Entry Point

Run it like the original assembler for the supported subset:

```powershell
python -m asmsh -Nologo -CPU=SH4 -List=out.lis -Object=out.obj samples/sh4_touch_poll.src
```

Supported options today:

- `-Nologo`
- `-CPU=<profile>`
- `-List=<path>`
- `-Object=<path>`
- `-Flat` / `-Raw` / `-FlatObject`
- source file path

`-Object` writes a minimal SuperH ELF32 big-endian relocatable object.  Use `-Flat -Object=<path>` to write the divergent flat big-endian instruction/data word stream.

## Source Layout

- `asmsh/assembler.py`: parser, CPU profiles, encoders, and listing comparison helpers.
- `asmsh/dsp_generated.py`: generated SH4AL-DSP DSP operation table from confirmed `asmsh.exe` probes.
- `asmsh/__main__.py`: `asmsh.exe`-style command-line entry point.
- `asmsh/probe.py`: reference `asmsh.exe` runner and listing parser.
- `asmsh/rawbin.py`: local-label resolver for turning listing/object words into standalone raw streams.
- `asmsh/renesas_obj.py`: small SuperH ELF relocatable object reader/writer.
- `build_raw_draw.py`: builds the screen-draw raw binary fixture with both assemblers.
- `dsp_matrix_probe.py`: probes SH4AL-DSP DSP forms against `asmsh.exe`.
- `validate_dsp_matrix.py`: validates every accepted DSP matrix form against the Python assembler.
- `samples/`: SH4 and SH4AL-DSP comparison fixtures.

## Validation

Run package syntax checks:

```powershell
python -m py_compile asmsh\__init__.py asmsh\__main__.py asmsh\assembler.py asmsh\probe.py
```

Compare Python against the real executable on representative SH4/SH4AL-DSP programs:

```powershell
python compare_reference.py
```

Current expected output:

```text
sh4_nonfpu: success=True words=True obj=True ref=0/155 py=0/155
sh4_touch_poll: success=True words=True obj=True ref=0/69 py=0/69
sh4_triangle: success=True words=True obj=True ref=0/95 py=0/95
sh4_fibonacci: success=True words=True obj=True ref=0/14 py=0/14
sh4_gcd: success=True words=True obj=True ref=0/14 py=0/14
sh4_checksum: success=True words=True obj=True ref=0/15 py=0/15
sh4_memcopy: success=True words=True obj=True ref=0/16 py=0/16
sh4aldsp_probe: success=True words=True obj=True ref=0/29 py=0/29
sh4aldsp_dsp_confirmed: success=True words=True obj=True ref=0/37 py=0/37
dsp_sigmadelta2_raw_negative: success=True words=True obj=True ref=4/0 py=2/0
```

The DSP sketch is intentionally a negative parity fixture.  The reference assembler rejects the raw GNU/macro/parallel-DSP sketch, and the Python clone rejects it too.  The next reverse-engineering target is the full SH4AL-DSP parallel/DSP-CO grammar, after which this fixture can become a positive test.

Run focused validators:

```powershell
python validate_mini_sh1.py
python validate_mini_sh4.py
python validate_mini_sh4aldsp.py
python validate_dsp_matrix.py
```

Build the standalone raw screen-draw fixture:

```powershell
python build_raw_draw.py
```

This assembles `samples/sh4_raw_triangle.src` with both the original `asmsh.exe` and `python -m asmsh`, checks the relocatable word stream, resolves local PC-relative literal loads, and writes:

- `raw_triangle_ref.bin`
- `raw_triangle_py.bin`

Both are flat big-endian SH word streams intended to be loaded at `0x80000000`.  The first two listing words are relocatable placeholders (`DE00 DD00`); the raw postprocess patches them to concrete local displacements (`DE0D DD0E`) for the 4-byte-aligned in-file literal pool.

## Current Scope

The Python clone matches the reference instruction-word stream and `P` section object words for the extracted SH1 set, the SH4 non-FPU set, and the confirmed SH4AL-DSP integer/cache/system/DSP subset.

`validate_dsp_matrix.py` currently checks 1,068 accepted SH4AL-DSP DSP forms generated from the SH73050 references and confirmed through `asmsh.exe`: formulaic `MOVS.W/.L` forms across accepted address/data registers plus 588 generated DSP operation/parallel spellings.  The raw SigmaDelta sketch remains a negative parity fixture because its macro/numeric-label source form is not accepted by the legacy assembler as written.
