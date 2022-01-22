"""
JCore OPCodes

Base struct:
mask (binary)
name (str)
type (str)
"""
from typing import List, Tuple

opcodes_table: List[Tuple[int, str, int, int, Tuple[int, ...]]] = [
    # (id, name:str, mask:int, code:int, args: tuple
    (
        0, "mov r%d, r%d",
        0b1111_0000_0000_1111,
        0b0110_0000_0000_0011,
        (
            0b0000_0000_1111_0000,  # m
            0b0000_1111_0000_0000,  # n
        )
     )
]

abstract_table = [
    ("R%d -> R%d"),  # 0
]
