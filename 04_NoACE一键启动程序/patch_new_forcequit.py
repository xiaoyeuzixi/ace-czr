"""
Automatically search for and patch the ForceQuitNotice (type==1) branch
in the NEW updatescript bundle.

Two operating modes:

  MODE A — Auto-patch (exactly 1 match found):
    python patch_new_forcequit.py <new_bundle.ab>

  MODE B — Search & review (multiple candidates or manual check):
    python patch_new_forcequit.py <new_bundle.ab> --dry-run
    (Reports all candidates; you verify which one is correct)

Patch formula (same as original fix):
  17 33 XX  -->  26 2B ZZ    where ZZ = XX - 1

  17 = ldc.i4.1 (push 1)  -->  26 = pop (discard type value)
  33 = bne.un.s XX        -->  2B = br.s ZZ (unconditional jump)
  ZZ = XX - 1 (branch target adjusted because pop consumes 1 value)

Requirements: pip install lz4
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
    print("  C:\\Users\\Administrator\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\pip install lz4")
    sys.exit(1)


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
        return data
    if compression in (2, 3):
        return lz4.block.decompress(data, uncompressed_size=expected_size)
    raise ValueError(f"unsupported compression type {compression}")


def compress(data: bytes, compression: int) -> bytes:
    if compression == 0:
        return data
    if compression == 2:
        return lz4.block.compress(data, mode="fast", store_size=False)
    if compression == 3:
        return lz4.block.compress(data, mode="high_compression", compression=12, store_size=False)
    raise ValueError(f"unsupported compression type {compression}")


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
    for block in blocks:
        encoded = source.read(block.compressed_size)
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


def find_candidates(dll_data: bytes, cab_node_name: str) -> list[dict]:
    """
    Search the DLL data for:
      ldfld [4 bytes]  ; 7B xx xx xx xx
      ldc.i4.1          ; 17
      bne.un.s [1 byte] ; 33 YY
      call [4 bytes]    ; 28 xx xx xx xx

    Total: 13 bytes (7B + 4 + 17 + 33 + 1 + 28 + 4)
    """
    results = []
    pos = 0
    while True:
        idx = dll_data.find(b"\x17\x33", pos)
        if idx < 0:
            break
        # Check: at least 5 bytes before (for 7B + 4-byte token)
        # Check: at least 6 bytes after (for 1-byte offset + 28 + 4-byte token)
        if idx >= 5 and idx + 6 <= len(dll_data):
            if dll_data[idx - 5] == 0x7B and dll_data[idx + 3] == 0x28:
                field_token = dll_data[idx - 4 : idx]
                old_3bytes = dll_data[idx : idx + 3]
                bne_offset = dll_data[idx + 2]
                method_token = dll_data[idx + 4 : idx + 8]

                # New offset: ZZ = YY - 1 (same formula as original patch)
                new_offset = (bne_offset - 1) & 0xFF
                new_3bytes = bytes([0x26, 0x2B, new_offset])

                results.append({
                    "node": cab_node_name,
                    "file_offset": idx - 5,
                    "old_bytes": old_3bytes.hex().upper(),
                    "new_bytes": new_3bytes.hex().upper(),
                    "field_token": field_token.hex().upper(),
                    "method_token": method_token.hex().upper(),
                    "bne_offset_hex": f"0x{bne_offset:02X}",
                    "bne_offset_dec": bne_offset,
                    "new_offset_hex": f"0x{new_offset:02X}",
                    "context_13bytes": dll_data[idx - 5 : idx + 8].hex(" ").upper(),
                })
        pos = idx + 1
    return results


def main():
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    if len(args) < 1:
        # Default to new bundle path (from launcher log)
        default = Path(os.environ.get("LOCALAPPDATA", "")) / "LocalLow" / "pi" / "超自然行动组" / "bundles" / "data" / "code" / "updatescript_500.dll.ab_u_a624426295f04443b448195052d3e304"
        bundle_path = default
    else:
        bundle_path = Path(args[0])

    if not bundle_path.exists():
        print(f"ERROR: Bundle not found at {bundle_path}")
        print()
        print("Please copy the new bundle file to this script's directory first, e.g.:")
        print('  copy "%LOCALAPPDATA%\\LocalLow\\pi\\超自然行动组\\bundles\\data\\code\\updatescript_500.dll.ab_u_*" .')
        print()
        print(f"Usage: python {Path(__file__).name} <path_to_bundle> [--dry-run]")
        sys.exit(1)

    source_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest().upper()
    print(f"[*] Bundle: {bundle_path}")
    print(f"[*] SHA-256: {source_hash}")

    # Parse bundle
    bundle = parse_bundle(bundle_path)
    cab_nodes = [n for n in bundle.nodes if n.path.startswith("CAB-")]
    if not cab_nodes:
        print("ERROR: No CAB (DLL) node found in bundle")
        sys.exit(1)

    print(f"[*] Bundle: {len(bundle.blocks)} blocks, {len(bundle.nodes)} nodes, {len(bundle.data)} bytes data")
    print(f"[*] CAB nodes: {[n.path for n in cab_nodes]}")

    # Search for candidates in each CAB node
    all_candidates = []
    for cab_node in cab_nodes:
        dll_data = bytes(bundle.data[cab_node.offset : cab_node.offset + cab_node.size])
        candidates = find_candidates(dll_data, cab_node.path)
        all_candidates.extend(candidates)

    print(f"\n[*] Found {len(all_candidates)} candidate(s):")
    for i, c in enumerate(all_candidates):
        print(f"  [{i}] node={c['node']} offset=0x{c['file_offset']:X}")
        print(f"      field_token={c['field_token']}  method_token={c['method_token']}")
        print(f"      bne_offset={c['bne_offset_hex']} ({c['bne_offset_dec']})")
        print(f"      OLD 3 bytes: {c['old_bytes']}  -->  NEW 3 bytes: {c['new_bytes']}")
        print(f"      Context: {c['context_13bytes']}")

    if len(all_candidates) == 0:
        print("\n[!] No matching patterns found. The ForceQuitNotice handler structure may have changed significantly.")
        print("    Try running reanalyze_forcequit.py to dump detailed IL for manual review.")
        sys.exit(1)

    if len(all_candidates) > 1:
        print(f"\n[!] Multiple candidates ({len(all_candidates)}) found.")
        print("    The ORIGINAL patch had exactly 1 match. Please review the candidates above.")
        print("    Look for a candidate whose field_token likely points to a ForceQuitNotice.type field.")
        print()
        if dry_run:
            print("    --dry-run mode: no changes made. Review and re-run with specific candidate index.")
            sys.exit(0)
        print("    To auto-patch: confirm which candidate index is correct, or run with --dry-run first.")
        print("    Then run: python patch_new_forcequit.py <bundle> --pick N")
        sys.exit(1)

    # Exactly 1 candidate - can auto-patch
    candidate = all_candidates[0]
    print(f"\n[*] Single candidate found. Patching...")

    if dry_run:
        print("    --dry-run mode: would patch at offset 0x{candidate['file_offset']:X}")
        print(f"    Would change: {candidate['old_bytes']} -> {candidate['new_bytes']}")
        print("    No files modified.")
        sys.exit(0)

    # Apply patch
    cab_node = next(n for n in cab_nodes if n.path == candidate["node"])
    dll_offset_in_cab = candidate["file_offset"] - cab_node.offset
    absolute_offset = cab_node.offset + dll_offset_in_cab

    old_3 = bytes.fromhex(candidate["old_bytes"])
    new_3 = bytes.fromhex(candidate["new_bytes"])

    if bundle.data[absolute_offset : absolute_offset + 3] != old_3:
        print(f"ERROR: Bytes at offset 0x{absolute_offset:X} don't match expected {candidate['old_bytes']}")
        sys.exit(1)

    bundle.data[absolute_offset : absolute_offset + 3] = new_3

    # Write patched bundle
    output_path = bundle_path.parent / f"{bundle_path.stem}_forcequit_fix.ab"
    write_bundle(bundle, output_path)

    output_hash = hashlib.sha256(output_path.read_bytes()).hexdigest().upper()

    print(f"[+] Patched bundle written: {output_path}")
    print(f"[+] Original SHA-256: {source_hash}")
    print(f"[+] Patched  SHA-256: {output_hash}")
    print(f"[+] Change: 0x{absolute_offset:X}  {candidate['old_bytes']} -> {candidate['new_bytes']}")
    print(f"[+] CAB node: {candidate['node']}")

    # Verify no old pattern remains
    dll_data = bytes(bundle.data[cab_node.offset : cab_node.offset + cab_node.size])
    if old_3 in dll_data:
        print("[!] WARNING: Old byte sequence still found in CAB node!")
    else:
        print("[+] Verification passed: no old sequence remaining in CAB node.")

    print(f"\n[*] NEXT: Copy {output_path.name} back to the game's bundle directory as:")
    for name in [bundle_path.name, os.path.basename(str(bundle_path))]:
        print(f"      {name}")
    print(f"[*] Then update Start_Game_NoACE.ps1 with new OriginalHash={source_hash} and PatchHash={output_hash}")


if __name__ == "__main__":
    main()
