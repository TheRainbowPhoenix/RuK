#!/usr/bin/env python3

from ruk.classpad import Classpad

rom = b'\x6E\xF3\x6E\x13\x6A\x13\x6F\x13\x60\x13\x60\x03\x74\x01'


if __name__ == '__main__':
    cp = Classpad(rom, debug=True)

    cp.run()