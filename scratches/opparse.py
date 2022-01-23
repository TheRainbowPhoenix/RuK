with open("Renesas SH Instruction Set Summary.html") as f:
    l = f.read()

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