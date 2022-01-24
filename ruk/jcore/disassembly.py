from typing import Tuple, List, Union, Any

from ruk.jcore.opcodes import opcodes_table, abstract_table


class Disassembler:
    def __init__(self, debug=False):
        self.debug = debug

    def disasm(self, op, trace_only=False) -> Tuple[Union[int, str], List[int]]:
        """
        :param trace_only: Will only return the operation string. No action will be taken.
        """
        for opcode_struct in opcodes_table:
            op_id, fmt, mask, code, args_struct = opcode_struct

            args: List[int] = []

            if op & mask == code:
                # Switching arg masks. Order's very important !
                for arg_mask in args_struct:

                    # arg mask is 0b1111_0000_0000
                    if arg_mask & 0b1111_1111 == 0:
                        args.append((op & arg_mask) >> 8)
                        continue

                    # arg mask is 0b1111_0000
                    if arg_mask & 0b1111_0000_1111 == 0:
                        args.append((op & arg_mask) >> 4)
                        continue

                    # arg_mask is 0b1111_1111 (i)
                    if arg_mask & 0b1111_0000_0000 == 0:
                        args.append((op & arg_mask))
                        continue

                if trace_only:
                    return fmt, tuple(args)
                print(fmt % tuple(args))

                if self.debug:
                    if min(abstract_table) <= op_id <= max(abstract_table):
                        print(abstract_table[op_id].format(*args))

                # if trace_only:
                return op_id, args
        raise IndexError(f"Unknown OPCode : {op:02X}")
