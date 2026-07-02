from ruk.tools.assembler import SH4Assembler

asm = SH4Assembler()
binary = asm.assemble("""
    AND #0xFC, r1
    nop
""")

print(binary)