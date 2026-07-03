from __future__ import annotations

from .assembler import first_pass, parse_source, words_for
from .renesas_obj import words_to_bytes


def resolve_local_words(source_lines: list[str], listing_words: list[str], cpu: str) -> list[str]:
    parsed = parse_source(source_lines)
    labels = first_pass(parsed)
    resolved = list(listing_words)
    offset = 0
    for line in parsed:
        placeholder = words_for(line, labels, cpu, resolve_symbols=False)
        if not placeholder:
            continue
        local = words_for(line, labels, cpu, resolve_symbols=True)
        if len(local) != len(placeholder):
            raise ValueError(f"cannot patch variable-width line: {line.source.strip()}")
        if offset + len(local) > len(resolved):
            raise ValueError(f"listing ended before source line: {line.source.strip()}")
        for i, word in enumerate(local):
            resolved[offset + i] = f"{word:04X}"
        offset += len(placeholder)
    if offset != len(resolved):
        raise ValueError(f"source/listing word count mismatch: source={offset} listing={len(resolved)}")
    return resolved


def words_to_raw(words: list[str]) -> bytes:
    return words_to_bytes(words)
