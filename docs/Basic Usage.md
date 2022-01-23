# Using the RuK Core
For now, RuK is still in early alpha. You can get some code running by placing it on a python `byte` string and calling it, like the following:
````python
from ruk.classpad import Classpad

rom = b'\xE1\x01\x71\x01'

cp = Classpad(rom, debug=True)
cp.run()
````

You would get some error, since the code didn't end, but you can watch the verbose output :
````
mov #h'0001 r1
01 -> R1
add #h'0001, r1
R1 += 01
!!! CPU Error : Unknown OPCode : 00 !!!
r0   = 00		r1   = 02		r2   = 00		r3   = 00	
r4   = 00		r5   = 00		r6   = 00		r7   = 00	
r8   = 00		r9   = 00		r10  = 00		r11  = 00	
r12  = 00		r13  = 00		r14  = 00		r15  = 00	
pr   = 00		sr   = 00		gbr  = 00		vbr  = 00	
mach = 00		macl = 00	
pc   = 80000004
````

Understanding its content, we can see the following:
````
mov #h'0001 r1
01 -> R1
````
Which is the `E1 01` instruction being interpreted as `mov #h'0001 r1` and the pseudocode linked `01 -> R1` or literally "Put 1 into R1".

Then, the CPU execute its next step :
````
add #h'0001, r1
R1 += 01
````
Which is the `71 01` instruction being interpreted as `add #h'0001, r1` and the pseudocode linked `R1 += 01` or literally "Increment R1 by 1".

Then, since the memory is filled of "`00`" when initialized, the cpu step to the next operation and read "`00 00`" which isn't valid OPCode, nor implemented ATM.
It'll then trigger an exception with "Unknown OPCode" and dump the CPU memory, showing us that R1 is set at value 2.

## Future plans
For now, it's very limited and can't run any serious programs, but it's planned to get almost every OPCode builtin and maybe some cool GUI debugger !

One major milestone would be to get some IO working like some screen or keyboard with DMA (direct memory access).

