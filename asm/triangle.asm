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

    ! RS=0, select GRAM (0x2C)
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #0x00, r0
    shll8 r0
    or #0x2C, r0
    mov.w r0, @r13

    ! RS=1 (data mode for pixels)
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14


    ! === BEGIN PROGRAM ===

    ! Pre-compute limits
    ! r7 = 360 (col limit)
    mov #0x01, r7
    shll8 r7
    mov #0x68, r0
    or r0, r7
    ! r8 = 640 (row limit) = 5 << 7
    mov #5, r8
    shll2 r8
    shll2 r8
    shll2 r8
    shll r8
    ! r9 = 180 (center column) = 90 << 1
    ! (can't use mov #0xB4, sign-extends to -76)
    mov #90, r9
    shll r9

    mov #0, r2
    row_loop3:
    mov #0, r3
    col_loop3:

    ! Check row < 600 (0x258 = 600 = 0x02 << 8 | 0x58)
    ! Can't use or #0x58, r1 (only works with R0)
    ! Build 600 in r10: 600 = 75 * 8 = 75 << 3
    mov #75, r10
    shll2 r10
    shll r10
    cmp/ge r10, r2
    bt outside

    ! half_width = row >> 4 (triangle gets wider toward bottom)
    mov r2, r5
    shlr2 r5
    shlr2 r5

    ! left_edge = 180 - half_width (r6)
    mov r9, r6
    sub r5, r6

    ! right_edge = 180 + half_width (r11, don't clobber r7)
    mov r9, r11
    add r5, r11

    ! Check col >= left_edge
    cmp/hs r6, r3
    bf outside

    ! Check col < right_edge
    cmp/ge r11, r3
    bt outside

    ! Inside triangle: gradient color
    ! red = (row >> 2) & 0xF8
    mov r2, r0
    shlr2 r0
    and #0xF8, r0
    shll8 r0
    ! green = (col >> 1) & 0xFC
    mov r3, r1
    shlr r1
    and #0xFC, r1
    or r1, r0
    ! blue = ((row + col) >> 3) & 0x1F
    mov r2, r1
    add r3, r1
    shlr2 r1
    shlr r1
    and #0x1F, r1
    or r1, r0
    bra write_px
    nop

    outside:
    mov #0, r0

    write_px:
    mov.w r0, @r13

    add #1, r3
    cmp/ge r7, r3
    bf col_loop3
    add #1, r2
    cmp/ge r8, r2
    bf row_loop3
    bra end3
    nop
    end3:
    ! bra end3
    nop


    !LCD_CONST_POOL 
    .align 2
    prdr_addr:
    .long 0xA405013C
    disp_addr:
    .long 0xB4000000