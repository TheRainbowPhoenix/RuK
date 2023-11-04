#!/usr/bin/env python3

from ruk.classpad import Classpad


# mov.l	syscall_table, r2
# mov.l	syscall_id, r0

rom = b'\xD2\x02'   # mov.l   #off_80687CD0, r2  # off_801C7DD8 in fx9860
rom += b'\x40\x08'  # shll2   r0
rom += b'\x00\x2E'  # mov.l   @(r0,r2), r0
rom += b'\x40\x2B'  # jmp     @r0
rom += b'\x00\x09'  # nop
rom += b'\x00\x00'  # .data.b    0      .data.b    0
rom += b'\x80\x68'  # .data.l off_80687CD0  # off_801C7DD8 in fx9860
rom += b'\x7C\xD0'

from cg50.trapa import trapa

if __name__ == '__main__':
    # cp = Classpad(rom, debug=True)

    # Note, the "Address is unmapped : 0x0" is totally expected since
    # the cpu isn't supposed to halt after the previous code :D
    # cp.run()

    from ruk.gui.window import DebuggerWindow

    with open("cg50/3.60.bin", 'rb') as f:
        bootrom = f.read()
        # start_pc = 0x0000_0000
        start_pc = 0x8000_0340

    # start_pc = None
    cp = Classpad(bootrom, debug=True, start_pc=0x8002_0070)

    # mov.l	syscall_table, r2
    # mov.l	syscall_id, r0
    cp.cpu.regs[2] = 0x80020070  # syscall_table
    cp.cpu.regs[0] = 0x2  # syscall_id

    cp.add_rom(rom, 0x8002_0070, name="User ROM")
    cp.add_rom(trapa, 0x8068_7CD0, name="TrapA")

    dbg_win = DebuggerWindow()
    dbg_win.attach(cp)
    dbg_win.show()

