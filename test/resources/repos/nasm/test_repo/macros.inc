; shared constants and macros for the test program

%define SYS_WRITE 1
%define SYS_EXIT 60
STDOUT equ 1
FLAG_MARK equ 0x80

%macro write_stdout 2
    mov rax, SYS_WRITE
    mov rdi, STDOUT
    mov rsi, %1
    mov rdx, %2
    syscall
%endmacro

%macro exit_process 1
    mov rax, SYS_EXIT
    mov rdi, %1
    syscall
%endmacro

; layout of a two-dimensional point
struc point
    .x: resq 1
    .y: resq 1
endstruc
