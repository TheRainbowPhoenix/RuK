
    mov.l prdr_addr, r14
    mov.l disp_addr, r13

    ! RS=0, set H addr = 0 (reg 0x200)
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #0x02, r0
    shll8 r0
    mov.w r0, @r13

    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14
    mov #0, r0
    mov.w r0, @r13

    ! RS=0, set V addr = 0 (reg 0x201)
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #0x02, r0
    shll8 r0
    or #0x01, r0
    mov.w r0, @r13

    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14
    mov #0, r0
    mov.w r0, @r13

    ! RS=0, select GRAM (0x202)
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #0x02, r0
    shll8 r0
    or #0x02, r0
    mov.w r0, @r13

    ! RS=1 (data mode for pixels)
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

    ! Pre-compute loop limits ONCE before the loops
    ! r7 = 360 (col limit)
    mov #0x01, r7
    shll8 r7
    mov #0x68, r0
    or r0, r7
    ! r8 = 640 (row limit) = 0x280
    ! Can't use mov #0x80 (sign-extends to 0xFFFFFF80)
    ! Instead: 640 = 5 << 7 = 5 * 128
    mov #5, r8
    shll2 r8
    shll2 r8
    shll2 r8
    shll r8

    mov #0, r2

    row_loop:
    mov #0, r3

    col_loop:
    mov r2, r0
    and #0xF8, r0
    shll8 r0
    mov r3, r1
    and #0xFC, r1
    or r1, r0
    mov.w r0, @r13
    add #1, r3
    cmp/ge r7, r3
    bf col_loop
    add #1, r2
    cmp/ge r8, r2
    bf row_loop
    bra end
    nop
    end:
    bra end
    nop

    .align 2
    prdr_addr:
    .long 0xA405013C
    disp_addr:
    .long 0xB4000000
