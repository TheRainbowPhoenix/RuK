from ruk.jcore.cpu import Register, CPU
from ruk.jcore.disassembly import Disassembler
from ruk.jcore.memory import Memory, MemoryMap
from ruk.jcore.opcodes import opcodes_table, abstract_table


# mov r15, r14;
raw_asm = b'\x6E\xF3\x6E\x13\x6A\x13\x6F\x13\x60\x13\x60\x03'

disassembler = Disassembler(debug=True)

# for asm_op in [raw_asm[i * 2:(i + 1) * 2] for i in range(len(raw_asm) // 2)]:
#     disassembler.disasm(int.from_bytes(asm_op, "big"))

# mov = 0x6EF3
#
# disasm(mov)

"""
0x6EF3 = mov r15, r14; 
0x6E13 = mov r1,  r14;
0x6A13 = mov r1,  r10;
0x6F13 = mov r1,  r15;
0x6013 = mov r1,  r0;
0x6003 = mov r0, r0;

0x_N__ = register from
0x__N_ = register to
"""


r = Register()
r[15]= 0xff

# print(r)
# r.dump()

# RAM
ram = Memory(0x100_0000)

# ROM
rom = Memory(0x150_0000)

rom.write_bin(0, raw_asm)

memory = MemoryMap()
memory.add(0x8C00_0000, ram)
memory.add(0x8000_0000, rom)

# memory.add(0x8?00_0000, ScreenIO)
cpu = CPU(memory, start_pc=0x8000_0000, debug=True)
cpu.regs[15] = 0xff
cpu.regs[1] = 0x7f
print(cpu.regs)

while not cpu.ebreak:
    try:
        cpu.step()
    except Exception as e:
        print(f"!!! CPU Error : {e} !!!")
        cpu.stacktrace()
        raise

print(cpu.regs)
