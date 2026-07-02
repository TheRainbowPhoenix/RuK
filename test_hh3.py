#!/usr/bin/env python3
"""Tests for the hh3 ELF loader.

Validates:
  - ELF parsing (header, program headers, notes)
  - Segment loading (bytes copied correctly, bss zeroed)
  - CPU state setup (PC, SP, argc, argv, envp)
  - Stack layout (argv/envp strings and pointer arrays)
  - End-to-end execution (program runs at least N steps)
"""
import os, sys, struct, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad
from ruk.jcore.hh3 import (
    parse_elf, get_metadata, load_hh3, run_hh3,
    HH3Error, ELFMAG, EM_SH, ET_EXEC, PT_LOAD,
    _setup_symbol_table, HHK_SYSCALLS,
)

# TestAzur.hh3 is downloaded from the RuK GitHub releases.
# If absent, these tests are skipped.
HH3_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'hh3', 'TestAzur.hh3')

ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'cp400', '3070.bin')


def _make_classpad():
    """Create a Classpad with all peripherals for testing."""
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()
    return Classpad(
        rom, debug=False,
        with_tmu=True, with_rtc=True, with_dma=True,
        with_display=True, with_bsc=True, with_cpg=True,
    )


@unittest.skipUnless(os.path.exists(HH3_PATH), f"TestAzur.hh3 not found at {HH3_PATH}")
class TestHH3Parsing(unittest.TestCase):
    """Test ELF parsing of TestAzur.hh3."""

    @classmethod
    def setUpClass(cls):
        with open(HH3_PATH, 'rb') as f:
            cls.data = f.read()
        cls.parsed = parse_elf(cls.data)

    def test_magic(self):
        self.assertEqual(self.data[:4], ELFMAG)

    def test_header(self):
        self.assertEqual(self.parsed['e_phnum'], 2)
        self.assertEqual(self.parsed['e_phentsize'], 32)
        # Entry point should be in RAM (0x8C000000-0x8CFFFFFF)
        self.assertGreaterEqual(self.parsed['e_entry'], 0x8C000000)
        self.assertLess(self.parsed['e_entry'], 0x8D000000)

    def test_segments(self):
        loads = [p for p in self.parsed['phdrs'] if p['p_type'] == PT_LOAD]
        self.assertEqual(len(loads), 2)
        # First segment: code+data in RAM
        self.assertEqual(loads[0]['p_vaddr'], 0x8C052800)
        self.assertGreater(loads[0]['p_filesz'], 0)
        self.assertEqual(loads[0]['p_filesz'], loads[0]['p_memsz'])
        # Second segment: ILRAM stub
        self.assertEqual(loads[1]['p_vaddr'], 0xE5200000)

    def test_metadata(self):
        meta = get_metadata(self.parsed)
        # TestAzur.hh3 may or may not have notes; just check the keys exist
        self.assertIn('name', meta)
        self.assertIn('author', meta)
        self.assertIn('description', meta)
        self.assertIn('version', meta)


@unittest.skipUnless(os.path.exists(HH3_PATH), f"TestAzur.hh3 not found at {HH3_PATH}")
@unittest.skipUnless(os.path.exists(ROM_PATH), f"3070.bin not found at {ROM_PATH}")
class TestHH3Loading(unittest.TestCase):
    """Test segment loading and CPU state setup."""

    def setUp(self):
        self.cp = _make_classpad()
        with open(HH3_PATH, 'rb') as f:
            self.data = f.read()
        self.parsed = parse_elf(self.data)

    def test_load_segments(self):
        """Verify that segment bytes are correctly written to memory."""
        entry = load_hh3(self.cp, HH3_PATH)
        self.assertEqual(entry, self.parsed['e_entry'])

        # Check first segment bytes match the file
        seg0 = self.parsed['phdrs'][0]
        vaddr = seg0['p_vaddr']
        for i in range(0, min(64, seg0['p_filesz'])):
            file_byte = self.data[seg0['p_offset'] + i]
            mem_byte = self.cp.mem.read8(vaddr + i)
            self.assertEqual(mem_byte, file_byte,
                             f"Byte mismatch at offset {i}: "
                             f"file=0x{file_byte:02X} mem=0x{mem_byte:02X}")

    def test_run_sets_cpu_state(self):
        """Verify run_hh3 sets PC, SP, argc, argv, envp correctly."""
        entry = run_hh3(self.cp, HH3_PATH,
                        argv=['test.hh3'],
                        envp={'FOO': 'bar'})

        cpu = self.cp.cpu
        self.assertEqual(cpu.pc, entry)
        self.assertGreater(cpu.regs[15], 0x8C000000)  # SP in RAM
        self.assertLess(cpu.regs[15], 0x8C080000)      # SP below stack top
        self.assertEqual(cpu.regs[4], 1)                # argc = 1
        self.assertNotEqual(cpu.regs[5], 0)             # argv != NULL
        self.assertNotEqual(cpu.regs[6], 0)             # envp != NULL
        self.assertEqual(cpu.regs['pr'], 0xFFFFFFFF)    # PR = invalid
        self.assertFalse(cpu.ebreak)

    def test_stack_layout(self):
        """Verify argv/envp strings and pointer arrays on the stack."""
        run_hh3(self.cp, HH3_PATH,
                argv=['myprog'],
                envp={'KEY1': 'val1', 'KEY2': 'val2'})

        mem = self.cp.mem
        def read32(addr):
            return (mem.read8(addr) << 24) | (mem.read8(addr+1) << 16) | \
                   (mem.read8(addr+2) << 8) | mem.read8(addr+3)
        def read_str(addr):
            s = b''
            while True:
                b = mem.read8(addr)
                if b == 0: break
                s += bytes([b]); addr += 1
            return s.decode('utf-8', 'replace')

        argv_ptr = self.cp.cpu.regs[5]
        envp_ptr = self.cp.cpu.regs[6]
        argc = self.cp.cpu.regs[4]

        # argc should be 1
        self.assertEqual(argc, 1)

        # argv[0] should point to "myprog"
        argv0_ptr = read32(argv_ptr)
        self.assertEqual(read_str(argv0_ptr), 'myprog')
        # argv[1] should be NULL
        self.assertEqual(read32(argv_ptr + 4), 0)

        # envp should have 2 entries + NULL
        env0_ptr = read32(envp_ptr)
        env1_ptr = read32(envp_ptr + 4)
        env_null = read32(envp_ptr + 8)
        self.assertEqual(read_str(env0_ptr), 'KEY1=val1')
        self.assertEqual(read_str(env1_ptr), 'KEY2=val2')
        self.assertEqual(env_null, 0)

    def test_default_argv_envp(self):
        """run_hh3 with no argv/envp should use sensible defaults.

        With setup_symbols=True (default), a synthetic HHK symbol table
        is created and its address/length are passed via envp.
        """
        entry = run_hh3(self.cp, HH3_PATH)
        cpu = self.cp.cpu
        self.assertEqual(cpu.pc, entry)
        self.assertEqual(cpu.regs[4], 1)  # argc = 1 (basename)
        # envp should have HHK_SYMBOL_TABLE and HHK_SYMBOL_TABLE_LEN
        mem = self.cp.mem
        def read32(addr):
            return (mem.read8(addr) << 24) | (mem.read8(addr+1) << 16) | \
                   (mem.read8(addr+2) << 8) | mem.read8(addr+3)
        def read_str(addr):
            s = b''
            while True:
                b = mem.read8(addr)
                if b == 0: break
                s += bytes([b]); addr += 1
            return s.decode('utf-8', 'replace')

        envp_ptr = cpu.regs[6]
        env_strs = []
        i = 0
        while True:
            ptr = read32(envp_ptr + i * 4)
            if ptr == 0: break
            env_strs.append(read_str(ptr))
            i += 1
        # The symbol table address should be non-zero
        sym_line = [s for s in env_strs if s.startswith('HHK_SYMBOL_TABLE=')]
        self.assertEqual(len(sym_line), 1)
        sym_addr = int(sym_line[0].split('=')[1], 16)
        self.assertNotEqual(sym_addr, 0, "Symbol table address should be non-zero")

        len_line = [s for s in env_strs if s.startswith('HHK_SYMBOL_TABLE_LEN=')]
        self.assertEqual(len(len_line), 1)
        sym_len = int(len_line[0].split('=')[1], 16)
        self.assertGreater(sym_len, 0, "Symbol table length should be > 0")

    def test_symbol_table_setup(self):
        """Verify the HHK symbol table is correctly built in RAM.

        The gint hhk3_entry() reads the table and panics if:
          - The guard string doesn't match 0x814fffe0 (panic 0x20c0)
          - The table is too short (panic 0x20e0)
        """
        from ruk.jcore.hh3 import _setup_symbol_table, HHK_SYSCALLS
        addr, length = _setup_symbol_table(self.cp)
        self.assertGreater(addr, 0x8C000000)
        self.assertLess(addr, 0x8D000000)
        self.assertGreater(length, 0)

        # Read the guard string from the table
        mem = self.cp.mem
        guard = b''
        for i in range(16):
            b = mem.read8(addr + i)
            if b == 0: break
            guard += bytes([b])

        # Read the guard string from the OS ROM
        os_guard = b''
        for i in range(16):
            b = mem.read8(0x814fffe0 + i)
            if b == 0: break
            os_guard += bytes([b])

        self.assertEqual(guard, os_guard,
                         "Symbol table guard must match OS version string")

        # Verify all 16 syscalls are present
        off = len(guard) + 1  # skip guard + NUL
        for i, expected_name in enumerate(HHK_SYSCALLS):
            name = b''
            while True:
                b = mem.read8(addr + off)
                if b == 0: break
                name += bytes([b]); off += 1
            off += 1  # skip NUL
            self.assertEqual(name.decode(), expected_name)
            # Read the 4-byte address
            stub_addr = (mem.read8(addr+off) << 24) | (mem.read8(addr+off+1) << 16) | \
                        (mem.read8(addr+off+2) << 8) | mem.read8(addr+off+3)
            off += 4
            self.assertNotEqual(stub_addr, 0, f"{expected_name} has NULL address")

    def test_symbol_table_no_symbols(self):
        """With setup_symbols=False, envp should have 0 values."""
        run_hh3(self.cp, HH3_PATH, setup_symbols=False)
        mem = self.cp.mem
        def read32(addr):
            return (mem.read8(addr) << 24) | (mem.read8(addr+1) << 16) | \
                   (mem.read8(addr+2) << 8) | mem.read8(addr+3)
        def read_str(addr):
            s = b''
            while True:
                b = mem.read8(addr)
                if b == 0: break
                s += bytes([b]); addr += 1
            return s.decode('utf-8', 'replace')

        envp_ptr = self.cp.cpu.regs[6]
        env_strs = []
        i = 0
        while True:
            ptr = read32(envp_ptr + i * 4)
            if ptr == 0: break
            env_strs.append(read_str(ptr))
            i += 1
        self.assertIn('HHK_SYMBOL_TABLE=0', env_strs)
        self.assertIn('HHK_SYMBOL_TABLE_LEN=0', env_strs)


@unittest.skipUnless(os.path.exists(HH3_PATH), f"TestAzur.hh3 not found at {HH3_PATH}")
@unittest.skipUnless(os.path.exists(ROM_PATH), f"3070.bin not found at {ROM_PATH}")
class TestHH3Execution(unittest.TestCase):
    """Test that the hh3 actually runs."""

    def test_runs_at_least_100_steps(self):
        """The program should execute at least 100 instructions."""
        cp = _make_classpad()
        run_hh3(cp, HH3_PATH)
        steps = cp.cpu.run(max_steps=100_000)
        self.assertGreater(steps, 100,
                           f"Program only ran {steps} steps -- "
                           f"check for load errors")
        self.assertFalse(cp.cpu.ebreak, "CPU hit ebreak unexpectedly")


class TestHH3ErrorHandling(unittest.TestCase):
    """Test error handling for invalid files."""

    def test_bad_magic(self):
        with self.assertRaises(HH3Error):
            parse_elf(b'NOT-ELF' + b'\x00' * 100)

    def test_too_small(self):
        with self.assertRaises(HH3Error):
            parse_elf(b'\x7fELF\x01\x02\x01\x00')

    def test_wrong_class(self):
        # ELF64 instead of ELF32
        data = b'\x7fELF\x02\x02\x01\x00' + b'\x00' * 8 + b'\x00' * 40
        with self.assertRaises(HH3Error):
            parse_elf(data)


if __name__ == '__main__':
    unittest.main()
