
mov.l prdr_addr, r14
mov.l disp_addr, r13

! Exit sleep mode (0x11)

    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #17, r0
    mov.w r0, @r13
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

! Display on (0x29)

    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #41, r0
    mov.w r0, @r13
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

! Set column address (0x2A): start=0, end=359
! 4 params: XS_high=0, XS_low=0, XE_high=1, XE_low=0x67

    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #42, r0
    mov.w r0, @r13
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

mov #0, r0
mov.w r0, @r13
mov #0, r0
mov.w r0, @r13
mov #1, r0
mov.w r0, @r13
mov #0x67, r0
mov.w r0, @r13

! Set page address (0x2B): start=0, end=639
! 4 params: YS_high=0, YS_low=0, YE_high=2, YE_low=0x7F

    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #43, r0
    mov.w r0, @r13
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

mov #0, r0
mov.w r0, @r13
mov #0, r0
mov.w r0, @r13
mov #2, r0
mov.w r0, @r13
mov #0x7F, r0
mov.w r0, @r13

! Write memory start (0x2C) - subsequent writes go to GRAM

    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #44, r0
    mov.w r0, @r13
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

mov #0x01, r7
shll8 r7
mov #0x68, r0
or r0, r7
mov #5, r8
shll2 r8
shll2 r8
shll2 r8
shll r8

mov #0, r2
row_loop2:
mov #0, r3
col_loop2:
mov r2, r0
add r3, r0
and #0x1F, r0
shll8 r0
shll2 r0
shll2 r0
shll r0
mov.w r0, @r13
add #1, r3
cmp/ge r7, r3
bf col_loop2
add #1, r2
cmp/ge r8, r2
bf row_loop2
bra end2
nop
end2:
! bra end2
nop

.align 2
prdr_addr: .long 0xA405013C
disp_addr: .long 0xB4000000
