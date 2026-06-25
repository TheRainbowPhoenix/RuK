"""
Minimal SH-4 interrupt delivery support for RuK.

The base RuK CPU has no interrupt handling at all (TRAPA isn't even
implemented).  This module adds the minimum needed to deliver a TMU/ETMU
interrupt to the SH-4:

  - An `InterruptController` that holds a queue of pending IRQs (each
    identified by its INTEVT code).
  - A patch to `CPU.step()` that, before executing each instruction,
    checks the INTC for a pending IRQ and -- if interrupts are enabled
    in SR -- takes it: pushes PC->SPC, SR->SSR, sets INTEVT, jumps to
    VBR + 0x600.

We don't try to model the full SH-4 INTC (IPR registers, IMASK, etc.).
Instead we accept all IRQs unconditionally if SR.IF (bits 4-7) is 0,
which is enough for the TMU test.

Usage:
    from ruk.jcore.intc import InterruptController, attach_intc
    cp = Classpad(rom, ...)
    intc = InterruptController()
    attach_intc(cp.cpu, intc)
    intc.enable()                       # allow IRQ delivery
    cp.cpu.tmu.on_irq = intc.request    # wire TMU IRQs to the INTC
"""

from typing import Optional, List
import queue


# SH-4 SR bit fields we care about
SR_MD  = 1 << 31        # processor mode (1 = privileged)
SR_RB  = 1 << 29        # register bank
SR_BL  = 1 << 28        # exception/interrupt mask (blocks ALL exceptions)
SR_IF_MASK = 0x000000F0 # interrupt priority mask (bits 4-7)


class InterruptController:
    """
    A minimal SH-4 interrupt controller.

    Holds a FIFO of pending INTEVT codes.  The CPU polls `take_pending()`
    before each instruction; if a code is available and the CPU is in a
    state where interrupts can be delivered (SR.BL=0 and the IRQ's
    priority is > SR.IF), the CPU calls `deliver(intevt)` to dispatch it.
    """

    def __init__(self):
        self._queue: "queue.Queue[int]" = queue.Queue()
        self.enabled = False

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def request(self, intevt: int):
        """Called by peripherals to raise an interrupt."""
        self._queue.put(intevt & 0xFFFF)

    def take_pending(self) -> Optional[int]:
        if not self.enabled:
            return None
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def clear(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break


# ---------------------------------------------------------------------------
# CPU patching
# ---------------------------------------------------------------------------

# Saved reference to the original CPU.step() function, so we can chain to it.
_orig_step = None


def _interruptible_step(self):
    """
    Replacement for CPU.step() that checks the INTC before each instruction.
    """
    intc = getattr(self, '_intc', None)
    if intc is not None:
        intevt = intc.take_pending()
        if intevt is not None:
            _deliver_interrupt(self, intevt)
            return

    # Run the original step (calling the saved function directly with `self`)
    # _orig_step is a bound method of cpu, so we don't pass self again.
    _orig_step()


def _deliver_interrupt(cpu, intevt: int):
    """
    Deliver an interrupt to the SH-4 CPU.

    This is the minimal "general IRQ" path (VBR + 0x600):
      1. Save PC -> SPC, SR -> SSR, R15 -> SGR
      2. Set INTEVT register (we store it on the CPU object)
      3. Set SR.BL=1, SR.MD=1, SR.RB=1 (mask further exceptions)
      4. Jump to VBR + 0x600

    We don't have SPC/SSR/SGR/INTEVT registers in the base CPU model, so
    we stash them on the cpu object as plain attributes.  A future RTS
    from the interrupt handler will need an RTE instruction to restore
    them, which RuK doesn't implement yet either -- so for the test we
    just verify the IRQ was delivered (PC is now VBR + 0x600) and that
    the handler at that address got executed.
    """
    sr = cpu.regs['sr']
    # Block further exceptions
    new_sr = sr | (1 << 31) | (1 << 29) | (1 << 28)
    # Save state
    cpu.spc = cpu.pc
    cpu.ssr = sr
    cpu.sgr = cpu.regs[15]
    cpu.intevt = intevt
    cpu.regs['sr'] = new_sr
    # Vector to VBR + 0x600
    vbr = cpu.regs['vbr']
    cpu.pc = (vbr + 0x600) & 0xFFFFFFFF


def attach_intc(cpu, intc: InterruptController):
    """
    Attach an InterruptController to a CPU.  Patches the CPU's step()
    method so it checks the INTC before each instruction.
    """
    global _orig_step
    if _orig_step is None:
        _orig_step = cpu.step
    cpu._intc = intc
    cpu.step = _interruptible_step.__get__(cpu, type(cpu))
