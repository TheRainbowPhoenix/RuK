from ruk.classpad import Classpad
from ruk.gui.window import DebuggerWindow

from ruk.tools.elf import ELFFile

# rom =

if __name__ == '__main__':
    # Reading some ELF, for testing
    # elf = ELFFile()
    # elf.read("elfs/17/00017.elf")
    # rom = elf.P

    # Reading raw bytes
    with open("elfs/rom_01.bin", 'rb') as f:
        rom = f.read()

    # Reading test opcodes file
    # with open("scratches/all_opcodes.bin", 'rb') as f:
    #     rom = f.read()

    cp = Classpad(rom, debug=True)
    dbg_win = DebuggerWindow()
    dbg_win.attach(cp)
    dbg_win.show()

    # TODO: run trigger cp.run()
    # cp.run()