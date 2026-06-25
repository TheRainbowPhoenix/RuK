from ruk.jcore.cpu import CPU
from ruk.jcore.memory import Memory, MemoryMap


class Classpad:
    def __init__(self, rom: bytes, debug: bool = False, start_pc=None, ram_size: int = 0x100_0000,
                 with_tmu: bool = False, with_rtc: bool = False, with_ubc: bool = False,
                 with_dma: bool = False, with_display: bool = False,
                 with_bsc: bool = True, with_cpg: bool = True):
        """
        Create a virtual Classpad II.

        :param rom: rom bytes, raw assembly !
        :param debug: Flag to enable exception and stacktrace printing
        :param with_tmu: If True, attach a TMU+ETMU peripheral and an
                         InterruptController to the CPU.
        :param with_rtc: If True, attach an RTC peripheral.
        :param with_ubc: If True, attach a UBC (User Break Controller)
                         for hardware breakpoints.
        :param with_dma: If True, attach a DMA controller (6 channels).
        :param with_display: If True, attach an R61523 LCD display.
        :param with_bsc: If True, attach a BSC (Bus State Controller).
        :param with_cpg: If True, attach a CPG (Clock Pulse Generator).
        """
        # TODO: get real values !!
        self._ram = Memory(ram_size)
        self._rom = Memory(len(rom))  # 0x1FF_FFFF)
        self._cached_rom = Memory(len(rom))  # 0x1FF_FFFF)
        # Debug turn on stacktrace
        self.debug = debug

        self._memory = MemoryMap()

        self.load_rom(rom)
        self.setup_memory()

        if start_pc is None:
            start_pc = 0x8000_0000

        self._cpu = CPU(self._memory, start_pc=start_pc, debug=debug)

        # Initialize CPU registers to sensible defaults (matching cp-emu).
        # Without these, R15 (stack pointer) is 0, causing immediate
        # crashes on any push (e.g. mov.l r8, @-r15 -> write to 0xFFFFFFFC).
        self._cpu.regs[15] = 0x8C080000     # stack pointer (top of 8MB RAM)
        self._cpu.regs['pr'] = 0xFFFFFFFF   # return address (invalid -- catches missing RTS)
        self._cpu.regs['vbr'] = 0x80020F00  # vector base register (OS exception table)
        self._cpu.regs['sr'] = 0x700000F0   # MD=1, RB=1, BL=1 (privileged, banked, exceptions blocked); IMASK=0xF

        # Register the peripheral auto-tick callback so peripherals
        # advance even when stepping via the GUI (not just in run()).
        self._cpu.on_step = self._tick_peripherals

        # Optional peripherals
        self._cpu_step_count = 0   # for auto-ticking RTC
        self._tmu = None
        self._rtc = None
        self._ubc = None
        self._dma = None
        self._display = None
        self._bsc = None
        self._cpg = None
        self._intc = None

        if with_tmu:
            self._setup_tmu()
        if with_rtc:
            self._setup_rtc()
        if with_ubc:
            self._setup_ubc()
        if with_dma:
            self._setup_dma()
        if with_display:
            self._setup_display()
        if with_bsc:
            self._setup_bsc()
        if with_cpg:
            self._setup_cpg()
        
        self.setup_catch_all_mmio()

    def _setup_tmu(self):
        """Attach the TMU+ETMU peripheral and an InterruptController."""
        from ruk.jcore.tmu import TMU
        from ruk.jcore.mmio import attach_tmu
        from ruk.jcore.intc import InterruptController, attach_intc

        self._tmu = TMU()
        if self._intc is None:
            self._intc = InterruptController()
            attach_intc(self._cpu, self._intc)
            self._intc.enable()
        # Wire TMU IRQs -> INTC -> CPU
        self._tmu.on_irq = self._intc.request
        # Map the TMU MMIO regions into the memory map
        attach_tmu(self._memory, self._tmu)

    def _setup_rtc(self):
        """Attach the RTC peripheral."""
        from ruk.jcore.rtc import RTC
        from ruk.jcore.mmio import attach_rtc
        from ruk.jcore.intc import InterruptController, attach_intc

        self._rtc = RTC()
        if self._intc is None:
            self._intc = InterruptController()
            attach_intc(self._cpu, self._intc)
            self._intc.enable()
        # Wire RTC IRQs -> INTC -> CPU
        self._rtc.on_irq = self._intc.request
        # Map the RTC MMIO region
        attach_rtc(self._memory, self._rtc)

    def _setup_ubc(self):
        """Attach the UBC (User Break Controller) for hardware breakpoints."""
        from ruk.jcore.ubc import UBC
        from ruk.jcore.mmio import attach_ubc

        self._ubc = UBC()
        # Wire the UBC into the CPU (the CPU checks it on each instruction)
        self._cpu.ubc = self._ubc
        # Enable UBDE (User Break Debugging Support) so breaks vector
        # through DBR.  The host should set DBR to the handler address
        # before running.  If DBR is 0, breaks will vector through
        # VBR+0x100 instead.
        self._ubc.cbcr = 1 << 31   # CBCR.UBDE = 1
        # Map the UBC MMIO region
        attach_ubc(self._memory, self._ubc)

    def _setup_dma(self):
        """Attach the DMA controller (6 channels)."""
        from ruk.jcore.dma import DMA
        from ruk.jcore.mmio import attach_dma

        self._dma = DMA()
        # Wire DMA end-of-transfer IRQs -> INTC (if present)
        if self._intc is not None:
            self._dma.on_irq = self._intc.request
        # Map the DMA MMIO region
        attach_dma(self._memory, self._dma)

    def _setup_display(self):
        """Attach the R61523 LCD display."""
        from ruk.jcore.display import Display
        from ruk.jcore.mmio import attach_display

        self._display = Display()
        attach_display(self._memory, self._display)

    def _setup_bsc(self):
        """Attach the BSC (Bus State Controller)."""
        from ruk.jcore.bsc import BSC
        from ruk.jcore.mmio import attach_bsc
        self._bsc = BSC()
        attach_bsc(self._memory, self._bsc)

    def _setup_cpg(self):
        """Attach the CPG (Clock Pulse Generator) + Power (MSTPCR)."""
        from ruk.jcore.cpg import CPG
        from ruk.jcore.mmio import attach_cpg
        self._cpg = CPG()
        attach_cpg(self._memory, self._cpg)

    def load_rom(self, rom: bytes):
        self._rom.write_bin(0, rom)
        self._cached_rom.write_bin(0, rom)

    def setup_memory(self):
        # RAM (P1, uncached) and its P2 alias (cached)
        self._memory.add(0x8C00_0000, self._ram, name="RAM", perms="RWX")
        self._memory.add(0xAC00_0000, self._ram, name="RAM (P2 cached)", perms="RWX")

        # ROM (P1) and its P2 alias
        self._memory.add(0x8000_0000, self._rom, name="ROM", perms="RX")
        self._memory.add(0xA000_0000, self._cached_rom, name="Cached ROM", perms="RX")

        # 64KB null page at address 0 (catches null pointer dereferences)
        self._null_page = Memory(0x10000)
        self._memory.add(0x00000000, self._null_page, name="Null page", perms="RW")

        # ILRAM (4KB at 0xE5200000) -- instruction/data RAM
        self._ilram = Memory(0x1000)
        self._memory.add(0xE5200000, self._ilram, name="ILRAM", perms="RWX")

        # XRAM (8KB at 0xE5000000, wraps every 8KB) -- DSP X memory
        # The OS accesses up to 0xE507FFFF, so we map 512KB and let the
        # OS handle wrapping (or just provide a large enough buffer).
        self._xram = Memory(0x80000)   # 512KB (covers wrapping)
        self._memory.add(0xE5000000, self._xram, name="XRAM", perms="RW")

        # YRAM (8KB at 0xE5010000, wraps every 8KB) -- DSP Y memory
        self._yram = Memory(0x80000)   # 512KB
        self._memory.add(0xE5010000, self._yram, name="YRAM", perms="RW")

        # RS memory (16KB at 0xFD800000) -- storage memory
        self._rs = Memory(0x4000)
        self._memory.add(0xFD800000, self._rs, name="RS memory", perms="RW")

        # PRAM0 (160KB at 0xFE200000) -- display RAM or similar
        self._pram0 = Memory(160 * 1024)
        self._memory.add(0xFE200000, self._pram0, name="PRAM0", perms="RW")

        # XRAM0 (224KB at 0xFE240000) -- extended RAM
        self._xram0 = Memory(224 * 1024)
        self._memory.add(0xFE240000, self._xram0, name="XRAM0", perms="RW")

        # Additional VRAM/PRAM area at 0xFE280000 (512KB) -- used by OS for display buffers
        self._vram = Memory(0x80000)   # 512KB
        self._memory.add(0xFE280000, self._vram, name="VRAM", perms="RW")

        # FE300000 area (1MB) -- more display/OS buffer area, also contains DSP1 at 0xFE3FFD00
        self._fe3 = Memory(0x100000)
        self._memory.add(0xFE300000, self._fe3, name="FE3 area (DSP1)", perms="RW")

        # SPU at 0xFE2FFC00 (256 bytes, covers SPU + DSP0 registers)
        # spu_t starts at 0xFE2FFC00, spu_dsp_t (DSP0) starts at 0xFE2FFD00
        # Both are within the VRAM area (0xFE280000) but let's be explicit.
        # DSP1 is at 0xFE3FFD00 (within FE3 area).
        # These are already covered by the catch-all memory above, so no
        # additional mapping is needed -- the OS can read/write the registers.

        # Catch-all MMIO regions for Casio SH7305 peripheral space.
        # The OS writes to various undocumented MMIO registers during boot.
        # We silently accept all reads (returning 0) and writes.
        # Region 1: 0xA4000000-0xA4FFFFFF (1MB, covers most Casio peripherals)
        # Region 2: 0xA4150000-0xA4160000 (64KB, CPG area -- overlaps region 1
        #            but MemoryMap resolves the first match, so we add it first)
        # Region 3: 0xFEC00000-0xFEC40000 (256KB, undocumented I/O)
        # self._mmio_a4 = Memory(0x1000000)   # 16MB at 0xA4000000
        # self._memory.add(0xA4000000, self._mmio_a4, name="MMIO (A4xxxxxx)", perms="RW")

        # 0xFF000000 area (BSC, UBC, etc.)
        # self._mmio_ff = Memory(0x1000000)   # 16MB at 0xFF000000
        # self._memory.add(0xFF000000, self._mmio_ff, name="MMIO (FFxxxxxx)", perms="RW")

        # self._mmio_catchall = Memory(0x40000)   # 256KB at 0xFEC00000
        # self._memory.add(0xFEC00000, self._mmio_catchall, name="MMIO (catch-all)", perms="RW")

        self.setup_direct_io()

        # self.setup_catch_all_mmio()

    def setup_direct_io(self):
        pass
        # 0xFEC0_0000 -> 0xFEFF_FFFF

    def setup_catch_all_mmio(self):
        """Add catch-all MMIO regions AFTER all specific peripherals so
        MemoryMap first-match resolution falls through to them."""
        self._mmio_a4 = Memory(0x1000000)
        self._memory.add(0xA4000000, self._mmio_a4, name="MMIO (A4xxxxxx)", perms="RW")

        self._mmio_ff = Memory(0x1000000)
        self._memory.add(0xFF000000, self._mmio_ff, name="MMIO (FFxxxxxx)", perms="RW")

        self._mmio_catchall = Memory(0x40000)
        self._memory.add(0xFEC00000, self._mmio_catchall, name="MMIO (catch-all)", perms="RW")

    @property
    def cpu(self):
        return self._cpu

    @property
    def ram(self):
        return self._ram

    @property
    def tmu(self):
        """The TMU peripheral, or None if not attached."""
        return self._tmu

    @property
    def rtc(self):
        """The RTC peripheral, or None if not attached."""
        return self._rtc

    @property
    def ubc(self):
        """The UBC peripheral, or None if not attached."""
        return self._ubc

    @property
    def dma(self):
        """The DMA peripheral, or None if not attached."""
        return self._dma

    @property
    def display(self):
        """The Display peripheral, or None if not attached."""
        return self._display

    @property
    def bsc(self):
        """The BSC peripheral, or None if not attached."""
        return self._bsc

    @property
    def cpg(self):
        """The CPG peripheral, or None if not attached."""
        return self._cpg

    @property
    def intc(self):
        """The InterruptController, or None if not attached."""
        return self._intc

    def tick_tmu(self, pphi_cycles: int = 0, rtc_cycles: int = 0):
        """
        Advance the TMU/ETMU by the given number of cycles.  Any pending
        IRQs are queued to the INTC and will be delivered before the
        next CPU instruction.
        """
        if self._tmu is not None:
            self._tmu.tick(pphi_cycles=pphi_cycles, rtc_cycles=rtc_cycles)

    def tick_rtc(self, ticks_128hz: int = 1):
        """
        Advance the RTC by `ticks_128hz` 128-Hz ticks (default 1).
        Call this 128 times per emulated second for real-time speed.
        """
        if self._rtc is not None:
            self._rtc.tick_128hz(ticks_128hz)

    def _tick_peripherals(self, step_count: int):
        """Auto-tick peripherals.  Called after every CPU step.

        Tick rates are calibrated to let the Casio OS boot code make
        forward progress on its polling loops:
          - RTC R64CNT ticks at ~1 tick per 4 CPU steps.  The OS polls
            R64CNT waiting for it to change (at 0xA00008CC); ticking
            every 4 steps means R64CNT advances fast enough for the
            "cmp/gt r4, r0" check (r4=2) to pass within ~12 CPU steps.
          - CMT ticks every step.  The OS polls CMCSR.CMF waiting for
            a compare match (at 0x800034CC); with CMCOR=0x1200 (4608),
            ticking every step means CMF is set after ~4608 CPU steps,
            which is fast enough for boot.  The real ratio would be
            ~257 CPU cycles per CMT tick (118 MHz / 459 KHz), but
            that's too slow for emulation.
        """
        # Tick RTC every 4 steps (R64CNT advances fast enough for boot)
        if self._rtc is not None and (step_count & 0x3) == 0:
            self._rtc.tick_128hz(1)
            if not (self._rtc.rcr2 & 0x01):
                self._rtc.rcr2 |= 0x01
        # Tick CMT every step (so CMF gets set fast enough for the
        # OS polling loop at 0x800034CC)
        if self._tmu is not None:
            self._tmu.tick_cmt(1)

    def run(self):
        while not self._cpu.ebreak:
            try:
                self._cpu.step()
                # Peripheral ticking is handled by the on_step callback
                # registered in __init__, so it works in both run() and
                # GUI stepping modes.
            except Exception as e:
                print(f"!!! CPU Error : {e} !!!")
                self._cpu.stacktrace()
                self._dump_full_state()
                if self.debug:
                    raise

    def _dump_full_state(self):
        """Print a complete dump of all CPU registers for debugging."""
        r = self._cpu.regs
        print("\n--- Full CPU State ---")
        for i in range(0, 16, 4):
            print(f"  R{i:<2}=0x{r[i]:08X}  R{i+1:<2}=0x{r[i+1]:08X}  "
                  f"R{i+2:<2}=0x{r[i+2]:08X}  R{i+3:<2}=0x{r[i+3]:08X}")
        print(f"  PR =0x{r['pr']:08X}  SR =0x{r['sr']:08X}  "
              f"GBR=0x{r['gbr']:08X}  VBR=0x{r['vbr']:08X}")
        print(f"  MACH=0x{r['mach']:08X}  MACL=0x{r['macl']:08X}")
        print(f"  PC =0x{self._cpu.pc:08X}  SPC=0x{self._cpu.spc:08X}  "
              f"SSR=0x{self._cpu.ssr:08X}  SGR=0x{self._cpu.sgr:08X}")
        print(f"  DBR=0x{self._cpu.dbr:08X}  EXPEVT=0x{self._cpu.expevt:08X}  "
              f"TRA=0x{self._cpu.tra:08X}  INTEVT=0x{self._cpu.intevt:08X}")
        print(f"  TEA=0x{self._cpu.tea:08X}  sleeping={self._cpu.is_sleeping}")
        # Dump banked registers
        rb = self._cpu.r_bank
        if any(v != 0 for v in rb):
            print(f"  R0B=0x{rb[0]:08X}  R1B=0x{rb[1]:08X}  "
                  f"R2B=0x{rb[2]:08X}  R3B=0x{rb[3]:08X}")
            print(f"  R4B=0x{rb[4]:08X}  R5B=0x{rb[5]:08X}  "
                  f"R6B=0x{rb[6]:08X}  R7B=0x{rb[7]:08X}")
        print("--- End State ---\n")

    def add_rom(self, rom: bytes, index: int, name: str = "UserRom", perms: str = None):
        rom_memory = Memory(len(rom))
        rom_memory.write_bin(0, rom)
        self._memory.add(index, rom_memory, name, perms)
