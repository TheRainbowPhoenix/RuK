"""Interpreter runner for HH3 workloads."""


def run_cached(cpu, max_steps):
    """Run at most max_steps top-level instructions, including host call stubs.

    Delayed branch handlers execute their slots, as they do in CPU.step().
    Unlike the JIT this path does not inline guest loops or stop at a tight
    loop whose registers are still making progress.
    """
    steps = 0
    while steps < max_steps and not cpu.ebreak and cpu.pc != 0xffffffff:
        cpu.step()
        steps += 1
    return steps
