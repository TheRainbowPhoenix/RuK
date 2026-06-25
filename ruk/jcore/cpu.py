from typing import Union

from ruk.jcore.disassembly import Disassembler
from ruk.jcore.emulator import Emulator  # generated_
from ruk.jcore.memory import MemoryMap


# SH-4 SR bit fields
SR_T     = 1 << 0       # T bit (condition flag)
SR_S     = 1 << 1
SR_IMASK = 0x000000F0   # bits 4-7: interrupt mask
SR_Q     = 1 << 8
SR_M     = 1 << 9
SR_BL    = 1 << 28      # block exceptions/interrupts
SR_RB    = 1 << 29      # register bank select
SR_MD    = 1 << 31      # processor mode (1 = privileged)


class Register:
    """
    Simple SH4 register model
    """
    def __init__(self):
        # Actual register table
        self._regs = {
            'r0': 0x0,
            'r1': 0x0,
            'r2': 0x0,
            'r3': 0x0,
            'r4': 0x0,
            'r5': 0x0,
            'r6': 0x0,
            'r7': 0x0,
            'r8': 0x0,
            'r9': 0x0,
            'r10': 0x0,
            'r11': 0x0,
            'r12': 0x0,
            'r13': 0x0,
            'r14': 0x0,
            'r15': 0x0,
            'r0_bank': 0x0,
            'r1_bank': 0x0,
            'r2_bank': 0x0,
            'r3_bank': 0x0,
            'r4_bank': 0x0,
            'r5_bank': 0x0,
            'r6_bank': 0x0,
            'r7_bank': 0x0,
            'pr': 0x0,
            'sr': 0x0,
            'gbr': 0x0,
            'vbr': 0x0,
            'mach': 0x0,
            'macl': 0x0,
            'spc': 0x0,
            'ssr': 0x0,
            'sgr': 0x0,
            'dbr': 0x0,
        }

    def __getitem__(self, key: Union[int, str]) -> int:
        """
        Helper method to access items
        >>> r = Register()
        >>> print(r[0])
        >>> print('r0')
        :param key: Index of the register (0 to 15) or string name.
        Valid names includes pc, pr, sr, gbr, vbrn mach and macl
        :return: int value
        :raise IndexError: key is not valid
        """
        # Numeric access
        if type(key) == int and 0 <= int(key) <= 15:
            return self._regs[f'r{key}']
        # Name access
        elif type(key) == str:
            key = key.lower()
            if key in self._regs:
                return self._regs[key]
        raise IndexError("Index is not a valid register")

    def __setitem__(self, key: Union[int, str], value: int) -> int:
        """
        >>> r = Register()
        >>> r[0] = 15
        >>> r['r0'] = 15
        Helper to set an item
        :param key: Index of the register (0 to 15) or string name.
        :param value: int value
        :return: int value (the one set)
        :raise IndexError: key is not valid
        """
        # Mask to 32 bits on every write -- negative Python ints and
        # 64-bit `c_long` results would otherwise leak into PC arithmetic.
        value &= 0xFFFFFFFF
        # Numeric access
        if type(key) == int and 0 <= int(key) <= 15:
            self._regs[f'r{key}'] = value
            return value
        elif type(key) == str:
            key = key.lower()
            if key in self._regs:
                self._regs[key] = value
                return value
        raise IndexError("Index is not a valid register")

    def __str__(self) -> str:
        return "Register{" + ', '.join([f'{i}: {self._regs[i]:02X}' for i in self._regs])+"}"

    def dump(self) -> None:
        """
        Dump every registers and print them
        """
        regs = list(self._regs)

        col = 4
        extra = len(regs) % col

        print('\n'.join([
            '\t'.join([f'{r:<4} = {self._regs[r]:02X}' + ('\t' if abs(self._regs[r]) <= 0xFF else '') for r in i])
            for i in zip(*[iter(regs)]*col)
        ]),
            end='\n' + '\t'.join(
                [f'{r:<4} = {self._regs[r]:02X}' + ('\t' if abs(self._regs[r]) <= 0xFF else '') for r in regs[-extra:]]) + '\n'
        )

    def __len__(self):
        return len(self._regs)

    def __iter__(self):
        for x in self._regs.__iter__():
            yield x

    def reset(self):
        """
        Perform CPU reset
        """
        for reg in self._regs:
            self._regs[reg] = 0x0


class PCWrapper:
    """
    PC register wrapper for display
    """
    def __init__(self, parent: 'CPU'):
        self.parent = parent

    def __getitem__(self, item):
        return self.parent.pc

    def __setitem__(self, key, value: int):
        self.parent.pc = value


class CPU:
    """
    Simple SH4 CPU model
    """
    def __init__(self, mem: MemoryMap, start_pc: int, *, debug=False):
        self.ebreak = False
        self.debug = debug
        self.pc = start_pc & 0xFFFFFFFF
        self._start_pc = start_pc
        self._pc_wrap = PCWrapper(self)

        self.mem = mem
        self.regs = Register()
        self.emulator = Emulator(self)
        self.disassembler = Disassembler(debug=debug)

        self.delay_slot_flag = False

        # SH-4 system registers that the original RuK CPU class didn't
        # model.  These are needed by RTE, LDC, STC, and the interrupt
        # delivery path.  See cp-emu/src/cpu.h for the full layout.
        self.spc = 0          # saved PC (for exceptions/interrupts)
        self.ssr = 0          # saved SR
        self.sgr = 0          # saved R15
        self.dbr = 0          # debug base register (UBC handler address)
        self.expevt = 0       # exception event code
        self.tra = 0          # TRAPA argument
        self.intevt = 0       # interrupt event code
        self.tea = 0          # TLB exception address

        # Banked registers (R0_BANK..R7_BANK) -- stored in the Register
        # dict as 'r0_bank'..'r7_bank'.  The r_bank property below is a
        # convenience alias for backwards compatibility.
        # (The swap happens when SR.RB is written -- see interpreter.c.)

        # Sleep state for the SLEEP instruction (cleared by any interrupt).
        self.is_sleeping = False

        # Optional UBC (User Break Controller).  When set, the CPU checks
        # each instruction fetch against the UBC's match conditions and
        # triggers a UBC break if they match.  See ruk/jcore/ubc.py.
        self.ubc = None
        self._ubc_break_pending = False   # set when a break is delivered this cycle

        # Optional callback invoked when a UBC break triggers, BEFORE
        # the break is delivered.  If it returns True, the break is
        # suppressed (useful for "continue through this breakpoint").
        # Signature: on_ubc_break(channel: int, match_addr: int) -> bool
        self.on_ubc_break = None

    @property
    def reg_pc(self):
        return self._pc_wrap

    @property
    def r_bank(self):
        """Convenience list accessor for R0_BANK..R7_BANK."""
        return [self.regs[f'r{i}_bank'] for i in range(8)]

    @r_bank.setter
    def r_bank(self, values):
        for i, v in enumerate(values):
            self.regs[f'r{i}_bank'] = v & 0xFFFFFFFF

    def _sr_t(self) -> int:
        """Get the T bit (bit 0 of SR)."""
        return self.regs['sr'] & 1

    def _set_sr_t(self, value: int):
        """Set or clear the T bit (bit 0 of SR)."""
        if value:
            self.regs['sr'] |= 1
        else:
            self.regs['sr'] &= ~1 & 0xFFFFFFFF

    def _check_ubc(self):
        """
        Check the UBC for an instruction-fetch match at the current PC
        (for channels with PCB=0, i.e. "break before execution").
        """
        self._ubc_break_pending = False
        if self.ubc is None:
            return
        ch = self.ubc.check_instruction_fetch(self.pc, pcb_after=False)
        if ch is None:
            return
        if self.on_ubc_break is not None:
            if self.on_ubc_break(ch, self.pc):
                return
        self._deliver_ubc_break(ch)
        self._ubc_break_pending = True

    def _check_ubc_after(self, pre_pc: int):
        """
        Check the UBC for a "break after execution" match (PCB=1).
        `pre_pc` is the PC of the instruction that just executed.
        """
        self._ubc_break_pending = False
        if self.ubc is None:
            return
        ch = self.ubc.check_instruction_fetch(pre_pc, pcb_after=True)
        if ch is None:
            return
        if self.on_ubc_break is not None:
            if self.on_ubc_break(ch, pre_pc):
                return
        # SPC should point to the instruction AFTER the one that triggered
        # the break (i.e. the current PC, not pre_pc).
        self._deliver_ubc_break(ch)
        # Override SPC to pre_pc (the instruction that was at the break
        # address).  When the handler does RTE, it returns to pre_pc,
        # which is correct for "break after" semantics.
        self.spc = pre_pc & 0xFFFFFFFF
        self._ubc_break_pending = True

    def _deliver_ubc_break(self, channel: int):
        """
        Deliver a UBC (user break) exception.
        Vectors through DBR if CBCR.UBDE=1, else through VBR+0x100.
        EXPEVT is set to 0x1E0 (UBC channel 0) or 0x1A0 (UBC channel 1).

        Note: We do NOT clear the match flag here -- on real hardware the
        handler is responsible for clearing CCMFR (by writing 0).  This
        lets the host inspect which channel triggered the break.
        """
        # Save state
        self.spc = self.pc & 0xFFFFFFFF
        self.ssr = self.regs['sr'] & 0xFFFFFFFF
        self.sgr = self.regs[15] & 0xFFFFFFFF
        # Set EXPEVT
        self.expevt = 0x1E0 if channel == 0 else 0x1A0
        # Block further exceptions, go privileged
        self.regs['sr'] |= SR_MD | SR_BL | SR_RB
        # Vector
        if self.ubc is not None and self.ubc.ubde:
            self.pc = self.dbr & 0xFFFFFFFF
        else:
            vbr = self.regs['vbr']
            self.pc = (vbr + 0x100) & 0xFFFFFFFF
        self.is_sleeping = False

    def step(self):
        try:
            # Check for UBC break before fetching the instruction (PCB=0).
            self._check_ubc()
            if self.ebreak:
                return
            if self._ubc_break_pending:
                self.pc &= 0xFFFFFFFF
                return

            # Save the pre-execution PC for the post-execution UBC check.
            pre_pc = self.pc & 0xFFFFFFFF

            ins = self.mem.read16(self.pc)
            if isinstance(ins, int):
                op_val = ins
            else:
                op_val = int.from_bytes(ins, "big")

            op, args = self.disassembler.disasm(op_val)
            callback = self.emulator.resolve(op)
            callback(**args)

            # Check for UBC break AFTER the instruction (PCB=1).
            # If the instruction that just executed was at a channel's CAR
            # and that channel has PCB=1, deliver the break now.
            self._check_ubc_after(pre_pc)
            if self._ubc_break_pending:
                self.pc &= 0xFFFFFFFF
                return
        except IndexError:
            self.ebreak = True
            if self.debug:
                raise

        # Mask PC to 32 bits.  Negative displacements from branch
        # instructions can produce 33-bit PCs in Python (which has
        # arbitrary-precision ints); the SH-4 is a 32-bit machine.
        self.pc &= 0xFFFFFFFF

    def stacktrace(self):
        self.regs.dump()
        print(f"{'pc':<4} = {self.pc:02X}")
        self.ebreak = True

    def delay_slot(self, addr: int):
        if self.debug:
            print(f"Delay_slot \"{addr:04X}\"")
        pc = self.pc
        self.pc = addr
        self.step()
        self.pc = pc

    def get_surrounding_memory(self, pc=None, size=40):
        if pc == None:
            pc = self.pc
        return self.mem.get_arround(pc, size)

    def reset(self):
        self.pc = self._start_pc
        self.regs.reset()
        self.ebreak = False
