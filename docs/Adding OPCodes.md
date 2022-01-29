# Adding (implementing) OPCodes

## Getting the index
First, you'll need to get the "Renesas SH Instruction Set Summary.html", that can be found on the "scratches" folder.
You'll need the op index. You can do that with the following gist:
```python
with open("scratches/Renesas SH Instruction Set Summary.html") as f:
    l = f.read()

e = l.split("col_cont_2\">")
mk = [i.split('</div>')[0] for i in e]
mk = mk[1:]
```

Let's say you want to implement the "`bra	label`" OPCode, then query its index:
`mk.index('bra	label')`

That should return you "153".

## Creating the opcode entry
In the [`opcodes.py`](/ruk/jcore/opcodes.py) file, get to the `opcodes_table`.

Scroll till you find your index position and then add a tuple object.
Referring to the "bra" syntax, the code is `1010dddddddddddd`

Implementing the masking for it will look like the following :
````python
(
    153, "bra 0x%06x",
    0b1111_0000_0000_0000,
    0b1010_0000_0000_0000,
    (
        0b0000_1111_1111_1111,  # d
    )
),
````

Where:
````
(
    id, name:"bra 0x%06x" (used directly by format),
    mask:0b1111_0000_0000_0000,
    code:0b1010_0000_0000_0000,
    args: (
        0b0000_1111_1111_1111,  # d
    )
),
````
The "mask" is useful for OPCode detection: all the "1" bit will be AND'ed with the "code",
maching anything like "`0b1010_XXXX_XXXX_XXXX`"

Args is an array of bit masks for the extracted arguments. If you have two parameters like:
`0000nnnmmmm0000`, then the masks will be:
````python
args: (
        0b0000_0000_1111_0000,  # m
        0b0000_1111_0000_0000,  # n
)
````
Take care of preserving the order ! Otherwise the formating function will break

## Creating the abstract table entry (pseudocode)
Then, add an entry to the `abstract_table` in the same `opcodes.py` file. They'll be usefull in debug mode for easier reading

````python
abstract_table = {
    # ...
    153: "disp*2 + PC + 4 -> PC",
    # ...
}
````

The index should point to a string. If you have to add arguments, the use the "f-string format" syntax like so:
````python
abstract_table = {
    # ...
    0: "R{0:d} -> R{1:d}"
   # ...
}
````
Where `{0}` is the first var and `{1}` the second one. `:d` is used for formatting.

## Add an emulator entry
Then, we'll need to add an emulator entry. Go to the [`emulator.py`](/ruk/jcore/emulator.py) and locate the `self._resolve_table`.
Add an entry looking like :
````python
_resolve_table = {
    # ...
    153: self.bra
    # ...
}
````
Where `153` is the ID we're after and `self.bra` the emulation method we're about to create.

Next, add your method with the implementation:
````python
def bra(self, d: int):
    """
    disp*2 + PC + 4 -> PC
    :param d: label
    """
    disp: int = abs(d)
    pc = self.cpu.pc
    self.cpu.pc += 4 + (disp << 1)
    self.cpu.delay_slot(pc + 2)
    self.cpu.pc = self.cpu.regs['pr']
````


## Write unit testing
Finally, you can validate your code with some unit testing.

Get to the `tests/test_emulator.py`
````python
def test_bra(self):
    self.emu.cpu.regs['sr'] = 1
    self.emu.cpu.regs['pc'] = 0x80
    self.emu.cpu.pc = self.emu.cpu.regs['pc']
    disp = 1
    self.emu.bra(disp)

    self.emu.cpu.delay_slot.assert_called_once()
    self.emu.cpu.delay_slot.assert_called_with(0x80 + 2)
    self.assertEqual(self.emu.cpu.pc, 0x80 + 4 + disp*2)
````
