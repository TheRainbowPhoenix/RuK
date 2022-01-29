from io import BytesIO


class ELFFile:
    def __init__(self):
        self.abi_table = {
            0: 'SystemV',
            1: 'HP-UX',
            2: 'NetBSD',
            3: 'Linux',
            4: 'GNU Hurd',
            5: '??? (5)',
            6: 'Solaris',
            7: 'AIX',
            8: 'IRIX',
            9: 'FreeBSD',
            0x0A: 'Tru64',
            0x0B: 'Novell Modesto',
            0x0C: 'OpenBSD',
            0x0D: 'OpenVMS',
            0x0E: 'NoneStop Kernel',
            0x0F: 'AROS',
            0x10: 'Fenix OS',
            0x11: 'CloudABI',
            0x12: 'OpenVOS',
        }

        self.e_types = {
            0x00: "ET_NONE",
            0x01: "ET_REL",
            0x02: "ET_EXEC",
            0x03: "ET_DYN",
            0x04: "ET_CORE",
            0xFE00: "ET_LOOS",
            0xFEFF: "ET_HIOS",
            0xFF00: "ET_LOPROC",
            0xFFFF: "ET_HIPROC",
        }

        self._p_section = b''

        self.stream = None

    def read_section(self, addr=None):
        if addr is not None:
            self.stream.seek(addr)

        read_sz = 4 if self.EI_CLASS == 32 else 8

        return {
            'sh_name': int.from_bytes(self.stream.read(4), "big"),
            'sh_type': int.from_bytes(self.stream.read(4), "big"),
            'sh_flags': int.from_bytes(self.stream.read(read_sz), "big"),
            'sh_addr': int.from_bytes(self.stream.read(read_sz), "big"),
            'sh_offset': int.from_bytes(self.stream.read(read_sz), "big"),
            'sh_size': int.from_bytes(self.stream.read(read_sz), "big"),
            'sh_link': int.from_bytes(self.stream.read(4), "big"),
            'sh_info': int.from_bytes(self.stream.read(4), "big"),
            'sh_addralign': int.from_bytes(self.stream.read(read_sz), "big"),
            'sh_entsize': int.from_bytes(self.stream.read(read_sz), "big"),
        }

    def read(self, filename: str):
        with open(filename, "rb") as f:
            elf_bin = f.read()

        self.stream = BytesIO(elf_bin)

        self.read_headers()
        self.read_sections()

    def read_headers(self):
        self.EI_MAG = self.stream.read(4)
        assert self.EI_MAG == b'\x7FELF'

        self.EI_CLASS = 32 if self.stream.read(1) == b'\x01' else 64
        # print(self.EI_CLASS)

        self.EI_DATA = 'little' if self.stream.read(1) == b'\x01' else 'big'
        # print(self.EI_DATA)

        self.EI_VERSION = self.stream.read(1)
        # print(f'v{int.from_bytes(self.EI_VERSION, "big")}')


        self.EI_OSABI = self.abi_table[int.from_bytes(self.stream.read(1), "big")]
        # print(self.EI_OSABI)

        self.EI_ABIVERSION = self.stream.read(1)
        # print(f'abi {int.from_bytes(self.EI_ABIVERSION, "big")}')

        self.EI_PAD = self.stream.read(7)
        assert self.EI_PAD == b'\x00\x00\x00\x00\x00\x00\x00'


        self.e_type = self.e_types[int.from_bytes(self.stream.read(2), "big")]
        # print(self.e_type)

        self.e_machine = self.stream.read(2)
        # print(self.e_machine)

        MACHINE_SUPERH = b'\x00*'
        assert self.e_machine == MACHINE_SUPERH

        self.e_version = int.from_bytes(self.stream.read(4), "big")
        # print(self.e_version)


        read_sz = 4 if self.EI_CLASS == 32 else 8

        self.e_entry = int.from_bytes(self.stream.read(read_sz), "big")  # memory address of the entry point

        self.e_phoff = int.from_bytes(self.stream.read(read_sz), "big")  # start of the program header table

        self.e_shoff = int.from_bytes(self.stream.read(read_sz), "big")

        self.e_flags = int.from_bytes(self.stream.read(4), "big")  # custom read
        self.e_ehsize = int.from_bytes(self.stream.read(2), "big")  # size of the header, should be 52 for 32 bits
        self.e_phentsize = int.from_bytes(self.stream.read(2), "big")  # size of a program header table entry.
        self.e_phnum = int.from_bytes(self.stream.read(2), "big")  #  number of entries in the program header table
        self.e_shentsize = int.from_bytes(self.stream.read(2), "big")  # size of a section header table entry.
        self.e_shnum = int.from_bytes(self.stream.read(2), "big")  # number of entries in the section header table.
        self.e_shstrndx = int.from_bytes(self.stream.read(2), "big")  # index of the section header table entry that contains the section names.

    def print_headers(self):
        print(f'''
        e_entry: \t\t{self.e_entry}
        e_phoff: \t\t{self.e_phoff}
        e_shoff: \t\t{self.e_shoff}  \t(start of the section header table)
        e_flags: \t\t{self.e_flags}
        e_ehsize: \t\t{self.e_ehsize} == 52
        e_phentsize: \t{self.e_phentsize}
        e_phnum: \t\t{self.e_phnum}
        e_shentsize: \t{self.e_shentsize}  \t(size of a section header table entry)
        e_shnum: \t\t{self.e_shnum}  \t(number of entries in the section header table)
        e_shstrndx: \t{self.e_shstrndx}  \t\t(index of the section header table entry that contains the section names)
        ''')

    def read_sections(self):
        self.stream.seek(self.e_shoff)

        section_1 = self.read_section()
        p_section = self.read_section()

        # TODO: read all

        self.stream.seek(p_section['sh_offset'])
        self._p_section = self.stream.read(p_section['sh_size'])

    @property
    def P(self) -> bytes:
        return self._p_section


if __name__ == '__main__':
    elf = ELFFile()
    elf.read("elfs/17/00017.elf")
    print(elf.P)
