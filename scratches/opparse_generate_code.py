with open("Renesas SH Instruction Set Summary.html") as f:
    l = f.read()

import re

"""
HERE'S THE REAL COOL STUFF

THIS GENERATES OPCODE !!
"""

headers = """import typing
if typing.TYPE_CHECKING:  # pragma: no cover
    from ruk.jcore.cpu import CPU

from ctypes import c_long

class Emulator:
    \"\"\"
    Simple python OPCodes emulator
    \"\"\"
    def __init__(self, cpu: 'CPU'):
        self.cpu = cpu
        self.debug = self.cpu.debug
        
        self._resolve_table = {
"""

mid = """        }

    def resolve(self, opcode_id: int) -> typing.Callable:
        \"\"\"
        Resolve opcode index in lookup table, getting the asm method from it.
        :param opcode_id: integer
        :return: self method
        \"\"\"
        if opcode_id in self._resolve_table:
            return self._resolve_table[opcode_id]
        raise IndexError(f"OPCode index \\"{opcode_id}\\" not resolved (did you added it to _resolve_table ?)")
    
    \"\"\"
    Emulates OpCodes (Generated)
    \"\"\"
    
"""

resolve_table = ""

impl_methods = ""

all_returns = []

index = -1
all_col = l.split('<div class="col_cont" ')[1:]
for col in all_col:
    index += 1
    if not 'SH4   ' in col:
        continue

    name = col.split('<div class="col_cont_2">')[1].split('</div>')[0] \
        .replace("Rn", "R{n:d}").replace("Rm", "R{m:d}") \
        .replace("disp", "R{d:d}").replace("imm", "h'{i:04x}") \
        .replace('\t', ' ').replace('&amp;', '&')

    if name.startswith("f") or "FPUL" in name or "FPSCR" in name:
        # NO FPU !
        continue

    abstract = col.split('<div class="col_cont_3">')[1].split('</div>')[0] \
        .replace('\t', ' ').replace('\n', ' ') \
        .replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')

    pre_code = col.split('<p class="precode">')[1].split('</p>')[0].replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')

    first_line = pre_code.split('\n')[0].replace('void ', '')
    fun_name = first_line.split()[0]

    args_l = [': '.join(i.replace('long', 'int').split()[::-1]) for i in
              first_line.split('(')[1].split(')')[0].split(",") if not 'void' in i]

    args = ''.join([f', {a}' for a in args_l])

    resolve_table += f"{' ' * 4 * 3}{index}: self.{fun_name},\n"

    descs = [abstract]
    code_lines = []

    # print('\n'.join(pre_code.split('\n')[1:]))

    skip_flag = False
    line_spacing = 0
    continue_spacing_flag = False
    for line in pre_code.split('\n')[1:]:
        line = line.strip()
        if line in '{}':
            continue

        if line.lstrip().startswith("#if"):
            if "SH4A" not in line:
                skip_flag = True
            else:
                skip_flag = False
                continue

        if line.lstrip().startswith("#elif"):
            if "SH4A" not in line:
                skip_flag = True
            else:
                skip_flag = False
                continue

        if line.lstrip().startswith("#endif"):
            skip_flag = False
            continue

        if skip_flag:
            continue

        if line == "PC += 2;":
            code_lines.append(f"{' ' * 4 * line_spacing}self.cpu.pc += 2")
            continue

        if re.match("R\[(n|m)\] = R\[(n|m)\];", line):
            code_lines.append(
                line.replace("R[n]", "self.cpu.regs[n]") \
                .replace("R[m]", "self.cpu.regs[m]").replace(';', ''))
            continue

        line = line.replace("Read_", "self.cpu.mem.read").replace("Write_", "self.cpu.mem.write")

        line = line.replace("R[n]", "self.cpu.regs[n]") \
            .replace("R[m]", "self.cpu.regs[m]")

        if line.startswith("if"):
            if "{" in line:
                continue_spacing_flag = True
                raise Exception("What to do ???")
            line += ":"
            if line_spacing > 0:
                line_spacing -= 1
            code_lines.append(f"# {' ' * 4 * line_spacing}{line}  # TODO")
            line_spacing += 1
            continue
        elif line == "else":
            if "{" in line:
                continue_spacing_flag = True
                raise Exception("What to do ???")
            line += ":"
            if line_spacing > 0:
                line_spacing -= 1
            code_lines.append(f"# {' ' * 4 * line_spacing}{line}  # TODO")
            line_spacing += 1
            continue

        if line.endswith(";"):
            line = line[:-1]

        if "PC" in line:
            line = line.replace("PC", "self.cpu.pc")
        if "GBR" in line:
            line = line.replace("GBR", "self.cpu.regs['gbr']")

        if "R[0]" in line:
            line = line.replace("R[0]", "self.cpu.regs[0]")

        if "Delay_Slot " in line:
            line = line.replace("Delay_Slot ", "self.cpu.delay_slot")

        # T = self.cpu.regs['sr']

        if ("(T == 0)") in line:
            line = line.replace("(T == 0)", "self.cpu.regs['sr'] == 0")

        if "(0xFFFFFF00 | d)" in line:
            line = line.replace("(0xFFFFFF00 | d)", "c_long(0xFFFFFF00 | d).value")

        print(line)


        code_lines.append(f"# {' ' * 4 * line_spacing}{line}  # TODO: generated")

        if line_spacing > 0 and not continue_spacing_flag:
            line_spacing -= 1

    print("\n")

    for arg in args_l:
        descs.append(
            f":param {arg}".replace("m: int", "m: register index (between 0 and 15)")
                .replace("n: int", "n: register index (between 0 and 15)")
                .replace("i: int", "i: value to add (up to 0xFF)")
                .replace("d: int", "d: disp")
        )

    # PC += 2;
    if len([i for i in code_lines if not "# TODO:" in i]) == 0:
        code_lines.append("pass  # TODO: Implement me !")

    impl_methods += f"""
    def {fun_name}(self{args}):
        \"\"\"
        {f"{chr(10)}{' ' * 4 * 2}".join(descs)}
        \"\"\"
        {f"{chr(10)}{' ' * 4 * 2}".join(code_lines)}
    """

with open("generated_emulator.py", "w+") as f:
    f.write(headers)
    f.write(resolve_table)
    f.write(mid)
    f.write(impl_methods)
    f.write("\n")
