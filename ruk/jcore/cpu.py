from typing import Union

from ruk.jcore.disassembly import Disassembler
from ruk.jcore.emulator import Emulator  # generated_
from ruk.jcore.memory import MemoryMap
from ruk.jcore.mmu import MMUFault


# ----------------------------------------------------------------------------
# Dispatch helpers for opcodes that fall through the precomputed table.
# These are module-level functions (not closures) so they can be cached
# in Emulator._dsp_cache and re-invoked without creating new bound-method
# objects on each step.
# ----------------------------------------------------------------------------

def _dsp_dispatch(cpu, op_val: int):
    """Re-invoke the DSP instruction handler for `op_val` on `cpu`."""
    from ruk.jcore.dsp import handle_dsp_instruction
    handle_dsp_instruction(cpu, op_val)


def _nop_dispatch(cpu, op_val: int):
    """Advance PC by 2 (treat as NOP).  Used for truly unknown opcodes."""
    cpu.pc = (cpu.pc + 2) & 0xFFFFFFFF


# ----------------------------------------------------------------------------
# SyncedRegisterDict: a dict that mirrors writes back into the Register's
# fast _r list / _sys dict.  This exists so legacy code that does
# `regs._regs['r15'] = 0xFF` (e.g. ruk/tests/test_register.py) keeps
# working -- subsequent `regs[15]` reads see the new value.
# ----------------------------------------------------------------------------

class _SyncedRegisterDict(dict):
    """A dict whose __setitem__ mirrors writes into the parent Register.

    Only the keys 'r0'..'r15', 'r0_bank'..'r7_bank', and the system
    register names are mirrored.  Other keys are stored normally.
    """

    __slots__ = ('_parent',)

    def __init__(self, parent):
        super().__init__()
        self._parent = parent

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        # Mirror into the fast storage.
        parent = self._parent
        if type(key) is str:
            k = key.lower()
            # r0..r9
            if len(k) == 2 and k[0] == 'r' and k[1].isdigit():
                idx = ord(k[1]) - ord('0')
                parent._r[idx] = value & 0xFFFFFFFF
                parent._regs_dirty = True
                return
            # r10..r15
            if len(k) == 3 and k[0] == 'r' and k[1].isdigit() and k[2].isdigit():
                idx = (ord(k[1]) - ord('0')) * 10 + (ord(k[2]) - ord('0'))
                if 0 <= idx < 16:
                    parent._r[idx] = value & 0xFFFFFFFF
                    parent._regs_dirty = True
                    return
            # system / banked registers
            if k in parent._sys:
                parent._sys[k] = value & 0xFFFFFFFF
                parent._regs_dirty = True


# SH-4 SR bit fields (see cp-emu/src/cpu.h)
SR_T     = 1 << 0       # T bit (condition flag)
SR_S     = 1 << 1
SR_IMASK = 0x000000F0   # bits 4-7: interrupt mask
SR_Q     = 1 << 8
SR_M     = 1 << 9
SR_BL    = 1 << 28      # block exceptions/interrupts
SR_RB    = 1 << 29      # register bank select
SR_MD    = 1 << 30      # processor mode (1 = privileged)


class Register:
    """
    Simple SH4 register model.

    Performance: r0-r15 are stored in a list (self._r) for O(1) integer
    indexing -- the original dict-with-string-keys approach required
    f-string formatting ('r{n}') on every access which dominated the
    profile.  System registers (pr, sr, gbr, vbr, mach, macl, spc, ssr,
    sgr, dbr, and the DSP regs) remain in a dict keyed by lowercase name.

    The dict _regs is still populated with the same keys as before so
    that test_register.py and any external code that does
    `regs._regs['r15'] = ...` keeps working.
    """
    _SYS_NAMES = (
        'pr', 'sr', 'gbr', 'vbr', 'mach', 'macl',
        'spc', 'ssr', 'sgr', 'dbr',
        'x0', 'x1', 'y0', 'y1',
        'a0', 'a0g', 'a1', 'a1g', 'm0', 'm1',
        'rs', 're', 'rc', 'dsr', 'mod',
    )

    def __init__(self):
        # self._regs = {
        #     'r0': 0x0,
        #     'r1': 0x0,
        #     'r2': 0x0,
        #     'r3': 0x0,
        #     'r4': 0x0,
        #     'r5': 0x0,
        #     'r6': 0x0,
        #     'r7': 0x0,
        #     'r8': 0x0,
        #     'r9': 0x0,
        #     'r10': 0x0,
        #     'r11': 0x0,
        #     'r12': 0x0,
        #     'r13': 0x0,
        #     'r14': 0x0,
        #     'r15': 0x0,
        #     'r0_bank': 0x0,
        #     'r1_bank': 0x0,
        #     'r2_bank': 0x0,
        #     'r3_bank': 0x0,
        #     'r4_bank': 0x0,
        #     'r5_bank': 0x0,
        #     'r6_bank': 0x0,
        #     'r7_bank': 0x0,
        #     'pr': 0x0,
        #     'sr': 0x0,
        #     'gbr': 0x0,
        #     'vbr': 0x0,
        #     'mach': 0x0,
        #     'macl': 0x0,
        #     'spc': 0x0,
        #     'ssr': 0x0,
        #     'sgr': 0x0,
        #     'dbr': 0x0,
        #     # DSP registers (SH4AL-DSP)
        #     'x0': 0x0, 'x1': 0x0,
        #     'y0': 0x0, 'y1': 0x0,
        #     'a0': 0x0, 'a0g': 0x0,
        #     'a1': 0x0, 'a1g': 0x0,
        #     'm0': 0x0, 'm1': 0x0,
        #     'rs': 0x0, 're': 0x0, 'rc': 0x0,
        #     'dsr': 0x0,
        #     'mod': 0x0,    # DSP mode register (used by repeat loops)
        # }
        # Fast list for r0..r15 (the hot path).
        self._r = [0] * 16
        # Dict for system registers (slow path, but small).
        self._sys = {name: 0 for name in Register._SYS_NAMES}
        # Banked registers r0_bank..r7_bank -- kept in _sys.
        for i in range(8):
            self._sys[f'r{i}_bank'] = 0

        # Backwards-compat dict -- a plain dict populated eagerly with
        # all register names so __str__/dump()/__iter__/external code
        # that does `for name in regs._regs` works.
        # We DON'T mirror writes here (too slow -- 5M extra calls in the
        # LCD benchmark).  Instead, _regs is rebuilt lazily from _r/_sys
        # when something actually reads it (via _sync_legacy_dict).
        # Tests that do `regs._regs['r15'] = X` directly WILL still work
        # because _SyncedRegisterDict.__setitem__ mirrors back to _r.
        rd = _SyncedRegisterDict(self)
        for i in range(16):
            dict.__setitem__(rd, f'r{i}', 0)
        for i in range(8):
            dict.__setitem__(rd, f'r{i}_bank', 0)
        for name in Register._SYS_NAMES:
            dict.__setitem__(rd, name, 0)
        self._regs = rd
        # Dirty flag: set True whenever _r / _sys changes; cleared when
        # _sync_legacy_dict() refreshes _regs.
        self._regs_dirty = True

    @property
    def regs(self):
        """Legacy dict view (always available, kept in sync)."""
        return self._regs

    def __getitem__(self, key: Union[int, str]) -> int:
        """
        Access a register by index (0-15) or by name.
        Names: 'r0'..'r15', 'r0_bank'..'r7_bank', 'pr', 'sr', 'gbr',
        'vbr', 'mach', 'macl', 'spc', 'ssr', 'sgr', 'dbr', 'x0', 'x1',
        'y0', 'y1', 'a0', 'a0g', 'a1', 'a1g', 'm0', 'm1', 'rs', 're',
        'rc', 'dsr'.
        """
        # Numeric access -- the hot path.  List index, no dict, no
        # f-string formatting.
        if type(key) is int:
            if 0 <= key < 16:
                return self._r[key]
            raise IndexError(f"Register index out of range: {key}")
        # Name access
        if type(key) is str:
            if key == 'sr':
                return self._sys['sr']
            k = key.lower()
            # Quick path for 'r0'..'r9' (single digit)
            if len(k) == 2 and k[0] == 'r' and k[1].isdigit():
                return self._r[ord(k[1]) - ord('0')]
            # Quick path for 'r10'..'r15' (two digits)
            if len(k) == 3 and k[0] == 'r' and k[1].isdigit() and k[2].isdigit():
                idx = (ord(k[1]) - ord('0')) * 10 + (ord(k[2]) - ord('0'))
                if 0 <= idx < 16:
                    return self._r[idx]
            if k in self._sys:
                return self._sys[k]
        raise IndexError("Index is not a valid register")

    def __setitem__(self, key: Union[int, str], value: int) -> int:
        """
        Set a register by index (0-15) or by name.  See __getitem__ for
        the list of valid names.
        """
        # Mask to 32 bits on every write -- negative Python ints and
        # 64-bit `c_long` results would otherwise leak into PC arithmetic.
        value &= 0xFFFFFFFF
        # Numeric access -- hot path.  We do NOT mirror to _regs here
        # (that was costing ~5s in the LCD benchmark).  Instead we set
        # the dirty flag and let _sync_legacy_dict() refresh _regs only
        # when something actually reads it.
        if type(key) is int:
            if 0 <= key < 16:
                self._r[key] = value
                self._regs_dirty = True
                return value
            raise IndexError(f"Register index out of range: {key}")
        if type(key) is str:
            k = key.lower()
            if len(k) == 2 and k[0] == 'r' and k[1].isdigit():
                self._r[ord(k[1]) - ord('0')] = value
                self._regs_dirty = True
                return value
            if len(k) == 3 and k[0] == 'r' and k[1].isdigit() and k[2].isdigit():
                idx = (ord(k[1]) - ord('0')) * 10 + (ord(k[2]) - ord('0'))
                if 0 <= idx < 16:
                    self._r[idx] = value
                    self._regs_dirty = True
                    return value
            if k in self._sys:
                if k == 'sr' and getattr(self, 'bank_switching', False):
                    old_bank = (self._sys['sr'] & 0x60000000) == 0x60000000
                    new_bank = (value & 0x60000000) == 0x60000000
                    if old_bank != new_bank:
                        for i in range(8):
                            bank_name = f'r{i}_bank'
                            self._r[i], self._sys[bank_name] = self._sys[bank_name], self._r[i]
                self._sys[k] = value
                self._regs_dirty = True
                return value
        raise IndexError("Index is not a valid register")

    def __str__(self) -> str:
        # Refresh legacy dict view from _r/_sys so it's up to date.
        self._sync_legacy_dict()
        return "Register{" + ', '.join([f'{i}: {self._regs[i]:02X}' for i in self._regs])+"}"

    def _sync_legacy_dict(self):
        """Refresh the legacy _regs dict from _r / _sys (read-side sync).

        Only rebuilds when _regs_dirty is True -- this avoids the 5M
        extra dict writes that the eager-mirror approach was costing
        in the LCD benchmark.
        """
        if not self._regs_dirty:
            return
        rd = self._regs
        for i in range(16):
            dict.__setitem__(rd, f'r{i}', self._r[i])
        for k in self._sys:
            dict.__setitem__(rd, k, self._sys[k])
        self._regs_dirty = False

    def __str__(self) -> str:
        self._sync_legacy_dict()
        return "Register{" + ', '.join([f'{i}: {self._regs[i]:02X}' for i in self._regs])+"}"

    def dump(self) -> None:
        """
        Dump every register and print them.
        """
        self._sync_legacy_dict()
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
        # Total number of registers exposed via the legacy dict view.
        # (16 general + 8 banked + 25 system = 49)
        return 49 # len(self._regs)

    def __iter__(self):
        # Iterate register names in the legacy dict order.
        for x in self._regs.__iter__():
            yield x

    def reset(self):
        """
        Perform CPU reset -- zero all general, banked, and system registers.
        """
        for i in range(16):
            self._r[i] = 0
        for k in self._sys:
            self._sys[k] = 0
        self._regs_dirty = True


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
        self._ldst = False
        self._pc_wrap = PCWrapper(self)

        self.mem = mem
        self.regs = Register()
        # Optional target-specific bytecode translation unit backend.
        self.btu = None
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

        # Step counter and peripheral tick callback.
        # The host (Classpad) registers a callback here that ticks
        # peripherals (RTC, CMT, etc.) every N steps.  This ensures
        # peripherals advance even when stepping via the GUI.
        self._step_count = 0
        self.on_step = None  # callback(step_count: int) -> None

        # DSP repeat-loop active flag, armed by repeat setup and cleared
        # by step() when RC reaches zero. This gates the RE/RS check so the common
        # case (no DSP loop active) pays zero cost.
        self._dsp_active = False

    @property
    def reg_pc(self):
        return self._pc_wrap

    @property
    def r_bank(self):
        """Convenience list accessor for R0_BANK..R7_BANK."""
        return [self.regs._sys[f'r{i}_bank'] for i in range(8)]

    @r_bank.setter
    def r_bank(self, values):
        sysd = self.regs._sys
        for i, v in enumerate(values):
            sysd[f'r{i}_bank'] = v & 0xFFFFFFFF
            if self.regs._regs is not None:
                self.regs._regs[f'r{i}_bank'] = v & 0xFFFFFFFF

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
        self._ldst = False
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
        """Execute one SH-4 instruction at self.pc.

        Hot path -- this method runs millions of times per second, so
        every operation matters.  Optimizations applied:

          1. UBC fast-path: when self.ubc is None (no UBC configured),
             skip _check_ubc() / _check_ubc_after() entirely.

          2. No isinstance() on read16() result -- always int now.

          3. Direct dispatch table lookup (single list index into
             self.emulator._dispatch) instead of disassembler.disasm()
             + emulator.resolve() (linear scan of 170 entries).

          4. Positional args call instead of **kwargs dispatch.

          5. DSP repeat-loop check gated on self._dsp_active flag.

          6. (OPT-10) Cache hot attributes (mem, dispatch, emulator,
             dsp_active) as locals at function entry to avoid repeated
             attribute lookups on self -- CPython attribute access is
             a dict lookup on each `self.X` and costs ~30ns each.
        """
        ubc = self.ubc
        # ---- Pre-execution UBC check (PCB=0 break before fetch) ----
        if ubc is not None:
            self._check_ubc()
            if self.ebreak:
                return
            if self._ubc_break_pending:
                self.pc &= 0xFFFFFFFF
                return

        pre_pc = self.pc & 0xFFFFFFFF
        mem = self.mem
        emu = self.emulator
        dispatch = emu._dispatch
        dsp_cache = emu._dsp_cache

        try:
            op_val = mem.fetch16(pre_pc) if hasattr(mem, 'fetch16') else mem.read16(pre_pc)

            # ---- Dispatch ----
            from ruk.jcore.dsp import is_dsp_instruction, handle_dsp_instruction, handle_dsp_transfer
            entry = dispatch[op_val]
            dsp_enabled = self.regs._sys['sr'] & 0x1000
            if dsp_enabled and handle_dsp_transfer(self, op_val):
                pass
            elif (op_val & 0xF0FF) == 0x0043:
                # Sdsha's TRACE handler reads Rn for trace instrumentation.
                _ = self.regs[(op_val >> 8) & 15]
                self.pc = (pre_pc + 2) & 0xFFFFFFFF
            elif dsp_enabled and is_dsp_instruction(op_val):
                # DSP enable can change at runtime; never cache this decision.
                if not handle_dsp_instruction(self, op_val):
                    self.pc = (pre_pc + 2) & 0xFFFFFFFF
            elif entry is not None:
                # Happy path: precomputed (handler, args_tuple).
                # `handler(*args)` is the positional-call form -- ~30%
                # faster than `handler(**args)` because CPython skips
                # the kwargs dict unpacking.
                handler, args = entry
                handler(*args)
            else:
                # Unknown / SH4AL-DSP / unimplemented.  Probe once and
                # cache the result so we don't repeat the probe for the
                # same opcode on every step.
                cached = dsp_cache.get(op_val, False)
                if cached is False:
                    # First time seeing this opcode -- run the probe.
                    self._handle_unknown_op(op_val, pre_pc)
                elif cached is not None:
                    cached(self, op_val)  # DSP wrapper

            # ---- Post-execution UBC check (PCB=1 break after exec) ----
            if ubc is not None:
                self._check_ubc_after(pre_pc)
                if self._ubc_break_pending:
                    self.pc &= 0xFFFFFFFF
                    return

            # ---- DSP repeat-loop handling (SH4AL-DSP zero-overhead loop) ----
            # Only check if a repeat loop is currently active (RC > 0).
            # The loop-exhaustion path sets _dsp_active back to False.
            if self._dsp_active:
                re_addr = self.regs._sys['re'] & ~1
                is_setrc = ((op_val & 0xf0ff) in (0x4014, 0x4034)
                            or (op_val & 0xff00) in (0x8200, 0x8a00))
                size = 4 if (op_val & 0xfc00) == 0xf800 else 2
                fell_through = self.pc == ((pre_pc + size) & 0xffffffff)
                if pre_pc == re_addr and not is_setrc and fell_through:
                    rc = self.regs._sys['rc']
                    if rc > 0:
                        new_rc = rc - 1
                        self.regs._sys['rc'] = new_rc
                        self.regs._sys['sr'] = ((self.regs._sys['sr'] & ~0x0fff0000)
                                                | ((new_rc & 0xfff) << 16))
                        if new_rc > 0:
                            # Loop continues: branch back to RS.
                            self.pc = self.regs._sys['rs'] & 0xFFFFFFFF
                        else:
                            # Loop just ended: fall through past RE.
                            self._dsp_active = False

        except MMUFault as fault:
            self._ldst = False
            if fault.event == 0x140 or self.regs['sr'] & SR_BL:
                self.expevt = 0x140 if fault.event == 0x140 else 0x20
                self.mmu.write_reg(0xff000010, 4)
                self.regs['sr'] = 0x700000f0
                self.regs['vbr'] = 0
                self.pc = 0xa0000000
            else:
                self.spc = pre_pc
                self.ssr = self.regs['sr']
                self.sgr = self.regs[15]
                self.expevt = fault.event
                self.regs['sr'] = self.ssr | 0x70000000
                self.pc = (self.regs['vbr'] + fault.vector) & 0xffffffff
        except IndexError:
            self._ldst = False
            self.ebreak = True
            if self.debug:
                raise

        # Mask PC to 32 bits.  Negative displacements from branch
        # instructions can produce 33-bit PCs in Python (which has
        # arbitrary-precision ints); the SH-4 is a 32-bit machine.
        self.pc &= 0xFFFFFFFF
        self._step_count += 1
        if self.on_step is not None:
            self.on_step(self._step_count)

    def _handle_unknown_op(self, op_val: int, pre_pc: int):
        """
        Called when the dispatch table has no entry for `op_val`.
        Probes the DSP instruction handler; if that fails too, treats
        the instruction as a NOP (advances PC by 2) and warns once.

        Caches the result in self.emulator._dsp_cache so that subsequent
        encounters of the same opcode skip the probe.
        """
        from ruk.jcore.dsp import handle_dsp_instruction
        if handle_dsp_instruction(self, op_val):
            # It was a DSP instruction.  Cache a wrapper that re-invokes
            # handle_dsp_instruction -- we can't precompute the handler
            # because DSP instructions depend on DSP register state.
            self.emulator._dsp_cache[op_val] = _dsp_dispatch
        else:
            # Unknown instruction (likely SH4AL-DSP specific).
            if not hasattr(self, '_warned_unknown'):
                self._warned_unknown = set()
            if op_val not in self._warned_unknown:
                print(f"[WARN] Unknown instruction 0x{op_val:04X} at "
                      f"PC=0x{pre_pc:08X} -- skipping (treating as NOP)")
                self._warned_unknown.add(op_val)
            self.pc = (pre_pc + 2) & 0xFFFFFFFF
            # Cache a NOP-advance wrapper for subsequent encounters.
            self.emulator._dsp_cache[op_val] = _nop_dispatch

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

    def run(self, max_steps: int = 10000000) -> int:
        """Execute up to max_steps instructions using the interpreter."""
        count = 0
        while count < max_steps and not self.ebreak:
            self.step()
            count += 1
        return count

    def run_with_check(self, should_continue, max_steps_per_batch: int = 2000,
                       tick_callback=None, tick_interval: int = 500):
        """Interpret batches until should_continue returns false or CPU stops."""
        if max_steps_per_batch <= 0 or tick_interval <= 0:
            raise ValueError('batch size and tick interval must be positive')
        total_steps = 0
        while should_continue() and not self.ebreak:
            for _ in range(max_steps_per_batch):
                if self.ebreak:
                    break
                self.step()
                total_steps += 1
                if tick_callback is not None and total_steps % tick_interval == 0:
                    tick_callback(total_steps)
        return total_steps

    def jit_stats(self):
        """Return JIT compilation statistics (for debugging/tuning)."""
        if hasattr(self, '_jit'):
            return self._jit.stats()
        return {'jit_compiled': 0, 'jit_cache_size': 0, 'block_cache_size': 0}

    def reset(self):
        self.pc = self._start_pc
        self.regs.reset()
        self._ldst = False
        self.ebreak = False
        # Clear JIT caches on reset (code may have changed)
        if hasattr(self, '_jit'):
            self._jit.jit_cache.clear()
            self._jit.block_runner.block_cache.clear()
            self._jit.hotness.clear()
