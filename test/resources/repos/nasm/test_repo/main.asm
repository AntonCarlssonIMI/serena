; entry point of the test program

%include "macros.inc"

extern print_string

section .data
greeting: db "Hello, world!", 10, 0
farewell: db "Goodbye!", 10, 0
origin:
    istruc point
        at point.x, dq 0
        at point.y, dq 0
    iend

section .bss
counter: resq 1

section .text
global _start

_start:
    mov qword [counter], 3
.repeat:
    lea rdi, [greeting]
    call print_string
    dec qword [counter]
    jnz .repeat
    mov rax, [origin + point.y]
    call say_goodbye
    exit_process 0

; prints the farewell message
say_goodbye:
    lea rdi, [farewell]
    call print_string
    ret
