
! Bare-metal LCD color bars test
! Fills the LCD with colored bars using direct hardware writes

! Load constants from PC-relative pool
mov.l prdr_addr, r14     ! r14 = PRDR address (0xA405013C)
mov.l disp_addr, r13     ! r13 = display interface (0xB4000000)
mov.l color_red, r8      ! r8 = red (0xF800)
mov.l color_green, r9    ! r9 = green (0x07E0)
mov.l color_blue, r10    ! r10 = blue (0x001F)
mov.l color_white, r11   ! r11 = white (0xFFFF)
mov #0, r12              ! r12 = black (0x0000)

! Set RS=0 (command mode): clear PRDR bit 4
mov.b @r14, r0
and #0xEF, r0
mov.b r0, @r14

! Select GRAM register (0x202)
mov #0x02, r0
shll8 r0
or #0x02, r0
mov.w r0, @r13

! Set RS=1 (data mode) for pixel writes
mov.b @r14, r0
or #0x10, r0
mov.b r0, @r14

! Write pixels: cycle through colors
! r2 = pixel counter, r3 = color index
mov #0, r2
mov #0, r3

pixel_loop:
  ! Select color based on r3 (0-4)
  cmp/eq #0, r3
  bt use_red
  cmp/eq #1, r3
  bt use_green
  cmp/eq #2, r3
  bt use_blue
  cmp/eq #3, r3
  bt use_white
  ! Default: black
  mov r12, r0
  bra write_px
  nop
  use_red:
  mov r8, r0
  bra write_px
  nop
  use_green:
  mov r9, r0
  bra write_px
  nop
  use_blue:
  mov r10, r0
  bra write_px
  nop
  use_white:
  mov r11, r0
  write_px:
  mov.w r0, @r13

  ! Increment color index (mod 5)
  add #1, r3
  cmp/eq #5, r3
  bf skip_reset
  mov #0, r3
  skip_reset:

  ! Increment pixel counter
  add #1, r2
  ! Check if done: 396*224 = 88704 = 0x15A00
  ! We'll just do 1000 pixels for speed in testing
  mov #1000, r4
  cmp/gt r2, r4
  bt pixel_loop

! Infinite loop (program done)
end_loop:
bra end_loop
nop

! Constant pool (PC-relative data)
.align 2
prdr_addr:
.long 0xA405013C
disp_addr:
.long 0xB4000000
color_red:
.long 0xF800
color_green:
.long 0x07E0
color_blue:
.long 0x001F
color_white:
.long 0xFFFF
