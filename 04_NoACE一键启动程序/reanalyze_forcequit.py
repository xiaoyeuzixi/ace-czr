"""
ForceQuitNotice re-analysis tool for updated game version.
Extracts the DLL from the new updatescript bundle, dumps IL for all
methods matching the ldfld; ldc.i4.1; bne.un.s; call pattern, and
generates a patched bundle if confirmed.

Usage:
  python reanalyze_forcequit.py [new_bundle_path]

Default new bundle path (from launcher log):
  %LOCALAPPDATA%\LocalLow\pi\超自然行动组\bundles\data\code\updatescript_500.dll.ab_u_a624426295f04443b448195052d3e304

Requirements: pip install lz4 dnfile dncil
"""

import hashlib
import io
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import lz4.block
except ImportError:
    print("ERROR: pip install lz4")
    sys.exit(1)
try:
    import dnfile
    from dncil.cil.body.reader import read_method_body_from_bytes
    from dncil.clr.token import Token
except ImportError:
    print("ERROR: pip install dnfile dncil")
    sys.exit(1)


# ── UnityFS Bundle I/O (from patch_force_quit_bundle.py) ──

@dataclass
class Block:
    uncompressed_size: int
    compressed_size: int
    flags: int


@dataclass
class Node:
    offset: int
    size: int
    flags: int
    path: str


@dataclass
class Bundle:
    signature: str
    version: int
    player_version: str
    engine_version: str
    flags: int
    info_hash: bytes
    blocks: list[Block]
    nodes: list[Node]
    data: bytearray


def read_cstring(stream: io.BufferedIOBase) -> str:
    value = bytearray()
    while True:
        current = stream.read(1)
        if not current:
            raise EOFError("unterminated string")
        if current == b"\0":
            return value.decode("utf-8")
        value.extend(current)


def write_cstring(stream: io.BufferedIOBase, value: str) -> None:
    stream.write(value.encode("utf-8") + b"\0")


def read_be(stream: io.BufferedIOBase, fmt: str):
    size = struct.calcsize(">" + fmt)
    value = stream.read(size)
    if len(value) != size:
        raise EOFError(f"expected {size} bytes, got {len(value)}")
    return struct.unpack(">" + fmt, value)[0]


def write_be(stream: io.BufferedIOBase, fmt: str, value) -> None:
    stream.write(struct.pack(">" + fmt, value))


def align_read(stream: io.BufferedIOBase, alignment: int) -> None:
    stream.seek((-stream.tell()) % alignment, os.SEEK_CUR)


def align_write(stream: io.BufferedIOBase, alignment: int) -> None:
    stream.write(b"\0" * ((-stream.tell()) % alignment))


def decompress(data: bytes, compression: int, expected_size: int) -> bytes:
    if compression == 0:
        result = data
    elif compression in (2, 3):
        result = lz4.block.decompress(data, uncompressed_size=expected_size)
    else:
        raise ValueError(f"unsupported UnityFS compression type {compression}")
    if len(result) != expected_size:
        raise ValueError(f"decompressed size mismatch: {len(result)} != {expected_size}")
    return result


def compress(data: bytes, compression: int) -> bytes:
    if compression == 0:
        return data
    if compression == 2:
        return lz4.block.compress(data, mode="fast", store_size=False)
    if compression == 3:
        return lz4.block.compress(data, mode="high_compression", compression=12, store_size=False)
    raise ValueError(f"unsupported UnityFS compression type {compression}")


def parse_bundle(path: Path) -> Bundle:
    raw = path.read_bytes()
    source = io.BytesIO(raw)
    signature = read_cstring(source)
    if signature != "UnityFS":
        raise ValueError(f"unexpected signature {signature!r}")
    version = read_be(source, "I")
    player_version = read_cstring(source)
    engine_version = read_cstring(source)
    bundle_size = read_be(source, "Q")
    compressed_info_size = read_be(source, "I")
    uncompressed_info_size = read_be(source, "I")
    flags = read_be(source, "I")
    header_end = source.tell()
    if bundle_size != len(raw):
        raise ValueError(f"bundle size mismatch: {bundle_size} != {len(raw)}")

    info_at_end = bool(flags & 0x80)
    if info_at_end:
        source.seek(bundle_size - compressed_info_size)
    else:
        if flags & 0x200:
            align_read(source, 16)
    compressed_info = source.read(compressed_info_size)
    info = io.BytesIO(decompress(compressed_info, flags & 0x3F, uncompressed_info_size))

    info_hash = info.read(16)
    blocks = [
        Block(read_be(info, "I"), read_be(info, "I"), read_be(info, "H"))
        for _ in range(read_be(info, "I"))
    ]
    nodes = [
        Node(read_be(info, "Q"), read_be(info, "Q"), read_be(info, "I"), read_cstring(info))
        for _ in range(read_be(info, "I"))
    ]

    if info_at_end:
        source.seek(header_end)
        if flags & 0x200:
            align_read(source, 16)
    elif flags & 0x200:
        align_read(source, 16)

    data = bytearray()
    for index, block in enumerate(blocks):
        encoded = source.read(block.compressed_size)
        if len(encoded) != block.compressed_size:
            raise EOFError(f"truncated data block {index}")
        data.extend(decompress(encoded, block.flags & 0x3F, block.uncompressed_size))

    return Bundle(signature, version, player_version, engine_version, flags, info_hash, blocks, nodes, data)


def build_block_info(bundle: Bundle, compressed_blocks: list[bytes]) -> bytes:
    info = io.BytesIO()
    info.write(bundle.info_hash)
    write_be(info, "I", len(bundle.blocks))
    for block, comp in zip(bundle.blocks, compressed_blocks):
        write_be(info, "I", block.uncompressed_size)
        write_be(info, "I", len(comp))
        write_be(info, "H", block.flags)
    write_be(info, "I", len(bundle.nodes))
    for node in bundle.nodes:
        write_be(info, "Q", node.offset)
        write_be(info, "Q", node.size)
        write_be(info, "I", node.flags)
        write_cstring(info, node.path)
    return info.getvalue()


def write_bundle(bundle: Bundle, destination: Path) -> None:
    compressed_blocks = []
    cursor = 0
    for block in bundle.blocks:
        block_data = bytes(bundle.data[cursor : cursor + block.uncompressed_size])
        cursor += block.uncompressed_size
        compressed_blocks.append(compress(block_data, block.flags & 0x3F))
    raw_info = build_block_info(bundle, compressed_blocks)
    compressed_info = compress(raw_info, bundle.flags & 0x3F)
    output = io.BytesIO()
    write_cstring(output, bundle.signature)
    write_be(output, "I", bundle.version)
    write_cstring(output, bundle.player_version)
    write_cstring(output, bundle.engine_version)
    size_position = output.tell()
    write_be(output, "Q", 0)
    write_be(output, "I", len(compressed_info))
    write_be(output, "I", len(raw_info))
    write_be(output, "I", bundle.flags)
    info_at_end = bool(bundle.flags & 0x80)
    if bundle.flags & 0x200:
        align_write(output, 16)
    if info_at_end:
        for block in compressed_blocks:
            output.write(block)
        output.write(compressed_info)
    else:
        output.write(compressed_info)
        if bundle.flags & 0x200:
            align_write(output, 16)
        for block in compressed_blocks:
            output.write(block)
    final_size = output.tell()
    output.seek(size_position)
    write_be(output, "Q", final_size)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output.getvalue())


# ── IL Analysis ──

def full_type_name(row) -> str:
    namespace = str(getattr(row, "TypeNamespace", ""))
    name = str(getattr(row, "TypeName", "?"))
    return f"{namespace}.{name}" if namespace else name


def build_method_owners(pe):
    owners = {}
    for typedef in pe.net.mdtables.TypeDef.rows:
        owner = full_type_name(typedef)
        for method in typedef.MethodList:
            owners[method.row_index] = owner
    return owners


def operand_text(value) -> str:
    if isinstance(value, Token):
        return str(value)
    if isinstance(value, list):
        return ", ".join(f"IL_{item:04X}" for item in value)
    if value is None:
        return ""
    return str(value)


def extract_dll_from_bundle(bundle: Bundle) -> tuple[bytes, Node]:
    """Extract the CAB (DLL) node from the bundle data."""
    for node in bundle.nodes:
        if node.path.startswith("CAB-"):
            dll_data = bytes(bundle.data[node.offset : node.offset + node.size])
            return dll_data, node
    raise ValueError("No CAB (DLL) node found in bundle")


def find_forcequit_pattern(dll_data: bytes, dll_path: str) -> list[dict]:
    """
    Search for the ForceQuitNotice handler pattern:
    ldfld [token]  ; load type field of ForceQuitNotice
    ldc.i4.1       ; push 1
    bne.un.s [off] ; if type != 1, branch (skip error dialog)
    call [token]   ; call ShowDialog / Quit handler

    We search for: 7B xx xx xx xx 17 33 xx 28 xx xx xx xx
    (13 bytes with 5 variable bytes for tokens and branch offset)
    """
    results = []
    pos = 0
    while True:
        # Search for 0x7B (ldfld) near 0x17 0x33 (ldc.i4.1; bne.un.s)
        idx = dll_data.find(b"\x17\x33", pos)
        if idx < 0:
            break
        # Check preceding byte is 0x7B (ldfld) and we have at least 4 bytes before
        if idx >= 5 and dll_data[idx - 5] == 0x7B:
            # Check following 5 bytes: 0x28 (call) + 4-byte token
            offset_byte = dll_data[idx + 2]
            call_pos = idx + 3
            if call_pos + 5 <= len(dll_data) and dll_data[call_pos] == 0x28:
                field_token = dll_data[idx - 4 : idx]
                method_token = dll_data[call_pos + 1 : call_pos + 5]
                results.append({
                    "file_offset": idx - 5,
                    "field_token": field_token.hex().upper(),
                    "bne_offset": offset_byte,
                    "method_token": method_token.hex().upper(),
                    "old_bytes_3": dll_data[idx : idx + 3].hex().upper(),
                    "context_before": dll_data[idx - 8 : idx - 5].hex().upper(),
                    "context_after": dll_data[idx + 3 : idx + 8].hex().upper(),
                })
        pos = idx + 1
    return results


def dump_methods_with_pattern(dll_path: str) -> None:
    """
    Parse the DLL with dnfile/dncil and dump all methods that contain
    a ldfld; ldc.i4.1; bne.un.s; call pattern, with surrounding IL context.
    """
    pe = dnfile.dnPE(dll_path)
    owners = build_method_owners(pe)
    methods = []
    for index, row in enumerate(pe.net.mdtables.MethodDef.rows, 1):
        if row.Rva:
            methods.append((pe.get_offset_from_rva(row.Rva), index, row))
    methods.sort()

    print("\n" + "=" * 80)
    print("DUMPING METHODS WITH ldfld; ldc.i4.1; bne.un.s PATTERN")
    print("=" * 80)

    found = 0
    for method_file_offset, index, row in methods:
        try:
            body = read_method_body_from_bytes(pe.get_data(row.Rva, 0x100000))
        except Exception:
            continue

        instructions = body.instructions
        has_pattern = False
        for i, inst in enumerate(instructions[:-2]):
            if (inst.opcode.name.startswith("ldfld") and
                instructions[i + 1].opcode.name == "ldc.i4" and
                instructions[i + 1].operand == 1 and
                instructions[i + 2].opcode.name.startswith("bne.un") and
                i + 3 < len(instructions) and
                instructions[i + 3].opcode.name == "call"):

                if not has_pattern:
                    found += 1
                    token = 0x06000000 | index
                    owner = owners.get(index, "?")
                    method_name = row.Name
                    print(f"\n{'=' * 80}")
                    print(f"Method #{found}: {owner}::{method_name}")
                    print(f"  Token: 0x{token:08X}  RVA: 0x{row.Rva:X}  File: 0x{method_file_offset:X}")
                    has_pattern = True

                inst_ldfld = instructions[i]
                inst_ldci4 = instructions[i + 1]
                inst_bne = instructions[i + 2]
                inst_call = instructions[i + 3]

                ldfld_bytes = " ".join(f"{b:02X}" for b in inst_ldfld.get_bytes())
                ldci4_bytes = " ".join(f"{b:02X}" for b in inst_ldci4.get_bytes())
                bne_bytes = " ".join(f"{b:02X}" for b in inst_bne.get_bytes())
                call_bytes = " ".join(f"{b:02X}" for b in inst_call.get_bytes())

                print(f"\n  Pattern at IL_{inst_ldfld.offset:04X}:")
                print(f"    {inst_ldfld.offset:04X}: {ldfld_bytes:<20} {inst_ldfld.opcode.name:<14} {operand_text(inst_ldfld.operand)}")
                print(f"    {inst_ldci4.offset:04X}: {ldci4_bytes:<20} {inst_ldci4.opcode.name:<14} {inst_ldci4.operand}")
                print(f"    {inst_bne.offset:04X}: {bne_bytes:<20} {inst_bne.opcode.name:<14} {operand_text(inst_bne.operand)}")
                print(f"    {inst_call.offset:04X}: {call_bytes:<20} {inst_call.opcode.name:<14} {operand_text(inst_call.operand)}")

                # Show context around the pattern
                ctx_start = max(0, i - 4)
                ctx_end = min(len(instructions), i + 8)
                print(f"\n  Context (IL_{instructions[ctx_start].offset:04X} - IL_{instructions[ctx_end-1].offset:04X}):")
                for j in range(ctx_start, ctx_end):
                    ci = instructions[j]
                    marker = ">>" if j in (i, i + 1, i + 2, i + 3) else "  "
                    cbytes = " ".join(f"{b:02X}" for b in ci.get_bytes())
                    print(f"    {marker} IL_{ci.offset:04X}  {cbytes:<20} {ci.opcode.name:<14} {operand_text(ci.operand)}")

    print(f"\nTotal methods with pattern: {found}")


# ── Main ──

def main():
    # Default new bundle path (from launcher_status.log)
    default_path = Path(os.environ.get("LOCALAPPDATA", "")) / "LocalLow" / "pi" / "超自然行动组" / "bundles" / "data" / "code" / "updatescript_500.dll.ab_u_a624426295f04443b448195052d3e304"

    if len(sys.argv) > 1:
        bundle_path = Path(sys.argv[1])
    else:
        bundle_path = default_path

    if not bundle_path.exists():
        print(f"ERROR: Bundle not found at {bundle_path}")
        print(f"Usage: python {Path(__file__).name} [path_to_updatescript_bundle]")
        sys.exit(1)

    source_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest().upper()
    print(f"Bundle: {bundle_path}")
    print(f"SHA-256: {source_hash}")

    # Step 1: Parse bundle and extract DLL
    print("\n[1] Parsing bundle...")
    bundle = parse_bundle(bundle_path)
    print(f"  Blocks: {len(bundle.blocks)}, Nodes: {len(bundle.nodes)}, Data: {len(bundle.data)} bytes")

    dll_data, cab_node = extract_dll_from_bundle(bundle)
    print(f"  CAB node: {cab_node.path}, Size: {cab_node.size} bytes")

    # Step 2: Byte-level pattern search (fast, works without dnfile installed)
    print("\n[2] Searching for ldfld; ldc.i4.1; bne.un.s; call byte patterns...")
    results = find_forcequit_pattern(dll_data, cab_node.path)
    print(f"  Found {len(results)} candidate(s):")
    for i, r in enumerate(results):
        print(f"  [{i}] offset=0x{r['file_offset']:X} field_token={r['field_token']} bne_off=0x{r['bne_offset']:02X} method_token={r['method_token']} old_3bytes={r['old_bytes_3']}")

    # Step 3: Full IL dump using dnfile/dncil for detailed analysis
    print("\n[3] Dumping methods via dnfile/dncil for detailed analysis...")
    # Write DLL to temp file for dnfile
    dll_path = bundle_path.parent / "_temp_extracted.dll"
    dll_path.write_bytes(dll_data)
    print(f"  Extracted DLL to: {dll_path}")
    try:
        dump_methods_with_pattern(str(dll_path))
    finally:
        dll_path.unlink()
        print(f"  Cleaned up temp DLL.")

    # Step 4: Summary
    print("\n" + "=" * 80)
    print("NEXT STEP:")
    print("  Review the method dumps above. For each method, check if it handles")
    print("  ForceQuitNotice (look for nearby ldstr instructions referencing")
    print("  'ForceQuitNotice' or 'dataErrorTextId').")
    print()
    print("  The CORRECT method will have:")
    print("  - ldfld loading a ForceQuitNotice.type field")
    print("  - ldc.i4.1 comparing against type == 1")
    print("  - bne.un.s branch (the one we need to replace)")
    print("  - call to ShowDialog/Quit/similar")
    print()
    print("  Once identified, the patch formula is:")
    print("    NEW_3BYTES = '26' + '2B' + hex(OLD_BNE_OFFSET - 1)[2:]")
    print("    (Replace 17XXYY -> 26 2B ZZ where ZZ = YY - 1)")
    print()
    print(f"  Bundle SHA-256: {source_hash}")
    print("=" * 80)


if __name__ == "__main__":
    main()
