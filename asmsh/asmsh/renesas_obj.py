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


def write_renesas_object(path: Path, words: list[str], source_name: str = "", section_name: str = "P") -> None:
    code = words_to_bytes(words)
    shstr, shn = _strtab([".symtab", ".strtab", ".shstrtab", section_name, f".rela{section_name}"])
    strtab, stn = _strtab([source_name, section_name, "_start"])

    # Null, file, section, _start.
    symtab = b"".join(
        [
            struct.pack(">IIIBBH", 0, 0, 0, 0, 0, 0),
            struct.pack(">IIIBBH", stn.get(source_name, 0), 0, 0, 4, 0, 0xFFF1),
            struct.pack(">IIIBBH", stn[section_name], 0, 0, 3, 0, 3),
            struct.pack(">IIIBBH", stn["_start"], 0, 0, 0x10, 0, 3),
        ]
    )
    rela = b""

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
        (shn[".symtab"], 2, 0, 0, symtab_off, len(symtab), 2, 3, 4, 16),
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
