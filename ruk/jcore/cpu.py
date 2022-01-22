from typing import Union

from ruk.jcore.disassembly import Disassembler
from ruk.jcore.emulator import Emulator
from ruk.jcore.memory import MemoryMap


class Register:
    """
    Simple SH4 register model
    """
    def __init__(self):
        # Actual register table
        self._regs = {
            'r0': 0x0,
            'r1': 0x0,
            'r2': 0x0,
            'r3': 0x0,
            'r4': 0x0,
            'r5': 0x0,
            'r6': 0x0,
            'r7': 0x0,
            'r8': 0x0,
            'r9': 0x0,
            'r10': 0x0,
            'r11': 0x0,
            'r12': 0x0,
            'r13': 0x0,
            'r14': 0x0,
            'r15': 0x0,
            'pr': 0x0,
            'sr': 0x0,
            'gbr': 0x0,
            'vbr': 0x0,
            'mach': 0x0,
            'macl': 0x0,
        }

    def __getitem__(self, key: Union[int, str]) -> int:
        """
        Helper method to access items
        >>> r = Register()
        >>> print(r[0])
        >>> print('r0')
        :param key: Index of the register (0 to 15) or string name.
        Valid names includes pc, pr, sr, gbr, vbrn mach and macl
        :return: int value
        :raise IndexError: key is not valid
        """
        # Numeric access
        if type(key) == int and 0 <= int(key) <= 15:
            return self._regs[f'r{key}']
        # Name access
        elif type(key) == str:
            key = key.lower()
            if key in self._regs:
                return self._regs[key]
        raise IndexError("Index is not a valid register")

    def __setitem__(self, key: Union[int, str], value: int) -> int:
        """
        >>> r = Register()
        >>> r[0] = 15
        >>> r['r0'] = 15
        Helper to set an item
        :param key: Index of the register (0 to 15) or string name.
        :param value: int value
        :return: int value (the one set)
        :raise IndexError: key is not valid
        """
        # Numeric access
        if type(key) == int and 0 <= int(key) <= 15:
            self._regs[f'r{key}'] = value
            return value
        elif type(key) == str:
            key = key.lower()
            if key in self._regs:
                self._regs[key] = value
                return value
        raise IndexError("Index is not a valid register")

    def __str__(self) -> str:
        return "Register{" + ', '.join([f'{i}: {self._regs[i]:02X}' for i in self._regs])+"}"

    def dump(self) -> None:
        """
        Dump every registers and print them
        """
        regs = list(self._regs)

        col = 4
        extra = len(regs) % col

        print('\n'.join([
            '\t'.join([f'{r:<4} = {self._regs[r]:02X}' + ('\t' if abs(self._regs[r]) <= 0xff else '') for r in i])
            for i in zip(*[iter(regs)]*col)
        ]),
            end='\n' + '\t'.join(
                [f'{r:<4} = {self._regs[r]:02X}' + ('\t' if abs(self._regs[r]) <= 0xff else '') for r in regs[-extra:]]) + '\n'
        )


class CPU:
    """
    Simple SH4 CPU model
    """
    def __init__(self, mem: MemoryMap, start_pc: int, *, debug=False):
        self.ebreak = False
        self.debug = debug
        self.pc = start_pc

        self.mem = mem
        self.regs = Register()
        self.emulator = Emulator(self)
        self.disassembler = Disassembler(debug=debug)

    def step(self):
        try:
            ins = self.mem.read16(self.pc)
            op, args = self.disassembler.disasm(int.from_bytes(ins, "big"))

            callback = self.emulator.resolve(op)
            callback(*args)
        except IndexError:
            self.ebreak = True
            if self.debug:
                raise

        # self.ebreak = True

    def stacktrace(self):
        self.regs.dump()
        print(f"{'pc':<4} = {self.pc:02X}")
        self.ebreak = True
