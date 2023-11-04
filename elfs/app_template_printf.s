	.file	"main.cpp"
	.text
	.text
	.section	.rodata.str1.4,"aMS",@progbits,1
	.align 2
.LC0:
	.string	"HelloWorld"
	.text
	.align 1
	.global	_main
	.type	_main, @function
_main:
	sts.l	pr,@-r15	!,
! main.cpp:18:   Debug_PrintString("HelloWorld", 0);
	mov.l	.L3,r4	!,
	mov.l	.L4,r0	!, tmp163
	jsr	@r0	! tmp163
	mov	#0,r5	!,
! main.cpp:21: }
	lds.l	@r15+,pr	!,
	rts
	nop
.L5:
	.align 2
.L3:
	.long	.LC0
.L4:
	.long	_Debug_PrintString
	.size	_main, .-_main
	.global	_hollyhock_version
	.section	.hollyhock_version,"aw"
	.align 2
	.type	_hollyhock_version, @object
	.size	_hollyhock_version, 6
_hollyhock_version:
	.string	"1.0.2"
	.global	_hollyhock_author
	.section	.hollyhock_author,"aw"
	.align 2
	.type	_hollyhock_author, @object
	.size	_hollyhock_author, 8
_hollyhock_author:
	.string	"My name"
	.global	_hollyhock_description
	.section	.hollyhock_description,"aw"
	.align 2
	.type	_hollyhock_description, @object
	.size	_hollyhock_description, 30
_hollyhock_description:
	.string	"A short description of my app"
	.global	_hollyhock_name
	.section	.hollyhock_name,"aw"
	.align 2
	.type	_hollyhock_name, @object
	.size	_hollyhock_name, 12
_hollyhock_name:
	.string	"My app name"
	.ident	"GCC: (GNU) 10.1.0"
