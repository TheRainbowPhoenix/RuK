from ruk.classpad import Classpad
from ruk.gui.window import DebuggerWindow

rom = b"\xe3\x01t\x0147\x8b\x18\xe1\x024\x17\x8b\x13\xe0\x034\x07\x8b\x10\xe2\x044'\x8b\r\xe1\x054\x17\x8b\n\xe0\x064\x07\x8b\x07\xe2\x074'\x8b\x04\xe1\x084\x17\x8b\x01\xe0\t4\x07\xa0\x01\xe4e\xe4\n\x00\x0b`C"

if __name__ == '__main__':
    cp = Classpad(rom, debug=True)
    dbg_win = DebuggerWindow()
    dbg_win.attach(cp)
    dbg_win.show()

    # TODO: run trigger cp.run()
    # cp.run()