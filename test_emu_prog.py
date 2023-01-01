from ruk.classpad import Classpad
from ruk.gui.window import DebuggerWindow

from ruk.tools.elf import ELFFile

# rom =

if __name__ == '__main__':
    start_pc = None
    # Reading some ELF, for testing
    # elf = ELFFile()
    # elf.read("elfs/17/00017.elf")
    # rom = elf.P

    # elf = ELFFile()
    # elf.read("elfs/ifm.elf")
    # rom = elf.P

    # Reading raw bytes
    with open("cp400/3070.bin", 'rb') as f:
        rom = f.read()

    """
    0xA0000000 to 0xA1FFFFFF - Cached
    0x80000000 to 0x81FFFFFF - Same, but non-cached
    Addins are executed from the ROM, with the executable code virtually mapped to 0x00300000 by the MMU.
    """
    # Reading actual bootrom
    # with open("elfs/bootrom_1511.bin", 'rb') as f:
    #     bootrom = f.read()
    #     start_pc = 0x0000_0000
    #     # start_pc = 0x8000_0340

    with open("cp400/print_HelloWorld_and_exit.bin", 'rb') as f:
        print_HelloWorld_and_exit = f.read()
        start_pc=0x8cff_0000

    # with open("cp400/print_HelloWorld_and_exit.hhk", 'rb') as f:
    #     print_HelloWorld_and_exit = f.read()
    #     start_pc = 0x8cff_0938  # entry0



    # Reading test opcodes file
    # with open("scratches/all_opcodes.bin", 'rb') as f:
    #     rom = f.read()

    cp = Classpad(rom, debug=True, start_pc=start_pc)
    # cp.add_rom(bootrom, 0)
    cp.ram.write_bin(0x8cff_0000 - 0x8C00_0000, print_HelloWorld_and_exit)
    # cp.add_rom(print_HelloWorld_and_exit, 0x8cff_0000)

    # r2 = 0xa44b000a
    # r3 = 0xffff
    # r14 = 0x178000
    # r15 = 0x178000

    # init = """
    # sts.l pr, @-r15
    # mov.l main_bootstrap_addr, r0
    # jsr @r0
    # nop
    # lds.l @r15+, pr
    # rts
    # nop
    # """
    # cp.cpu.regs[15] = cp.cpu.regs['pr']
    # cp.cpu.regs[0] = 0x8cff_0000

    dbg_win = DebuggerWindow()
    dbg_win.attach(cp)
    dbg_win.show()

    # TODO: run trigger cp.run()
    # cp.run()