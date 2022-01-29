from binascii import unhexlify

# Dumb but works :tm:
with open("all_opcodes.bin", "wb+") as f:
    for i in range(0xffff):
        f.write(unhexlify(f'{i:04x}'))