"""
HH3 (Hollyhock-3) ELF loader for the RuK emulator.

An .hh3 file is a standard ELF32 big-endian SH executable that targets
the Casio Classpad II / fx-CG50 (SH7305).  It is produced by the
yhl/hollyhock-3 toolchain (see https://github.com/ClasspadDev/yal) and
loaded on real hardware by the `yal` launcher.

File format summary (verified against yal's ELFLoader source):

  - ELF32, big-endian (EI_DATA = ELFDATA2MSB)
  - e_machine = EM_SH (0x2A)
  - e_type = ET_EXEC (0x02) -- statically linked, fixed addresses
  - One or more PT_LOAD program headers
  - Each PT_LOAD is copied verbatim from p_offset to p_vaddr
    (p_filesz bytes from the file, then p_memsz - p_filesz zero-filled)
  - The entry point (e_entry) is called as:
        int entry(int argc, char **argv, char **envp)
    with argc=1, argv={"<filename>", NULL}, envp={"HHK_SYMBOL_TABLE=...",
    "HHK_SYMBOL_TABLE_LEN=...", NULL} (yal sets up the env vars).

Typical segment layout (from TestAzur.hh3):
  [0] vaddr=0x8C052800, filesz=0x83B0, memsz=0x83B0, flags=RWE -- code+data
  [1] vaddr=0xE5200000, filesz=0x50,   memsz=0x50,   flags=RX  -- ILRAM stub

The vaddrs fall inside memory regions already mapped by Classpad:
  - 0x8C000000 .. 0x8CFFFFFF : RAM (16MB) -- covers 0x8C052800
  - 0xE5200000 .. 0xE5200FFF : ILRAM (4KB) -- covers 0xE5200000

So we just need to copy segment bytes into the existing RAM/ILRAM
buffers; no new memory regions are needed.

Usage:
    from ruk.jcore.hh3 import load_hh3, run_hh3

    # Just load (segments written, CPU state not changed):
    entry = load_hh3(classpad, "TestAzur.hh3")
    # entry is the e_entry address

    # Load + set up CPU to run (entry -> PC, stack -> R15, args -> R4/R5/R6):
    entry = run_hh3(classpad, "TestAzur.hh3",
                    argv=["TestAzur.hh3"],
                    envp={"HHK_SYMBOL_TABLE": "0",
                          "HHK_SYMBOL_TABLE_LEN": "0"})
    classpad.cpu.run(max_steps=10_000_000)
"""

from typing import List, Dict, Optional, Tuple
import struct


# ---------------------------------------------------------------------------
# ELF constants (subset relevant to SH-4 hh3 files)
# ---------------------------------------------------------------------------

ELFMAG = b'\x7fELF'
SELFMAG = 4

EI_CLASS      = 4
EI_DATA       = 5
EI_VERSION    = 6

ELFCLASS32    = 1
ELFDATA2MSB   = 2
EV_CURRENT    = 1

ET_EXEC       = 2
EM_SH         = 0x2A    # Renesas / SuperH

PT_NULL       = 0
PT_LOAD       = 1
PT_NOTE       = 4
PT_PHDR       = 6

PF_X = 1; PF_W = 2; PF_R = 4


# ---------------------------------------------------------------------------
# ELF parsing
# ---------------------------------------------------------------------------

class HH3Error(Exception):
    """Raised when an .hh3 file cannot be loaded."""


def parse_elf(data: bytes) -> dict:
    """Parse an ELF32 BE SH executable's header + program headers.

    Returns a dict with:
      'e_entry'   : int  -- entry-point virtual address
      'e_phnum'   : int
      'e_phentsize': int
      'phdrs'     : list of dicts with keys
                      p_type, p_offset, p_vaddr, p_paddr,
                      p_filesz, p_memsz, p_flags, p_align
      'notes'     : list of dicts (from PT_NOTE segments) with keys
                      name, desc, type

    Raises HH3Error on any structural problem.
    """
    if len(data) < 52:
        raise HH3Error("File too small to be an ELF")

    if data[:SELFMAG] != ELFMAG:
        raise HH3Error("Not an ELF file (bad magic)")

    ei_class = data[EI_CLASS]
    if ei_class != ELFCLASS32:
        raise HH3Error(f"Only ELF32 supported (got EI_CLASS={ei_class})")

    ei_data = data[EI_DATA]
    if ei_data != ELFDATA2MSB:
        raise HH3Error(f"Only big-endian ELF supported (got EI_DATA={ei_data})")

    if data[EI_VERSION] != EV_CURRENT:
        raise HH3Error("Invalid ELF version")

    # ELF32 header (big-endian) -- bytes 16..51
    (e_type, e_machine, e_version, e_entry, e_phoff, e_shoff,
     e_flags, e_ehsize, e_phentsize, e_phnum,
     e_shentsize, e_shnum, e_shstrndx) = struct.unpack(
        '>HHIIIIIHHHHHH', data[16:52])

    if e_type != ET_EXEC:
        raise HH3Error(f"Only ET_EXEC supported (got e_type={e_type:#x})")

    if e_machine != EM_SH:
        raise HH3Error(f"Only EM_SH supported (got e_machine={e_machine:#x})")

    if e_phentsize != 32:
        raise HH3Error(f"Unexpected phentsize={e_phentsize} (expected 32)")

    # Read program headers
    phdrs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        if off + 32 > len(data):
            raise HH3Error(f"Program header {i} out of bounds")
        (p_type, p_offset, p_vaddr, p_paddr,
         p_filesz, p_memsz, p_flags, p_align) = struct.unpack(
            '>IIIIIIII', data[off:off + 32])
        phdrs.append({
            'p_type': p_type, 'p_offset': p_offset, 'p_vaddr': p_vaddr,
            'p_paddr': p_paddr, 'p_filesz': p_filesz, 'p_memsz': p_memsz,
            'p_flags': p_flags, 'p_align': p_align,
        })

    # Read PT_NOTE segments (used by yal for NAME/AUTHOR/DESCRIPTION/VERSION)
    notes = []
    for phdr in phdrs:
        if phdr['p_type'] != PT_NOTE:
            continue
        notes.extend(_parse_notes(data, phdr['p_offset'], phdr['p_filesz']))

    return {
        'e_entry': e_entry,
        'e_phnum': e_phnum,
        'e_phentsize': e_phentsize,
        'phdrs': phdrs,
        'notes': notes,
    }


def _parse_notes(data: bytes, offset: int, size: int) -> List[dict]:
    """Parse all Elf32_Nhdr notes from a PT_NOTE segment."""
    notes = []
    pos = offset
    end = offset + size
    while pos + 12 <= end:
        n_namesz, n_descsz, n_type = struct.unpack('>III', data[pos:pos + 12])
        pos += 12
        # Name and desc are each padded to 4-byte alignment
        name_pad = (4 - n_namesz % 4) % 4
        desc_pad = (4 - n_descsz % 4) % 4
        if pos + n_namesz + name_pad + n_descsz + desc_pad > end:
            break
        name = data[pos:pos + n_namesz].rstrip(b'\x00').decode('utf-8', 'replace')
        pos += n_namesz + name_pad
        desc = data[pos:pos + n_descsz]
        pos += n_descsz + desc_pad
        notes.append({'name': name, 'desc': desc, 'type': n_type})
    return notes


# ---------------------------------------------------------------------------
# hh3 metadata extraction (NAME, AUTHOR, DESCRIPTION, VERSION)
# ---------------------------------------------------------------------------

def get_metadata(parsed: dict) -> Dict[str, Optional[str]]:
    """Extract NAME/AUTHOR/DESCRIPTION/VERSION notes as strings."""
    meta = {'name': None, 'author': None, 'description': None, 'version': None}
    for note in parsed['notes']:
        if note['name'] == 'NAME':
            meta['name'] = note['desc'].rstrip(b'\x00').decode('utf-8', 'replace')
        elif note['name'] == 'AUTHOR':
            meta['author'] = note['desc'].rstrip(b'\x00').decode('utf-8', 'replace')
        elif note['name'] == 'DESCRIPTION':
            meta['description'] = note['desc'].rstrip(b'\x00').decode('utf-8', 'replace')
        elif note['name'] == 'VERSION':
            meta['version'] = note['desc'].rstrip(b'\x00').decode('utf-8', 'replace')
    return meta


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_hh3(classpad, path: str) -> int:
    """Load an .hh3 file into the Classpad's memory map.

    Walks the PT_LOAD segments and copies each one to its p_vaddr using
    the Classpad's MemoryMap (which already has RAM at 0x8C000000 and
    ILRAM at 0xE5200000 mapped).  Zero-fills the bss portion
    (p_memsz - p_filesz).

    Does NOT modify CPU state -- use run_hh3() to also set up PC/SP/args.

    Returns the entry-point virtual address.
    """
    with open(path, 'rb') as f:
        data = f.read()

    parsed = parse_elf(data)
    memmap = classpad.mem

    for phdr in parsed['phdrs']:
        if phdr['p_type'] != PT_LOAD:
            continue
        if phdr['p_memsz'] == 0:
            continue

        vaddr = phdr['p_vaddr']
        filesz = phdr['p_filesz']
        memsz = phdr['p_memsz']

        # Copy file bytes
        if filesz > 0:
            seg_data = data[phdr['p_offset']:phdr['p_offset'] + filesz]
            # Write byte-by-byte through the memory map.  This works
            # for any alignment and any underlying Memory region
            # (RAM, ILRAM, etc.) without needing to know the offset.
            for i, b in enumerate(seg_data):
                memmap.write8(vaddr + i, b)

        # Zero-fill the bss portion (p_memsz - p_filesz)
        # The RAM/ILRAM buffers are pre-zeroed, but if the program was
        # previously loaded (e.g. re-running), the old data may still
        # be there.  Be safe and explicitly zero it.
        for i in range(filesz, memsz):
            memmap.write8(vaddr + i, 0)

    return parsed['e_entry']


def run_hh3(classpad, path: str,
            argv: Optional[List[str]] = None,
            envp: Optional[Dict[str, str]] = None,
            stack_top: int = 0x8C080000) -> int:
    """Load an .hh3 file and set up CPU state to run it.

    Mirrors yal's ELFLoader::execute():
      - Load all PT_LOAD segments
      - Set PC = e_entry
      - Set R15 = stack_top (top of 8MB RAM, grows down)
      - Set up argc/argv/envp on the stack and in R4/R5/R6
        (SH-4 GCC calling convention: R4=argc, R5=argv, R6=envp)

    The argv/envp arrays are written to the stack just below stack_top
    in the standard Unix layout:

        [argv strings][envp strings][padding][envp[]][argv[]][&argc]

    R5 points to argv[0], R6 points to envp[0], R4 holds argc.

    Default argv is [basename(path)] (matches yal's behavior).
    Default envp is {"HHK_SYMBOL_TABLE": "0", "HHK_SYMBOL_TABLE_LEN": "0"}
    (yal fills these with the symbol-table address, but for emulation
    we use 0 since there's no OS symbol table available).

    Returns the entry-point virtual address.
    """
    if argv is None:
        # Default argv[0] = basename of the path (like yal)
        import os
        argv = [os.path.basename(path)]
    if envp is None:
        envp = {
            'HHK_SYMBOL_TABLE': '0',
            'HHK_SYMBOL_TABLE_LEN': '0',
        }

    # 1. Load the ELF
    entry = load_hh3(classpad, path)

    # 2. Build the argv/envp strings and pointer arrays on the stack.
    #
    # Stack layout (growing down from stack_top):
    #
    #   stack_top
    #   | argv strings (NUL-terminated)
    #   v
    #   | envp strings (NUL-terminated, "KEY=VALUE")
    #   v
    #   | 4-byte align
    #   v
    #   | envp[n] = NULL         <-- envp_end_ptr (envp array ends here)
    #   v
    #   | envp[n-1] = ptr
    #   v
    #   | ... envp[0] = ptr      <-- envp_ptr (R6 = this)
    #   v
    #   | argv[argc] = NULL      <-- argv_end_ptr (argv array ends here)
    #   v
    #   | argv[argc-1] = ptr
    #   v
    #   | ... argv[0] = ptr      <-- argv_ptr (R5 = this)
    #   v
    #   | argc (4 bytes)         <-- sp (R15 = this)
    #   v
    #
    # This matches what glibc's _start expects on SH-4.

    memmap = classpad.mem

    # Encode strings
    argv_bytes = [s.encode('utf-8') + b'\x00' for s in argv]
    envp_list = [f'{k}={v}'.encode('utf-8') + b'\x00'
                 for k, v in envp.items()]

    # Layout: start writing strings just below stack_top, growing down.
    # We'll then write the pointer arrays below the strings.
    #
    # To keep things simple, we allocate from the top down:
    #   1. Compute total size needed for strings + arrays + argc
    #   2. Write strings first (top-down)
    #   3. Write pointer arrays (top-down, below strings)
    #   4. Write argc at the very bottom
    #   5. R15 = address of argc

    # Total string size (with 4-byte alignment between strings and arrays)
    argv_str_total = sum(len(s) for s in argv_bytes)
    envp_str_total = sum(len(s) for s in envp_list)

    # Pointer arrays: (argc + 1) entries for argv (NULL-terminated),
    # (envp_count + 1) entries for envp (NULL-terminated), each 4 bytes.
    argv_ptr_total = (len(argv_bytes) + 1) * 4
    envp_ptr_total = (len(envp_list) + 1) * 4

    # Align string section end to 4 bytes for pointer array
    str_total = argv_str_total + envp_str_total
    str_total_aligned = (str_total + 3) & ~3

    total_size = str_total_aligned + argv_ptr_total + envp_ptr_total + 4
    sp = (stack_top - total_size) & 0xFFFFFFF0  # 16-byte align sp

    # 1. Write argv strings (high addresses first, growing down)
    # We write argv strings at the top, envp strings below them.
    addr = stack_top
    argv_str_ptrs = []
    for s in argv_bytes:
        addr -= len(s)
        for i, b in enumerate(s):
            memmap.write8(addr + i, b)
        argv_str_ptrs.append(addr)

    envp_str_ptrs = []
    for s in envp_list:
        addr -= len(s)
        for i, b in enumerate(s):
            memmap.write8(addr + i, b)
        envp_str_ptrs.append(addr)

    # Align addr down to 4 bytes (for pointer array)
    addr &= ~3

    # 2. Write envp pointer array (NULL-terminated), growing down.
    # envp[count] = NULL goes first (highest), then envp[count-1], ..., envp[0].
    # R6 will point to envp[0] (lowest address).
    addr -= 4
    _write32(memmap, addr, 0)  # NULL terminator
    for i in range(len(envp_str_ptrs) - 1, -1, -1):
        addr -= 4
        _write32(memmap, addr, envp_str_ptrs[i])
    envp_ptr = addr

    # 3. Write argv pointer array (NULL-terminated), growing down.
    addr -= 4
    _write32(memmap, addr, 0)  # NULL terminator
    for i in range(len(argv_str_ptrs) - 1, -1, -1):
        addr -= 4
        _write32(memmap, addr, argv_str_ptrs[i])
    argv_ptr = addr

    # 4. Write argc at the very bottom
    addr -= 4
    _write32(memmap, addr, len(argv))
    sp = addr

    # 3. Set up CPU registers
    cpu = classpad.cpu
    cpu.pc = entry & 0xFFFFFFFF
    cpu.regs[15] = sp          # R15 = stack pointer (top of argc)
    cpu.regs[4]  = len(argv)   # R4  = argc
    cpu.regs[5]  = argv_ptr    # R5  = argv
    cpu.regs[6]  = envp_ptr    # R6  = envp
    # PR = 0xFFFFFFFF so a missing RTS is caught
    cpu.regs['pr'] = 0xFFFFFFFF
    # SR: MD=1 (privileged), RB=0, BL=0, IMASK=0
    cpu.regs['sr'] = 0x80000000
    cpu.ebreak = False

    return entry


def _write32(memmap, addr: int, val: int):
    """Write a 32-bit big-endian value through the memory map."""
    memmap.write8(addr,     (val >> 24) & 0xFF)
    memmap.write8(addr + 1, (val >> 16) & 0xFF)
    memmap.write8(addr + 2, (val >> 8) & 0xFF)
    memmap.write8(addr + 3, val & 0xFF)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.hh3>")
        sys.exit(1)

    with open(sys.argv[1], 'rb') as f:
        data = f.read()
    parsed = parse_elf(data)
    meta = get_metadata(parsed)

    print(f"File:         {sys.argv[1]}")
    print(f"Entry:        0x{parsed['e_entry']:08X}")
    print(f"Segments:     {parsed['e_phnum']}")
    for i, phdr in enumerate(parsed['phdrs']):
        if phdr['p_type'] == PT_LOAD:
            flags = ''
            if phdr['p_flags'] & PF_R: flags += 'R'
            if phdr['p_flags'] & PF_W: flags += 'W'
            if phdr['p_flags'] & PF_X: flags += 'X'
            print(f"  [{i}] LOAD vaddr=0x{phdr['p_vaddr']:08X} "
                  f"filesz=0x{phdr['p_filesz']:X} memsz=0x{phdr['p_memsz']:X} "
                  f"flags={flags}")
    print(f"Notes:        {len(parsed['notes'])}")
    for note in parsed['notes']:
        desc_preview = note['desc'][:40].decode('utf-8', 'replace')
        print(f"  name={note['name']!r:20} type={note['type']} "
              f"desc={desc_preview!r}")
    print()
    print("Metadata:")
    for k, v in meta.items():
        print(f"  {k}: {v!r}")
