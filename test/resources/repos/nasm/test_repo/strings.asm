; string helpers

%include "macros.inc"

section .text
global string_length
global print_string
global count_char
global clear_mark

; returns in rax the length of the zero-terminated string at rdi
string_length:
    xor rax, rax
.next_char:
    cmp byte [rdi + rax], 0
    je .done
    inc rax
    jmp .next_char
.done:
    ret

; writes the zero-terminated string at rdi to stdout
print_string:
    push rdi
    call string_length
    pop rsi
    write_stdout rsi, rax
    ret

; returns in rax the number of occurrences of the byte in sil in the zero-terminated string at rdi
count_char:
    xor rax, rax
.next_char:
    mov dl, [rdi]
    test dl, dl
    jz .done
    cmp dl, sil
    jne .skip
    inc rax
.skip:
    inc rdi
    jmp .next_char
.done:
    ret

; clears the mark flag of the byte at rdi
; in: rdi; clobbers: nothing
clear_mark:
    and byte [rdi], ~FLAG_MARK
    ret
