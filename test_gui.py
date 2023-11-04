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

    elf = ELFFile()
    elf.read("elfs/ifm.elf")
    rom = elf.P

    # Reading raw bytes
    # with open("elfs/rom_01.bin", 'rb') as f:
    #     rom = f.read()
    # with open("elfs/app_template_printf.bin", 'rb') as f:
    #     rom = f.read()
    #     start_pc = 0x8cff0000

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

    # Reading test opcodes file
    # with open("scratches/all_opcodes.bin", 'rb') as f:
    #     rom = f.read()

    cp = Classpad(rom, debug=True, start_pc=start_pc, ram_size=0x0f_0000)
    # cp.add_rom(bootrom, 0)
    # cp.add_rom(rom, start_pc)
    dbg_win = DebuggerWindow()
    dbg_win.attach(cp)
    dbg_win.show()

    # TODO: run trigger cp.run()
    # cp.run()