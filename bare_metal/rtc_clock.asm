
! RTC clock display test
! Reads R64CNT, RSECCNT, RMINCNT, RHRCNT from the RTC

mov.l rtc_base, r14     ! r14 = RTC base (0xA413FEC0)
mov.l result_addr, r15  ! r15 = result storage

! Read R64CNT (offset 0x00)
mov.b @r14, r0
mov.b r0, @r15
add #1, r15

! Read RSECCNT (offset 0x02)
mov #(0x02), r0
mov.b @(r0, r14), r1
mov.b r1, @r15
add #1, r15

! Read RMINCNT (offset 0x04)
mov #(0x04), r0
mov.b @(r0, r14), r1
mov.b r1, @r15
add #1, r15

! Read RHRCNT (offset 0x06)
mov #(0x06), r0
mov.b @(r0, r14), r1
mov.b r1, @r15

! Infinite loop
end:
bra end
nop

.align 2
rtc_base:
.long 0xA413FEC0
result_addr:
.long 0x8C003000
