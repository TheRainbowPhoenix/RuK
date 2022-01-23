#!/usr/bin/env python3

from ruk.classpad import Classpad

# rom = b'\x71\x7F\x74\x01\x73\x03\x73\x03' \
#       + b'\x34\x3c' \
#       + b'\x6E\xF3\x6E\x13\x6A\x13\x6F\x13\x60\x13\x60\x03'

#           iff.c     4    int main(int argc, char* argv) {
#           iff.c     5        int i = argc + 1 ;
#           iff.c     6        if (i > 1) {
rom = b'\xE3\x01'   # MOV         #1,R3
rom += b'\x74\x01'  # ADD         #1,R4
rom += b'\x34\x37'  # CMP/GT      R3,R4
rom += b'\x8B\x18'  # BF          L248
#           iff.c     7            if (i > 2) {
rom += b'\xE1\x02'  # MOV         #2,R1
rom += b'\x34\x17'  # CMP/GT      R1,R4
rom += b'\x8B\x13'  # BF          L249
#           iff.c     8                if (i > 3) {
rom += b'\xE0\x03'  # MOV         #3,R0
rom += b'\x34\x07'  # CMP/GT      R0,R4
rom += b'\x8B\x10'  # BF          L249
#           iff.c     9                    if (i > 4) {
rom += b'\xE2\x04'  # MOV         #4,R2
rom += b'\x34\x27'  # CMP/GT      R2,R4
rom += b'\x8B\x0D'  # BF          L249
#           iff.c    10                        if (i > 5) {
rom += b'\xE1\x05'  # MOV         #5,R1
rom += b'\x34\x17'  # CMP/GT      R1,R4
rom += b'\x8B\x0A'  # BF          L249
#           iff.c    11                            if (i > 6) {
rom += b'\xE0\x06'  # MOV         #6,R0
rom += b'\x34\x07'  # CMP/GT      R0,R4
rom += b'\x8B\x07'  # BF          L249
#           iff.c    12                                if (i > 7) {
rom += b'\xE2\x07'  # MOV         #7,R2
rom += b'\x34\x27'  # CMP/GT      R2,R4
rom += b'\x8B\x04'  # BF          L249
#           iff.c    13                                    if (i > 8) {
rom += b'\xE1\x08'  # MOV         #8,R1
rom += b'\x34\x17'  # CMP/GT      R1,R4
rom += b'\x8B\x01'  # BF          L249
#           iff.c    14                                        if (i > 9) {
rom += b'\xE0\x09'  # MOV         #9,R0
rom += b'\x34\x07'  # CMP/GT      R0,R4
#           iff.c    15                                            i = 109;
#                                  }    }   }   }   }   }   }   }
#           iff.c    24            i = 101;
rom += b'\xA0\x01'  # BRA         L257
rom += b'\xE4\x65'  # MOV         #101,R4
#    0000003A              L248:
#           iff.c    25        } else {
#           iff.c    26            i = 10;
rom += b'\xE4\x0A'  # MOV         #10,R4
#    0000003C              L257:
#           iff.c    27        }
#           iff.c    28        return i;
#           iff.c    29    }
rom += b'\x00\x0B'  # RTS
rom += b'\x60\x43'  # MOV         R4,R0

if __name__ == '__main__':
    cp = Classpad(rom, debug=True)

    # Note, the "Address is unmapped : 0x0" is totally expected since
    # the cpu isn't supposed to halt after the previous code :D
    cp.run()
