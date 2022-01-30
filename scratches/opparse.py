with open("Renesas SH Instruction Set Summary.html") as f:
    l = f.read()

# archs
arch_e = l.split("col_cont_1\">")
arch_mk = [i.split('</div>')[0] for i in arch_e]

# Get all masks
mask_e = l.split("col_cont_4\">")
mask_mk = [i.split('</div>')[0] for i in mask_e]
mask_mk = mask_mk[1:]

# [i[4:8] for i in mask_mk]
# [i[8:12] for i in mask_mk]
# [i[4:] for i in mask_mk]

head_codes = [i[:4] for i in mask_mk]

# Get all ops
e = l.split("col_cont_2\">")
mk = [i.split('</div>')[0] for i in e]
mk = mk[1:]

# Find an index:
print(mk.index('bf	label'))

"""
HERE'S THE REAL COOL STUFF

THIS GENERATES OPCODE !!
"""

headers = """
from typing import List, Tuple, Dict

"""

opcodes_table = """
opcodes_table: List[Tuple[int, str, int, int, Dict[str, int]]] = [
    # (id, name:str, mask:int, code:int, args: dict{name:str, mask:int}
   """

abstract_table = """abstract_table = {
"""

index = -1
all_col = l.split('<div class="col_cont" ')[1:]
for col in all_col:
    index += 1
    if not 'SH4   ' in col:
        continue

    name = col.split('<div class="col_cont_2">')[1].split('</div>')[0] \
        .replace("Rn", "r{n:d}").replace("Rm", "r{m:d}") \
        .replace("disp", "0x{d:02x}").replace("imm", "h'{i:04x}") \
        .replace('\t', ' ').replace('&amp', '&').replace(",", ", ")\
        .replace("bf/s", "bf.s").replace("bt/s", "bt.s").replace("label", "0x{d:04x}")

    if name.startswith("f") or "FPUL" in name or "FPSCR" in name:
        # NO FPU !
        continue

    abstract = col.split('<div class="col_cont_3">')[1].split('</div>')[0] \
        .replace("Rn", "R{n:d}").replace("Rm", "R{m:d}") \
        .replace("disp", "R{d:d}").replace("imm", "h'{i:04x}") \
        .replace('\t', ' ').replace('\n', ' ')\
        .replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')

    abstract_table += f"{' ' * 4}{index}: \"{abstract}\",\n"

    mask_text = col.split('<div class="col_cont_4">')[1].split('</div>')[0]

    # id, name:str, mask:int, code:int, args: tuple

    mask = ''
    code = ''
    args = {}

    for x in 'nmid':
        if x in mask_text:
            args[x] = ''

    pos = -1
    for i in mask_text:
        pos += 1
        if pos % 4 == 0 and pos > 1:
            mask += '_'
            code += '_'
            for a in args:
                args[a] += '_'

        mask += '0' if i not in '01' else '1'
        code += '0' if i not in '01' else i
        for a in args:
            args[a] += '0' if i != a else '1'

    args_list = "\n".join([f"{' ' * 3 * 4}'{i}': 0b{args[i]},  # {i}" for i in args])

    opcodes_table += f""" (
        {index}, "{name}",
        0b{mask},
        0b{code},
        {{
{args_list}
        }}
    ),"""

    pass

opcodes_table += "\n]\n"

abstract_table += """
}\n"""

with open("generated_opcodes.py", "w+") as f:
    f.write(headers)
    f.write(opcodes_table)
    f.write("\n")
    f.write(abstract_table)
