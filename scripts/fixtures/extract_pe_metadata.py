#!/usr/bin/env python3
"""Extract the PE fields Crash-Cap uses for code_id/debug_id.

This deliberately uses only the Python standard library. It reads the PE's
COFF timestamp, Optional Header SizeOfImage and CodeView RSDS record; it never
infers an ID from a filename or from a PDB path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


class PeError(ValueError):
    pass


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def require(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or offset + size > len(data):
        raise PeError(f"truncated {label}")


def rva_to_file_offset(data: bytes, sections: list[tuple[int, int, int, int]], rva: int) -> int:
    for virtual_address, virtual_size, raw_size, raw_pointer in sections:
        span = max(virtual_size, raw_size)
        if virtual_address <= rva < virtual_address + span:
            offset = raw_pointer + (rva - virtual_address)
            require(data, offset, 1, "RVA target")
            return offset
    raise PeError(f"RVA 0x{rva:X} is not in a section")


def parse_pe(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    require(data, 0, 0x40, "DOS header")
    if data[:2] != b"MZ":
        raise PeError("missing MZ signature")
    pe_offset = u32(data, 0x3C)
    require(data, pe_offset, 24, "PE header")
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise PeError("missing PE signature")

    coff = pe_offset + 4
    machine = u16(data, coff)
    section_count = u16(data, coff + 2)
    timestamp = u32(data, coff + 4)
    optional_size = u16(data, coff + 16)
    optional = coff + 20
    require(data, optional, optional_size, "Optional Header")
    magic = u16(data, optional)
    if magic == 0x20B:
        architecture = "x86_64"
        image_base = struct.unpack_from("<Q", data, optional + 24)[0]
        number_of_rva_and_sizes_offset = 108
        directories_offset = 112
    elif magic == 0x10B:
        architecture = "x86"
        image_base = u32(data, optional + 28)
        number_of_rva_and_sizes_offset = 92
        directories_offset = 96
    else:
        raise PeError(f"unsupported PE Optional Header, got 0x{magic:X}")
    size_of_image = u32(data, optional + 56)
    number_of_rva_and_sizes = u32(data, optional + number_of_rva_and_sizes_offset)
    directories = optional + directories_offset
    debug_rva = debug_size = 0
    if number_of_rva_and_sizes > 6:
        require(data, directories + 8 * 6, 8, "debug data directory")
        debug_rva = u32(data, directories + 8 * 6)
        debug_size = u32(data, directories + 8 * 6 + 4)

    sections = []
    section_table = optional + optional_size
    for index in range(section_count):
        section = section_table + 40 * index
        require(data, section, 40, "section header")
        sections.append(
            (
                u32(data, section + 12),
                u32(data, section + 8),
                u32(data, section + 16),
                u32(data, section + 20),
            )
        )

    codeview = None
    if debug_rva and debug_size >= 28:
        debug_offset = rva_to_file_offset(data, sections, debug_rva)
        count = debug_size // 28
        for index in range(count):
            entry = debug_offset + index * 28
            require(data, entry, 28, "debug directory")
            debug_type = u32(data, entry + 12)
            size_of_data = u32(data, entry + 16)
            pointer_to_raw_data = u32(data, entry + 24)
            if debug_type != 2 or size_of_data < 24:
                continue
            require(data, pointer_to_raw_data, size_of_data, "CodeView record")
            record = data[pointer_to_raw_data : pointer_to_raw_data + size_of_data]
            if record[:4] != b"RSDS":
                continue
            guid = record[4:20]
            age = struct.unpack_from("<I", record, 20)[0]
            guid_network = guid[0:4][::-1] + guid[4:6][::-1] + guid[6:8][::-1] + guid[8:16]
            codeview = {
                "signature": "RSDS",
                "guid": "{}-{}-{}-{}-{}".format(
                    guid_network[0:4].hex().upper(),
                    guid_network[4:6].hex().upper(),
                    guid_network[6:8].hex().upper(),
                    guid_network[8:10].hex().upper(),
                    guid_network[10:16].hex().upper(),
                ),
                "age": age,
                "debug_id": (guid_network.hex() + format(age, "x")).lower(),
            }
            break

    result: dict[str, object] = {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "machine": f"0x{machine:04X}",
        "architecture": architecture if machine in (0x8664, 0x014C) else "unknown",
        "time_date_stamp": f"0x{timestamp:08X}",
        "image_base": f"0x{image_base:016X}",
        "size_of_image": f"0x{size_of_image:X}",
        "code_id": f"{timestamp:08X}{size_of_image:X}",
        "codeview": codeview,
        "debug_id": codeview["debug_id"] if codeview else None,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = parse_pe(args.pe)
    except (OSError, PeError, struct.error) as exc:
        parser.error(str(exc))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
