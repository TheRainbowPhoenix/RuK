"""Cached interpreter for HH3 workloads requiring the interpreter's handlers."""
from ruk.jcore.jit import BlockRunner


def run_cached(cpu, max_steps):
    """Run at most max_steps top-level instructions, including host call stubs.

    Delayed branch handlers execute their slots, as they do in CPU.step().
    Unlike the JIT this path does not inline guest loops or stop at a tight
    loop whose registers are still making progress.
    """
    runner = BlockRunner(cpu)
    cache = runner.block_cache
    steps = 0
    next_tick = 512
    while steps < max_steps and not cpu.ebreak and cpu.pc != 0xffffffff:
        pc = cpu.pc
        ops = cache.get(pc)
        if ops is None:
            ops = runner._compile_block(pc)
            cache[pc] = ops
        if not ops:
            cpu.step()
            steps += 1
        else:
            for handler, args in ops:
                if steps >= max_steps or cpu.ebreak or cpu.pc == 0xffffffff:
                    break
                handler(*args)
                steps += 1
                cpu._step_count += 1
        if steps >= next_tick:
            if cpu.on_step is not None:
                cpu.on_step(cpu._step_count)
            next_tick = steps + 512
    return steps
