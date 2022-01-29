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

all_masks = []

index = -1
all_col = l.split('<div class="col_cont" ')[1:]
for col in all_col:
    index += 1
    if not 'SH4   ' in col:
        continue

    name = col.split('<div class="col_cont_2">')[1].split('</div>')[0] \
        .replace("Rn", "R{n:d}").replace("Rm", "R{m:d}") \
        .replace("disp", "R{d:d}").replace("imm", "h'{i:04x}") \
        .replace('\t', ' ').replace('&amp', '&')

    if name.startswith("f") or "FPUL" in name or "FPSCR" in name:
        # NO FPU !
        continue

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

    # if mask not in all_masks:
    #     all_masks.append(mask)
    for a in args:
        if args[a] not in all_masks:
            all_masks.append(args[a])


print('\n'.join(all_masks))