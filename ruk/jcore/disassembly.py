from typing import Tuple, List, Union, Any

from ruk.jcore.opcodes import opcodes_table, abstract_table


class Disassembler:
    def __init__(self, debug=False):
        self.debug = debug

    def disasm(self, op) -> Tuple[int, List[int]]:
        for opcode_struct in opcodes_table:
            op_id, fmt, mask, code, args_struct = opcode_struct

            args: List[int] = []
            # Ugly but works...
            args_count = 0
            arg_0, arg_1, arg_2 = 0, 0, 0

            if op & mask == code:
                # if len(args_struct) == 2:
                #     arg_0 = op & args_struct[0] >>
                #     args_count+=1
                for arg_mask in args_struct:
                    if arg_mask & 0b1111_1111 == 0:
                        args.append((op & arg_mask) >> 8)
                        continue

                    if arg_mask & 0b1111 == 0:
                        args.append((op & arg_mask) >> 4)
                        continue

                print(fmt % tuple(args))

                if self.debug:
                    if 0 <= op_id < len(abstract_table):
                        print(abstract_table[op_id] % tuple(args))

                return op_id, args
        raise IndexError(f"Unknown OPCode : {op:02X}")