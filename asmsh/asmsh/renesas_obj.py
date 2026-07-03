from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


ELF_MAGIC = b"\x7fELF"
SH_MACHINE = 0x2A


@dataclass
class ElfSection:
    name: str
    sh_type: int
    flags: int
    addr: int
    offset: int
    size: int
    link: int
    info: int
    addralign: int
    entsize: int
    data: bytes


@dataclass
class ElfSymbol:
    name: str
    value: int
    size: int
    info: int
    other: int
    shndx: int


@dataclass
class ElfRelocation:
    offset: int
    symbol: str
    symbol_index: int
    reloc_type: int
    addend: int


@dataclass(frozen=True)
class Relocation:
    offset: int
    symbol: str
    reloc_type: int
    addend: int = 0


@dataclass
class RenesasObject:
    sections: list[ElfSection]

    def section(self, name: str) -> ElfSection | None:
        for section in self.sections:
            if section.name == name:
                return section
        return None

    def words(self, section_name: str = "P") -> list[str]:
        section = self.section(section_name)
        if section is None:
            return []
        data = section.data
        return [data[i : i + 2].hex().upper() for i in range(0, len(data) - 1, 2)]

    def symbols(self) -> list[ElfSymbol]:
        symtab = self.section(".symtab")
        strtab = self.section(".strtab")
        if symtab is None or strtab is None:
            return []

        def name_at(offset: int) -> str:
            if offset >= len(strtab.data):
                return ""
            end = strtab.data.find(b"\0", offset)
            if end < 0:
                end = len(strtab.data)
            return strtab.data[offset:end].decode("ascii", errors="replace")

        symbols: list[ElfSymbol] = []
        for i in range(0, len(symtab.data), 16):
            raw = symtab.data[i : i + 16]
            if len(raw) < 16:
                break
            st_name, value, size, info, other, shndx = struct.unpack(">IIIBBH", raw)
            symbols.append(ElfSymbol(name_at(st_name), value, size, info, other, shndx))
        return symbols

    def relocations(self, section_name: str = "P") -> list[ElfRelocation]:
        rela = self.section(f".rela{section_name}")
        if rela is None:
            return []
        symbols = self.symbols()
        relocs: list[ElfRelocation] = []
        for i in range(0, len(rela.data), 12):
            raw = rela.data[i : i + 12]
            if len(raw) < 12:
                break
            offset, info, addend = struct.unpack(">III", raw)
            symbol_index = info >> 8
            reloc_type = info & 0xFF
            symbol = symbols[symbol_index].name if symbol_index < len(symbols) else ""
            relocs.append(ElfRelocation(offset, symbol, symbol_index, reloc_type, addend))
        return relocs


def align(value: int, boundary: int) -> int:
    if boundary <= 1:
        return value
    return (value + boundary - 1) & ~(boundary - 1)


def read_renesas_object(path: Path) -> RenesasObject:
    data = path.read_bytes()
    if data[:4] != ELF_MAGIC or data[4] != 1 or data[5] != 2:
        raise ValueError(f"{path} is not an ELF32 big-endian object")
    header = struct.unpack(">16sHHIIIIIHHHHHH", data[:52])
    if header[2] != SH_MACHINE:
        raise ValueError(f"{path} is not a SuperH object: e_machine=0x{header[2]:x}")
    shoff = header[6]
    shentsize = header[11]
    shnum = header[12]
    shstrndx = header[13]
    raw_headers = [
        struct.unpack(">IIIIIIIIII", data[shoff + i * shentsize : shoff + (i + 1) * shentsize])
        for i in range(shnum)
    ]
    shstr = b""
    if 0 <= shstrndx < len(raw_headers):
        _, _, _, _, off, size, _, _, _, _ = raw_headers[shstrndx]
        shstr = data[off : off + size]

    def name_at(offset: int) -> str:
        if offset >= len(shstr):
            return ""
        end = shstr.find(b"\0", offset)
        if end < 0:
            end = len(shstr)
        return shstr[offset:end].decode("ascii", errors="replace")

    sections: list[ElfSection] = []
    for raw in raw_headers:
        name_off, sh_type, flags, addr, off, size, link, info, addralign, entsize = raw
        sections.append(
            ElfSection(
                name=name_at(name_off),
                sh_type=sh_type,
                flags=flags,
                addr=addr,
                offset=off,
                size=size,
                link=link,
                info=info,
                addralign=addralign,
                entsize=entsize,
                data=data[off : off + size] if sh_type != 8 else b"",
            )
        )
    return RenesasObject(sections)


def words_to_bytes(words: list[str]) -> bytes:
    return b"".join(int(word, 16).to_bytes(2, "big") for word in words)


def _strtab(strings: list[str]) -> tuple[bytes, dict[str, int]]:
    data = bytearray(b"\0")
    offsets = {"": 0}
    for text in strings:
        if text in offsets:
            continue
        offsets[text] = len(data)
        data.extend(text.encode("ascii") + b"\0")
    return bytes(data), offsets


def write_renesas_object(
    path: Path,
    words: list[str],
    source_name: str = "",
    section_name: str = "P",
    symbols: dict[str, int] | None = None,
    exports: set[str] | None = None,
    relocations: list[Relocation] | None = None,
) -> None:
    code = words_to_bytes(words)
    shstr, shn = _strtab([".symtab", ".strtab", ".shstrtab", section_name, f".rela{section_name}"])
    symbols = symbols or {}
    exports = exports or set()
    relocations = relocations or []
    local_names = sorted(name for name in symbols if name not in exports)
    export_names = sorted(exports)
    strtab, stn = _strtab([source_name, section_name, *local_names, *export_names])

    sym_entries = [
        ("", 0, 0, 0, 0, 0),
        (source_name, 0, 0, 4, 0, 0xFFF1),
        (section_name, 0, 0, 3, 0, 4),
    ]
    for name in local_names:
        sym_entries.append((name, symbols[name], 0, 0, 0, 4))
    for name in export_names:
        sym_entries.append((name, symbols.get(name, 0), 0, 0x10, 0, 4))
    sym_index = {name: i for i, (name, *_rest) in enumerate(sym_entries)}
    symtab = b"".join(
        struct.pack(">IIIBBH", stn.get(name, 0), value, size, info, other, shndx)
        for name, value, size, info, other, shndx in sym_entries
    )
    rela = b"".join(
        struct.pack(">III", reloc.offset, (sym_index[reloc.symbol] << 8) | reloc.reloc_type, reloc.addend & 0xFFFFFFFF)
        for reloc in relocations
    )

    offset = 52
    symtab_off = offset
    offset += len(symtab)
    strtab_off = offset
    offset += len(strtab)
    shstr_off = offset
    offset += len(shstr)
    code_off = align(offset, 4)
    offset = code_off + len(code)
    rela_off = align(offset, 4)
    offset = rela_off + len(rela)
    shoff = align(offset, 4)

    section_headers = [
        (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        (shn[".symtab"], 2, 0, 0, symtab_off, len(symtab), 2, 3 + len(local_names), 4, 16),
        (shn[".strtab"], 3, 0, 0, strtab_off, len(strtab), 0, 0, 1, 0),
        (shn[".shstrtab"], 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0),
        (shn[section_name], 1, 6, 0, code_off, len(code), 0, 0, 4, 0),
        (shn[f".rela{section_name}"], 4, 0, 0, rela_off, len(rela), 1, 4, 4, 12),
    ]
    header = struct.pack(
        ">16sHHIIIIIHHHHHH",
        b"\x7fELF\x01\x02\x01" + b"\0" * 9,
        1,
        SH_MACHINE,
        1,
        0,
        0,
        shoff,
        1,
        52,
        0,
        0,
        40,
        len(section_headers),
        3,
    )
    blob = bytearray(header)
    blob.extend(symtab)
    blob.extend(strtab)
    blob.extend(shstr)
    blob.extend(b"\0" * (code_off - len(blob)))
    blob.extend(code)
    blob.extend(b"\0" * (rela_off - len(blob)))
    blob.extend(rela)
    blob.extend(b"\0" * (shoff - len(blob)))
    for section_header in section_headers:
        blob.extend(struct.pack(">IIIIIIIIII", *section_header))
    path.write_bytes(bytes(blob))
