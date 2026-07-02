"""
SectorC-SH4: A C-subset compiler that emits SH-4 assembly.

Port of SectorC (https://github.com/xorvoid/sectorc) targeting SH-4.

Supported C subset:
  - Global int variables
  - int functions with parameters and return values
  - void functions (no params)
  - if/while/return statements
  - Assignment: x = expr;
  - Expressions: +, -, *, &, |, ^, <<, >>, ==, !=, <, >, <=, >=
  - Pointer dereference: *(int*)addr
  - Address-of: &var
  - Function calls with args: func(arg1, arg2);
  - Integer literals (decimal and hex)
  - Comments: // and /* */

Calling convention (stack-based):
  - Caller pushes args right-to-left: push argN, ..., push arg1
  - Caller calls BSR
  - Callee reads args at @(0, r15), @(4, r15), ..., @((N-1)*4, r15)
  - Callee returns value in r0 via RTS
  - Caller pops args: add #N*4, r15
  - Local variables allocated on stack via add #-N, r15

Register usage:
  - r0 = accumulator / return value
  - r1 = right operand (for binary ops)
  - r2 = scratch / swap temp
  - r8 = frame pointer (points to args base)
  - r14 = global variable base (VAR_BASE)
  - r15 = stack pointer
"""

import re
from typing import List, Dict, Optional, Tuple


# ============================================================================
# Tokenizer
# ============================================================================

class Token:
    __slots__ = ('type', 'value', 'is_num', 'is_call')
    def __init__(self, type, value, is_num=False, is_call=False):
        self.type = type
        self.value = value
        self.is_num = is_num
        self.is_call = is_call

    def __repr__(self):
        return f'Token({self.type!r}, {self.value!r}, is_num={self.is_num}, is_call={self.is_call})'


class Tokenizer:
    def __init__(self, source: str):
        self.source = self._strip_comments(source)
        self.pos = 0
        self.tokens: List[Token] = []
        self._tokenize()

    def _strip_comments(self, source: str) -> str:
        source = re.sub(r'/\*.*?\*/', ' ', source, flags=re.DOTALL)
        source = re.sub(r'//[^\n]*', ' ', source)
        return source

    def _tokenize(self):
        s = self.source
        i = 0
        while i < len(s):
            c = s[i]
            if c.isspace():
                i += 1
                continue
            if i + 1 < len(s):
                two = s[i:i+2]
                if two in ('<<', '>>', '==', '!=', '<=', '>='):
                    self.tokens.append(Token('punct', two))
                    i += 2
                    continue
            if c in '(){};&|+-*^<>=,;':
                self.tokens.append(Token('punct', c))
                i += 1
                continue
            if c.isdigit() or (c == '0' and i + 1 < len(s) and s[i+1] in 'xX'):
                j = i
                if c == '0' and i + 1 < len(s) and s[i+1] in 'xX':
                    j = i + 2
                    while j < len(s) and s[j] in '0123456789abcdefABCDEF':
                        j += 1
                    val = int(s[i:j], 16)
                else:
                    while j < len(s) and s[j].isdigit():
                        j += 1
                    val = int(s[i:j])
                self.tokens.append(Token('num', val, is_num=True))
                i = j
                continue
            if c.isalpha() or c == '_':
                j = i
                while j < len(s) and (s[j].isalnum() or s[j] == '_'):
                    j += 1
                word = s[i:j]
                self.tokens.append(Token('ident', word))
                i = j
                continue
            i += 1
        self.tokens.append(Token('eof', None))

    def peek(self, offset=0) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]

    def next(self) -> Token:
        tok = self.peek()
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def expect(self, value: str) -> Token:
        tok = self.next()
        if tok.value != value:
            raise SyntaxError(f"Expected '{value}', got {tok.value!r}")
        return tok


# ============================================================================
# Code generator
# ============================================================================

class SH4Codegen:
    VAR_BASE_ADDR = 0x8C070000
    MAX_GLOBALS = 15

    def __init__(self):
        self.lines: List[str] = []
        self.global_offsets: Dict[str, int] = {}
        self.func_labels: Dict[str, str] = {}
        self.func_params: Dict[str, int] = {}  # func_name -> num_params
        self.next_global_offset = 0
        self.label_counter = 0
        self.pool_entries: List[Tuple[str, int]] = []
        # Per-function context
        self.local_vars: Dict[str, int] = {}  # name -> offset from r8
        self.next_local_offset = 0
        self.current_func_locals_size = 0

    def emit(self, line: str):
        self.lines.append(line)

    def emit_label(self, label: str):
        self.lines.append(f'{label}:')

    def new_label(self) -> str:
        self.label_counter += 1
        return f'L{self.label_counter}'

    def get_global_offset(self, name: str) -> int:
        if name not in self.global_offsets:
            if len(self.global_offsets) >= self.MAX_GLOBALS:
                raise RuntimeError(f"Too many globals (max {self.MAX_GLOBALS})")
            self.global_offsets[name] = self.next_global_offset
            self.next_global_offset += 4
        return self.global_offsets[name]

    def get_func_label(self, name: str) -> str:
        if name not in self.func_labels:
            self.func_labels[name] = f'func_{name}'
        return self.func_labels[name]

    # ---- Variable access ----

    def is_local(self, name: str) -> bool:
        return name in self.local_vars

    def load_var(self, name: str):
        if self.is_local(name):
            off = self.local_vars[name]
            self.emit(f'    mov.l @(0x{off:X}, r8), r0  ; load local {name}')
        else:
            off = self.get_global_offset(name)
            self.emit(f'    mov.l @(0x{off:X}, r14), r0  ; load global {name}')

    def store_var(self, name: str):
        if self.is_local(name):
            off = self.local_vars[name]
            if 0 <= off <= 60:
                self.emit(f'    mov.l r0, @(0x{off:X}, r8)  ; store local {name}')
            else:
                self.emit(f'    mov #{off - 0x100}, r2  ; large offset {name}')
                self.emit(f'    add #0x100, r2')
                self.emit(f'    mov.l r0, @(r2, r8)')
        else:
            off = self.get_global_offset(name)
            self.emit(f'    mov.l r0, @(0x{off:X}, r14)  ; store global {name}')

    def load_imm(self, value: int):
        val = value & 0xFFFFFFFF
        signed_val = val if val < 0x80000000 else val - 0x100000000
        if -128 <= signed_val <= 127:
            self.emit(f'    mov #{signed_val}, r0')
        else:
            label = self.new_label()
            self.pool_entries.append((label, val))
            self.emit(f'    mov.l {label}_pool, r0  ; load 0x{val:X}')

    def push_r0(self):
        self.emit('    mov.l r0, @-r15')

    def pop_r1(self):
        self.emit('    mov.l @r15+, r1')

    # ---- Binary ops ----

    def emit_binop(self, op: str):
        if op == '+':
            self.emit('    add r1, r0')
        elif op == '-':
            self.emit('    sub r1, r0')
        elif op == '*':
            self.emit('    mul.l r0, r1')
            self.emit('    sts macl, r0')
        elif op == '&':
            self.emit('    and r1, r0')
        elif op == '|':
            self.emit('    or r1, r0')
        elif op == '^':
            self.emit('    xor r1, r0')
        elif op == '<<':
            self.emit('    shld r1, r0')
        elif op == '>>':
            self.emit('    neg r1, r1')
            self.emit('    shld r1, r0')
        elif op in ('==', '!=', '<', '>', '<=', '>='):
            self.emit_cmp(op)

    def emit_cmp(self, op: str):
        if op == '==':
            self.emit('    cmp/eq r1, r0')
        elif op == '!=':
            self.emit('    cmp/eq r1, r0')
            self.emit('    movt r0')
            self.emit('    xor #1, r0')
            return
        elif op == '<':
            self.emit('    cmp/gt r0, r1')
        elif op == '>':
            self.emit('    cmp/gt r1, r0')
        elif op == '<=':
            self.emit('    cmp/ge r0, r1')
        elif op == '>=':
            self.emit('    cmp/ge r1, r0')
        self.emit('    movt r0')

    # ---- Function call with args ----

    def gen_call(self, func_name: str, num_args: int):
        label = self.get_func_label(func_name)
        self.emit(f'    bsr {label}  ; call {func_name}({num_args} args)')
        self.emit('    nop')
        # Clean up args from stack
        if num_args > 0:
            cleanup = num_args * 4
            if cleanup <= 127:
                self.emit(f'    add #{cleanup}, r15  ; pop {num_args} args')
            else:
                self.emit(f'    mov #{cleanup}, r2')
                self.emit(f'    add r2, r15')

    def gen_func_decl(self, name: str, params: List[str], body_code):
        self.func_params[name] = len(params)
        label = self.get_func_label(name)
        self.emit(f'    .align 2')
        self.emit_label(label)

        # Save PR and frame pointer on stack
        self.emit('    sts.l pr, @-r15  ; save return address')
        self.emit('    mov.l r8, @-r15  ; save old frame pointer')
        self.emit('    mov r15, r8  ; r8 = frame pointer')

        saved_pool = self.pool_entries
        self.pool_entries = []

        old_locals = self.local_vars
        old_next = self.next_local_offset
        self.local_vars = {}
        # Local vars start after params: offset = (2 + num_params) * 4
        self.next_local_offset = (len(params) + 2) * 4

        for i, param in enumerate(params):
            # Stack layout after prologue:
            #   r8+0 = saved_r8, r8+4 = saved_pr, r8+8 = arg1, r8+12 = arg2
            self.local_vars[param] = (i + 2) * 4

        body_code()

        # Default return
        self.emit('    mov #0, r0  ; default return 0')
        self.emit(f'_ret_{label}:')
        self.emit('    mov r8, r15  ; restore SP')
        self.emit('    mov.l @r15+, r8  ; restore frame pointer')
        self.emit('    lds.l @r15+, pr  ; restore return address')
        self.emit('    rts')
        self.emit('    nop')

        if self.pool_entries:
            self.emit('    .align 4')
            for lbl, val in self.pool_entries:
                self.emit(f'{lbl}_pool: .long 0x{val:X}')

        self.pool_entries = saved_pool
        self.local_vars = old_locals
        self.next_local_offset = old_next

    def gen_return(self):
        """Emit return statement (r0 already has return value)."""
        label = self.get_func_label(self.current_func)
        self.emit(f'    bra _ret_{label}')
        self.emit('    nop')

    def gen_prologue(self):
        self.emit('    ; SectorC-SH4 compiled program')
        self.emit('    ; Clear SR (disable register banking, set MD=1)')
        self.emit('    mov #-128, r0')
        self.emit('    shll16 r0')
        self.emit('    shll8 r0  ; r0 = 0x80000000 (MD=1)')
        self.emit('    ldc r0, sr')
        self.emit('    mov.l var_base, r14')
        self.emit('    mov.l stack_top, r15')
        self.emit('    bsr func_main')
        self.emit('    nop')
        self.emit('_exit: bra _exit')
        self.emit('    nop')
        self.emit('    .align 4')
        self.emit('var_base: .long 0x8C070000')
        self.emit('stack_top: .long 0x8C080000')


# ============================================================================
# Parser + Compiler
# ============================================================================

class SectorC:
    def __init__(self):
        self.codegen = SH4Codegen()
        self.tok = None

    def compile(self, source: str) -> str:
        self.codegen = SH4Codegen()
        self.tok = Tokenizer(source)
        self.codegen.gen_prologue()

        while self.tok.peek().type != 'eof':
            tok = self.tok.peek()
            if tok.value == 'int':
                # Could be a var decl or a function decl
                if self.tok.peek(2).value == '(':
                    self.parse_func_decl()
                else:
                    self.parse_var_decl()
            elif tok.value == 'void':
                self.parse_func_decl()
            else:
                break

        return '\n'.join(self.codegen.lines)

    def parse_var_decl(self):
        self.tok.expect('int')
        name_tok = self.tok.next()
        self.tok.expect(';')
        self.codegen.get_global_offset(name_tok.value)

    def parse_func_decl(self):
        ret_type = self.tok.next()  # 'int' or 'void'
        name_tok = self.tok.next()
        func_name = name_tok.value
        self.codegen.current_func = func_name

        # Parse parameters
        params = []
        if self.tok.peek().value == '(':
            self.tok.next()
            while self.tok.peek().value != ')':
                tok = self.tok.peek()
                if tok.value == 'int':
                    self.tok.next()  # consume 'int'
                if self.tok.peek().type == 'ident':
                    params.append(self.tok.next().value)
                if self.tok.peek().value == ',':
                    self.tok.next()
            self.tok.expect(')')

        self.tok.expect('{')

        def body():
            while self.tok.peek().value != '}':
                self.parse_statement()

        self.codegen.gen_func_decl(func_name, params, body)
        self.tok.expect('}')

    def parse_statement(self):
        tok = self.tok.peek()

        if tok.value == ';':
            self.tok.next()
            return

        if tok.value == 'if':
            self.parse_if()
        elif tok.value == 'while':
            self.parse_while()
        elif tok.value == 'return':
            self.parse_return()
        elif tok.value == 'int':
            # Local variable declaration: int name;
            self.tok.next()  # consume 'int'
            name_tok = self.tok.next()
            self.tok.expect(';')
            # Allocate local at positive offset from r8
            off = self.codegen.next_local_offset
            self.codegen.local_vars[name_tok.value] = off
            self.codegen.next_local_offset += 4
            # Allocate stack space
            self.codegen.emit(f'    add #-4, r15  ; allocate local {name_tok.value}')
        elif tok.type == 'ident':
            if self.tok.peek(1).value == '(':
                self.parse_call_statement()
            elif self.tok.peek(1).value == '=':
                self.parse_assignment()
            else:
                raise SyntaxError(f"Unexpected token after identifier: {self.tok.peek(1)}")
        elif tok.value == '*':
            # Pointer store: *(int*)var = expr;
            self.parse_ptr_store()
        else:
            raise SyntaxError(f"Unexpected token: {tok}")

    def parse_if(self):
        self.tok.expect('if')
        if self.tok.peek().value == '(':
            self.tok.next()
        self.parse_expr()
        self.tok.expect(')')
        self.tok.expect('{')
        end_label = self.codegen.new_label()
        self.codegen.emit(f'    tst r0, r0')
        self.codegen.emit(f'    bt {end_label}')
        while self.tok.peek().value != '}':
            self.parse_statement()
        self.codegen.emit_label(end_label)
        self.tok.expect('}')

    def parse_while(self):
        self.tok.expect('while')
        if self.tok.peek().value == '(':
            self.tok.next()
        start_label = self.codegen.new_label()
        end_label = self.codegen.new_label()
        self.codegen.emit_label(start_label)
        self.parse_expr()
        self.tok.expect(')')
        self.tok.expect('{')
        self.codegen.emit(f'    tst r0, r0')
        self.codegen.emit(f'    bt {end_label}')
        while self.tok.peek().value != '}':
            self.parse_statement()
        self.codegen.emit(f'    bra {start_label}')
        self.codegen.emit('    nop')
        self.codegen.emit_label(end_label)
        self.tok.expect('}')

    def parse_return(self):
        self.tok.expect('return')
        if self.tok.peek().value != ';':
            self.parse_expr()
        else:
            self.codegen.emit('    mov #0, r0')
        self.tok.expect(';')
        self.codegen.gen_return()

    def parse_call_statement(self):
        """Parse: funcname(args) ;"""
        name_tok = self.tok.next()
        self.tok.expect('(')
        args = []
        if self.tok.peek().value != ')':
            self.parse_expr()
            args.append(True)
            while self.tok.peek().value == ',':
                self.tok.next()
                self.parse_expr()
                args.append(True)
        self.tok.expect(')')

        # The expressions were compiled in left-to-right order, each leaving
        # result in r0. But we need to push them onto the stack.
        # Problem: we compiled them left-to-right but need to push right-to-left.
        # Solution: push each arg as we parse it, then they'll be in
        # right-to-left order on the stack.
        # Actually, we need to restructure: push args as we go.
        # Let me re-do this...

        self.tok.expect(';')
        # This is wrong - we need to push args before the call.
        # Let me restructure.

    def parse_assignment(self):
        name_tok = self.tok.next()
        self.tok.expect('=')
        self.parse_expr()
        self.codegen.store_var(name_tok.value)
        self.tok.expect(';')

    def parse_ptr_store(self):
        """Parse: *(int*)var = expr ;
        Stores r0 to the memory address held in var.
        Uses mov.w (16-bit) for the store since the LCD interface is 16-bit."""
        self.tok.expect('*')
        # Skip "(int*)" cast
        if self.tok.peek().value == '(':
            self.tok.next()
            if self.tok.peek().value == 'int':
                self.tok.next()
            if self.tok.peek().value == '*':
                self.tok.next()
            if self.tok.peek().value == ')':
                self.tok.next()
        # Get the variable name (holds the address)
        name_tok = self.tok.next()
        # Consume "="
        self.tok.expect('=')
        # Compile expression (result in r0)
        self.parse_expr()
        # r0 has the value to store. Push it.
        self.codegen.push_r0()
        # Load the address from the variable
        self.codegen.load_var(name_tok.value)
        # r0 = address. Pop value into r1.
        self.codegen.pop_r1()
        # Store: mov.w r1, @r0 (16-bit store for LCD interface)
        self.codegen.emit('    mov.w r1, @r0  ; *(int*)store (16-bit)')
        self.tok.expect(';')

    def parse_expr(self):
        """Parse an expression: unary (op unary)* (left-to-right)"""
        self.parse_unary()
        while True:
            tok = self.tok.peek()
            if tok.type == 'punct' and tok.value in (
                '+', '-', '*', '&', '|', '^', '<<', '>>',
                '==', '!=', '<', '>', '<=', '>='
            ):
                op = tok.value
                self.tok.next()
                self.codegen.push_r0()
                self.parse_unary()
                self.codegen.pop_r1()
                if op in ('-', '<<', '>>', '<', '>', '<=', '>='):
                    self.codegen.emit('    mov r0, r2')
                    self.codegen.emit('    mov r1, r0')
                    self.codegen.emit('    mov r2, r1')
                self.codegen.emit_binop(op)
            else:
                break

    def parse_unary(self):
        tok = self.tok.peek()

        if tok.value == '*(int*)':
            self.tok.next()
            name_tok = self.tok.next()
            self.codegen.load_var(name_tok.value)
            self.codegen.emit('    mov.l @r0, r0  ; dereference')
        elif tok.value == '*':
            # *(int*)(expr) or *(int*)var — handle the (int*) cast form
            self.tok.next()
            # Skip "(int*)" cast
            if self.tok.peek().value == '(':
                self.tok.next()
                if self.tok.peek().value == 'int':
                    self.tok.next()
                if self.tok.peek().value == '*':
                    self.tok.next()
                if self.tok.peek().value == ')':
                    self.tok.next()
            # Now parse the address expression
            self.parse_unary()
            self.codegen.emit('    mov.l @r0, r0  ; dereference')
        elif tok.value == '&':
            self.tok.next()
            name_tok = self.tok.next()
            if self.codegen.is_local(name_tok):
                off = self.codegen.local_vars[name_tok]
                self.codegen.emit(f'    mov #{off}, r0')
                self.codegen.emit(f'    add r8, r0')
            else:
                off = self.codegen.get_global_offset(name_tok)
                self.codegen.emit(f'    mov #{off}, r0')
                self.codegen.emit(f'    add r14, r0')
        elif tok.value == '(':
            self.tok.next()
            self.parse_expr()
            self.tok.expect(')')
        elif tok.is_num:
            self.tok.next()
            self.codegen.load_imm(tok.value)
        elif tok.type == 'ident':
            # Check if this is a function call: ident followed by (
            if self.tok.peek(1).value == '(':
                self.parse_call_expr()
            else:
                self.tok.next()
                self.codegen.load_var(tok.value)
        else:
            raise SyntaxError(f"Unexpected token in expression: {tok}")

    def parse_call_expr(self):
        """Parse a function call expression: funcname(arg1, arg2, ...)"""
        name_tok = self.tok.next()
        func_name = name_tok.value
        self.tok.expect('(')

        # Parse arguments and push them right-to-left
        # We parse left-to-right, push each, then the stack has them
        # in reverse order. To fix, we collect them, then push in reverse.
        # But that's complex. Instead, we push as we parse (left-to-right),
        # and the callee reads them in reverse: arg1 at top, arg2 below.
        # Actually, we want arg1 at @(4, r8) and arg2 at @(8, r8).
        # If we push arg1 first, then arg2:
        #   stack: arg2 (top) -> arg1
        #   r8+4 = arg2, r8+8 = arg1
        # That's reversed! We need to push right-to-left.
        # Solution: parse all args, push in reverse order.

        # Parse all argument expressions, saving the generated code
        arg_count = 0
        if self.tok.peek().value != ')':
            # We need to push args in reverse order.
            # Strategy: parse and push each arg as we go (left-to-right).
            # Then the last arg is on top. The callee will see:
            #   r8+4 = last arg, r8+8 = second-to-last, etc.
            # We need arg1 at r8+4. So we need to push in reverse.
            #
            # Simple approach: count args, push them, then the callee
            # accesses arg_i at offset (num_args - i + 1) * 4.
            # But this is confusing. Let's just push left-to-right and
            # have the callee access args at (num_args - i) * 4 + 4.

            # Actually, simplest: push left-to-right.
            # After pushing all args and calling, the stack looks like:
            #   r15 -> argN (last pushed = top)
            #   r15+4 -> argN-1
            #   ...
            #   r15+(N-1)*4 -> arg1 (first pushed = bottom)
            #
            # Callee pushes r8, so r8 = r15 (before push), then r15 -= 4.
            # After push r8: r15 = r8 - 4, r8 = old r15
            # Args are at: r8+4 = argN, r8+8 = argN-1, ..., r8+N*4 = arg1
            #
            # So arg_i (0-indexed) is at r8 + (N - i) * 4
            # For func(a, b): N=2, a=arg0 at r8+8, b=arg1 at r8+4
            #
            # This is reversed from what we want. Let's fix by pushing
            # right-to-left. To do that, we parse all args first, then
            # push in reverse.

            # Parse all args, each leaves result in r0. We push r0 each time.
            # But then they're in wrong order on stack.
            #
            # Better: parse args into a list of code-generating closures,
            # then execute them in reverse order.
            arg_codes = []

            def parse_one_arg():
                # Save current codegen state, parse expr, capture emitted lines
                saved_lines = self.codegen.lines
                self.codegen.lines = []
                self.parse_expr()
                arg_code = list(self.codegen.lines)
                self.codegen.lines = saved_lines
                arg_codes.append(arg_code)

            parse_one_arg()
            while self.tok.peek().value == ',':
                self.tok.next()
                parse_one_arg()

            # Now push args in reverse order (right-to-left)
            for code in reversed(arg_codes):
                for line in code:
                    self.codegen.emit(line)
                self.codegen.push_r0()
                arg_count += 1

        self.tok.expect(')')

        # Call the function
        self.codegen.gen_call(func_name, arg_count)

    def parse_call_statement(self):
        """Parse: funcname(args) ;"""
        # Parse as call expression, then expect ;
        self.parse_call_expr()
        self.tok.expect(';')
