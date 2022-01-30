# Memory regions

## 0x0000_0000
Bootrom loaded here :
````
DF 1E D4 1F  44 0E D1 1F
E5 00 D4 1F  E7 10 D2 1F
47 18 DE 1F  E6 FF 21 22
24 52 E5 08  14 74 E7 A0
47 18 14 66  47 28 45 18
1E 53 07 E3  E1 04 D3 19
43 0B 2E 12  D3 18 43 0B
00 09 D3 18  43 0B 00 09
52 E5 60 2D  20 08 89 06
88 20 89 08  96 15 30 60
89 09 A0 0B  00 09 D2 12
D6 12 A0 07  22 62 D2 10
D6 11 A0 03  22 62 D2 0E
D6 10 22 62  D3 10 43 0B
00 09 AF FB  00 09 AF C3
70 00 00 F0  FE C1 00 00
A4 15 00 20  00 01 00 13
FF 00 00 10  A0 00 03 B8
A0 00 03 E2  A0 00 03 80
FD 80 0B 04  00 00 CA 00
00 00 CA 01  00 00 CA 02
A0 00 04 5E  00 00 00 00
..00
````

# 0x0000_0300
Bootloader, with `LV777`, then `CASIOABS` at 0x00003380

- 0x0ffe0000 -> Starting of a big program blob
- 0x0FFE0b00 "ELF" ??
- 0x0FFE1b00 -> "hollyhock", read *.bin and *.hhk
- (read only)

## 0x0C00_0000 -> 0x0??
`FF`'d area, with some `00 00 00 00`.


## 0x0???_???? -> 0x0EFF_FFFF 
 

## 0x0F00_000 -> 0x0F0A_4F00
`FF`'b blocks mostly, sometime `00` or `8C`
Get really repetitive like "FD DF" looping for 30 lines, so maybe pictures or gradient 

## 0x0F0A_5000 -> 0x0F0A_5900
Seems to be code (`2F 86` starting bloc)

## 0x0F0A_5900 -> 0x0F0A_6800
`00 00 00 00` and `FF FF FF FF` patterns, repeating 

## TODO : from 0x0F0A_6800 to 0x0FE0_0400
Seems to be a vast memory region.

## 0x0F0A_8A0E -> 0x0F0A_A311
`FF`'d region

## 0x0F0A_A312 ->
`00`'d region. Writing there trigger "address error"


## 0x0FE0_0400 -> 0x0FFE_0000 
Mostly `00`'b. Read Only.

##  -> 0x0FFE_FFFF
Writable sometimes, `00`'b

## 0x0FFF_0000 -> 0x0FFF_1510
Program (executable) blob bytes

## 0x0FFF_1510 -> 0x0FFF_FFFF
Memory of the Hex Editor
`0x0FFF15AA` => ">0FF..." (text prompt)

Read Only.

`00`'b 

## 0x0800_0000 -> 0x0BFF_FFFF
## 0x1000_0000 -> 0x1BFF_FFFF
Some of the bits keep changing, like a count. 
````
2E 2E 2E 2E  2E 2E 2E 2E
2E 2E 2E 2E  2E 2E 2E 2E
2E 2E 2E 2E  2E[2E 2E 2A] / [2A 2A 20]
2A 20 2A 20  20 00 20 00 / [???]

26 08 26 08  26 08 26 08
26 08 26 08  26 08 26 08
26 08 26 08  26 08 22 08
[20 08 20 08]  00 00 00 00 / [22 08] / [20 00]
(this 4 lines bloc repeats 7 times, change always on the same line but not synced)
````



## 0x1C00_0000 -> 0x7FXX_XXXX
(todo: find the actual end)
````
00 00 00 00  00 00 00 00
8C FF 14 OC  80 02 DB C8
8C FF 12 A8  8C FF 12 E8
8C FF 14 01  8C FF 15 CC
00 00 00 00  00 00 00 00
FF FF 00 00  FF FF FF FF
FF FF 00 00  FF FF FF FF
FF FF FF FF  FF FF FF FF
00 00 00 00  00 00 00 00
FF FF 00 00  FF FF FF FF
FF FF 00 00  FF FF FF FF
FF FF FF FF  FF FF FF FF
00 00 00 00  00 00 00 00
FF FF 00 00  FF FF FF FF
FF FF 00 00  FF FF FF FF
FF FF FF FF  FF FF FF FF
00 00 00 00  00 00 00 00
FF FF FF FF  FF FF FF FF
FF FF FF FF  FF FF FF FF
FF FF FF FF  FF FF FF FF
00 00 00 00  00 00 00 00
FF FF FF FF  FF FF FF FF
FF FF FF FF  FF FF FF FF
FF FF FF FF  FF FF FF FF
00 00 00 00  00 00 00 00
FF FF FF FF  FF FF FF FF
FF FF FF FF  FF FF FF FF
FF FF FF FF  FF FF FF FF
00 00 00 00  00 00 00 00
FF FF FF FF  FF FF FF FF
FF FF FF FF  FF FF FF FF
FF FF FF FF  FF FF FF FF
````

## 0xFEC0_0000 -> 0xFEFF_FFFF

Same reply repeated regardless the actual address.
Won't change on IDLE.
Move a lot on screen touch and keypress 
````
2E 2E 2E 2E  2E 2E 2E 2E
20 25 20 25  20 25 20 25 
00 00 00 00  00 00 00 00
(16 times more lines of 00)
FF FF FF FF  FF FF FF FF
00 00 00 00  00 00 00 00
(6 times more lines of 00)
FF FF FF FF  FF FF FF FF
(4 times more lines of FF)
````
