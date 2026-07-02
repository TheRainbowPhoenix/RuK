"""
Tests for SectorC-SH4 with calling convention: function args, return values,
recursion (fibonacci, factorial), and comparison with expected behavior.

Tests:
  1. add(a, b) returns a+b
  2. fib(n) recursive fibonacci
  3. factorial(n) recursive
  4. sum_range(lo, hi) iterative
  5. Multiple return paths (if/return)
  6. Nested function calls
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from sectorc.sectorc import SectorC
from ruk.tools.assembler import assemble
from ruk.classpad import Classpad

ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cp400', '3070.bin')


def _make_classpad():
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()
    return Classpad(rom, debug=False, start_pc=0x8C000000,
                    with_display=True, with_touch=True)


def _compile_and_run(source, max_steps=50000):
    compiler = SectorC()
    asm = compiler.compile(source)
    try:
        binary = assemble(asm, start_addr=0x8C000000)
    except Exception as e:
        raise RuntimeError(f"Assembly failed:\n{asm}\nError: {e}")
    cp = _make_classpad()
    cp.ram.write_bin(0, binary)
    cp.cpu.pc = 0x8C000000
    for i in range(max_steps):
        cp.cpu.step()
        if cp.cpu.ebreak:
            break
    return cp, asm


def _read_global(cp, name, var_offsets):
    """Read a global variable from the Classpad's memory."""
    off = var_offsets[name]
    return cp.mem.read32(0x8C070000 + off)


class TestFunctionArgs(unittest.TestCase):
    """Test functions with arguments."""

    def test_add(self):
        """int add(int a, int b) { return a + b; }"""
        source = """
            int result;
            int add(int a, int b) {
                return a + b;
            }
            void main() {
                result = add(3, 4);
            }
        """
        cp, asm = _compile_and_run(source)
        # result is the first global variable
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 7, f"add(3,4) should be 7, got {result}")

    def test_subtract(self):
        """int sub(int a, int b) { return a - b; }"""
        source = """
            int result;
            int sub(int a, int b) {
                return a - b;
            }
            void main() {
                result = sub(10, 3);
            }
        """
        cp, _ = _compile_and_run(source)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 7, f"sub(10,3) should be 7, got {result}")

    def test_multiply(self):
        """int mul(int a, int b) { return a * b; }"""
        source = """
            int result;
            int mul(int a, int b) {
                return a * b;
            }
            void main() {
                result = mul(6, 7);
            }
        """
        cp, _ = _compile_and_run(source)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 42, f"mul(6,7) should be 42, got {result}")

    def test_three_args(self):
        """int add3(int a, int b, int c) { return a + b + c; }"""
        source = """
            int result;
            int add3(int a, int b, int c) {
                return a + b + c;
            }
            void main() {
                result = add3(1, 2, 3);
            }
        """
        cp, _ = _compile_and_run(source)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 6, f"add3(1,2,3) should be 6, got {result}")


class TestRecursion(unittest.TestCase):
    """Test recursive functions."""

    def test_fibonacci(self):
        """Recursive fibonacci: fib(10) = 55"""
        source = """
            int result;
            int fib(int n) {
                if (n <= 1) {
                    return n;
                }
                return fib(n - 1) + fib(n - 2);
            }
            void main() {
                result = fib(10);
            }
        """
        cp, _ = _compile_and_run(source, max_steps=500000)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 55, f"fib(10) should be 55, got {result}")

    def test_factorial(self):
        """Recursive factorial: fact(5) = 120"""
        source = """
            int result;
            int fact(int n) {
                if (n <= 1) {
                    return 1;
                }
                return n * fact(n - 1);
            }
            void main() {
                result = fact(5);
            }
        """
        cp, _ = _compile_and_run(source, max_steps=200000)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 120, f"fact(5) should be 120, got {result}")

    def test_fibonacci_base_cases(self):
        """fib(0) = 0, fib(1) = 1"""
        source = """
            int r0;
            int r1;
            int fib(int n) {
                if (n <= 1) {
                    return n;
                }
                return fib(n - 1) + fib(n - 2);
            }
            void main() {
                r0 = fib(0);
                r1 = fib(1);
            }
        """
        cp, _ = _compile_and_run(source, max_steps=50000)
        v0 = cp.mem.read32(0x8C070000)
        v1 = cp.mem.read32(0x8C070000 + 4)
        self.assertEqual(v0, 0, f"fib(0) should be 0, got {v0}")
        self.assertEqual(v1, 1, f"fib(1) should be 1, got {v1}")


class TestControlFlow(unittest.TestCase):
    """Test control flow with functions."""

    def test_sum_range(self):
        """Iterative sum: sum(1..5) = 15"""
        source = """
            int result;
            int sum_range(int lo, int hi) {
                int s;
                s = 0;
                while (lo <= hi) {
                    s = s + lo;
                    lo = lo + 1;
                }
                return s;
            }
            void main() {
                result = sum_range(1, 5);
            }
        """
        cp, _ = _compile_and_run(source, max_steps=50000)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 15, f"sum(1..5) should be 15, got {result}")

    def test_max(self):
        """int max(int a, int b) { if (a > b) return a; return b; }"""
        source = """
            int result;
            int max(int a, int b) {
                if (a > b) {
                    return a;
                }
                return b;
            }
            void main() {
                result = max(7, 3);
            }
        """
        cp, _ = _compile_and_run(source)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 7, f"max(7,3) should be 7, got {result}")

    def test_max_reversed(self):
        """max(3, 7) should be 7"""
        source = """
            int result;
            int max(int a, int b) {
                if (a > b) {
                    return a;
                }
                return b;
            }
            void main() {
                result = max(3, 7);
            }
        """
        cp, _ = _compile_and_run(source)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 7, f"max(3,7) should be 7, got {result}")


class TestNestedCalls(unittest.TestCase):
    """Test nested function calls."""

    def test_nested_add(self):
        """add(add(1, 2), add(3, 4)) = 10"""
        source = """
            int result;
            int add(int a, int b) {
                return a + b;
            }
            void main() {
                result = add(add(1, 2), add(3, 4));
            }
        """
        cp, _ = _compile_and_run(source, max_steps=50000)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 10, f"add(add(1,2),add(3,4)) should be 10, got {result}")

    def test_square(self):
        """square(x) = x * x via call"""
        source = """
            int result;
            int sq(int x) {
                return x * x;
            }
            void main() {
                result = sq(9);
            }
        """
        cp, _ = _compile_and_run(source)
        result = cp.mem.read32(0x8C070000)
        self.assertEqual(result, 81, f"sq(9) should be 81, got {result}")


class TestNoArgsFunctions(unittest.TestCase):
    """Test backward compatibility: void functions with no args."""

    def test_void_function(self):
        """void functions still work."""
        source = """
            int x;
            void set_x() {
                x = 42;
            }
            void main() {
                set_x();
            }
        """
        cp, _ = _compile_and_run(source)
        x = cp.mem.read32(0x8C070000)
        self.assertEqual(x, 42, f"x should be 42, got {x}")

    def test_simple_loop(self):
        """Simple while loop still works."""
        source = """
            int i;
            void main() {
                i = 0;
                while (i < 10) {
                    i = i + 1;
                }
            }
        """
        cp, _ = _compile_and_run(source, max_steps=5000)
        i = cp.mem.read32(0x8C070000)
        self.assertEqual(i, 10, f"i should be 10, got {i}")


if __name__ == '__main__':
    unittest.main()
