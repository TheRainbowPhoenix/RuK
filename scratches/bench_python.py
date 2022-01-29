import ctypes
import time

from struct import pack, unpack

class Bench:
    def __init__(self):
        self.r = {
            0: 0
        }
        self.PC = 0x7F

    def fun_pure(self, n: int, d: int):
        disp = (0x000000FF & d)
        self.r[n] = ((self.PC & 0xFFFFFFFC) + 4 + (disp << 2))

    def fun_c(self, n: int, d: int):
        disp = ctypes.c_uint32(0x000000FF & d)
        self.r[n] = ((self.PC & 0xFFFFFFFC) + 4 + (disp.value << 2))

    def fun_bytes(self, n: int, d: bytes):
        disp = bytes(x & y for x, y in zip(b'\x00\x00\x00\xff', d))
        self.r[n] = ((self.PC & 0xFFFFFFFC) + 4 + (unpack('l', disp)[0] << 2))


if __name__ == '__main__':
    bench = Bench()

    start = time.time()
    for i in range(0xFFFF):
        bench.fun_pure(0, i)
    end = time.time()
    print("Pure ", end - start)

    start = time.time()
    for i in range(0xFFFF):
        bench.fun_pure(0, i)
    end = time.time()
    print("CTypes ", end - start)

    start = time.time()
    for i in range(0xFFFF):
        bench.fun_bytes(0, pack('l', i))
    end = time.time()
    print("Bytes ", end - start)
