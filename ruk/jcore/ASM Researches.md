# J-Core ASM study
Some searches about asm, made from binary rom
## Common findings
> Take a look at [http://shared-ptr.com/sh_insns.html](http://shared-ptr.com/sh_insns.html) for more
 
- The 4 first bits are never used for variables
- Args `n` and `m` can take from 3 to 4 bits.  
- Args `d` and `i` can take up to 16 bits.

## ADD #h'N
```
0x71CC = add 0xCC, r1
0x7201 = add 0x01, r2
0x7401 = add 0x01, r4
0x7 = ADD
0x_N = register N
0x__XX = value
```


## BT
```
0x8923 = bt 0x080000a8; 
0x8900 = bt 0x08000062; 
0x8901 = bt 0x08000064;
0x8909 = bt 0x08000074;
0x8910 = bt 0x08000082;
0x8999 = bt 0x07ffff94; 
0x89BF = bt 0x07ffffe0;
0x89CE = bt 0x07fffffe;

0x89CF = bt 0x08000000;
0x89FF = bt 0x08000060; 
0x89FE = bt 0x0800005e; 
0x897F = bt 0x08000160; 
```

## MOV
```
0x6EF3 = mov r15, r14; 
0x6E13 = mov r1,  r14;
0x6A13 = mov r1,  r10;
0x6F13 = mov r1,  r15;
0x6013 = mov r1,  r0;
0x6003 = mov r0, r0;

0x_N__ = register from
0x__N_ = register to
```

MOV is related to length :
```
0x6001 = mov.w @r0, r0;
0x6002 = mov.l @r0, r0;
0x6003 = mov r0, r0;
0x6004 = mov.b @r0+, r0; 
0x6005 = mov.w @r0+, r0; 
0x6006 = mov.l @r0+, r0; 
```

## MOV #h'N
```
0xE054 = mov #h'54, r0 ;
       = mov 0x54, r0 ;
0xE1FF = mov 0xff, r1;

0xE7FF = mov #h'FFFFFFFF, r7
```

## BRA
```
0xA000 = bra 0x080000e6; 
0xA004 = bra 0x080000ee;
0xA9CE = bra 0x07fff482; 

0xAF8D = bt 0x08000000;
0xAF7F = bt 0x07ffffe4; 
```

Related : 
```
0x6007 = not r0, r0;

0x6008 = swap.b r0, r0; 
0x6009 = swap.w r0, r0; 

0x600A = negc r0, r0; 
0x600B = neg r0, r0; 
 
0x600C = extu.b r0, r0; 
0x600D = extu.w r0, r0; 
0x600E = exts.b r0, r0;  
0x600F = exts.w r0, r0;  
```

## MOV.B
```
0x8001 = mov.b r0, @(0x1,r0); 
0x8002 = mov.b r0, @(0x2,r0); 
...
0x800F = mov.b r0, @(0xF,r0);

0x801F = mov.b r0, @(0xF,r1);

0x810F = mov.w r0, @(0x1e,r0); 
```