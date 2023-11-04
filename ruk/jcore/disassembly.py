from typing import Tuple, List, Union, Any, Dict

from ruk.jcore.generated_opcodes import opcodes_table, abstract_table


class Disassembler:
    def __init__(self, debug=False):
        self.debug = debug

    def disasm(self, op, trace_only=False) -> Tuple[Union[int, str], Dict[str, int]]:
        """
        :param trace_only: Will only return the operation string. No action will be taken.
        """
        for opcode_struct in opcodes_table:
            op_id, fmt, mask, code, args_struct = opcode_struct

            args: Dict[str, int] = {}

            if op & mask == code:
                # Switching arg masks. Order's very important !
                for arg_name in args_struct:
                    arg_mask = args_struct[arg_name]

                    # arg mask is 0b1111_0000_0000
                    if arg_mask & 0b1111_1111 == 0:
                        args[arg_name] = ((op & arg_mask) >> 8)
                        continue

                    # arg mask is 0b1111_0000
                    if arg_mask & 0b1111_0000_1111 == 0:
                        args[arg_name] = ((op & arg_mask) >> 4)
                        continue

                    # arg_mask is 0b1111_1111 (i)
                    if arg_mask & 0b1111_0000_0000 == 0:
                        args[arg_name] = (op & arg_mask)
                        continue

                    # arg_mask is 0b1111_1111_1111 (i)
                    if arg_mask & 0b1111_0000_0000_0000 == 0:
                        args[arg_name] = (op & arg_mask)
                        continue

                    # arg_mask is 0b1111 (i)
                    if arg_mask & 0b1111_1111_0000 == 0:
                        args[arg_name] = (op & arg_mask)
                        continue

                    # Weirds ones
                    # arg_mask is 0b0111_0000
                    if arg_mask & 0b1111_1000_1111 == 0:
                        args[arg_name] = (op & arg_mask)
                        continue
                    #
                    # # arg_mask is 0b0111_0000
                    # if arg_mask & 0b0001_1111_1111 == 0:
                    #     args[arg_name] = ((op & arg_mask))
                    #     continue
                    #
                    # # arg_mask is 0b0111_0000
                    # if arg_mask & 0b0001_1111_1111 == 0:
                    #     args[arg_name] = ((op & arg_mask))
                    #     continue

                if trace_only:
                    return fmt, args

                fmt_args = {**args}
                if "d" in fmt_args:
                    fmt_args["d"] *= 4

                print(fmt.format(**fmt_args))

                if self.debug:
                    if min(abstract_table) <= op_id <= max(abstract_table):
                        print(abstract_table[op_id].format(**fmt_args))

                # if trace_only:
                return op_id, args
        raise IndexError(f"Unknown OPCode : {op:02X}")
