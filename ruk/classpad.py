from ruk.jcore.cpu import CPU
from ruk.jcore.memory import Memory, MemoryMap


class Classpad:
    def __init__(self, rom: bytes, debug: bool = False, start_pc=None, ram_size: int = 0x100_0000,
                 with_tmu: bool = False, with_rtc: bool = False, with_ubc: bool = False,
                 with_dma: bool = False):
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
        self._cpu.regs['sr'] = 0x400000F0   # MD=1 (privileged), IMASK=0xF (all IRQs masked initially)

        # Optional peripherals
        self._tmu = None
        self._rtc = None
        self._ubc = None
        self._dma = None
        self._intc = None

        if with_tmu:
            self._setup_tmu()
        if with_rtc:
            self._setup_rtc()
        if with_ubc:
            self._setup_ubc()
        if with_dma:
            self._setup_dma()

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

    def load_rom(self, rom: bytes):
        self._rom.write_bin(0, rom)
        self._cached_rom.write_bin(0, rom)

    def setup_memory(self):
        self._memory.add(0x8C00_0000, self._ram, name="RAM", perms="RWX")
        self._memory.add(0x8000_0000, self._rom, name="ROM", perms="RX")
        self._memory.add(0xA000_0000, self._cached_rom, name="Cached ROM", perms="RX")

        self.setup_direct_io()

    def setup_direct_io(self):
        pass
        # 0xFEC0_0000 -> 0xFEFF_FFFF

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

    def run(self):
        while not self._cpu.ebreak:
            try:
                self._cpu.step()
            except Exception as e:
                print(f"!!! CPU Error : {e} !!!")
                self._cpu.stacktrace()
                if self.debug:
                    raise

    def add_rom(self, rom: bytes, index: int, name: str = "UserRom", perms: str = None):
        rom_memory = Memory(len(rom))
        rom_memory.write_bin(0, rom)
        self._memory.add(index, rom_memory, name, perms)
