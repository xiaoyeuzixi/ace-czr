"""Quick search for ForceQuitNotice handler via string/structure references."""
import sys
from pathlib import Path

import lz4.block
import io
import struct
import os

def read_cstring(s):
    data = bytearray()
    while True:
        b = s.read(1)
        if not b or b == b"\0": return data.decode("utf-8", errors="replace")
        data.extend(b)

def read_be(s, fmt):
    sz = struct.calcsize(">" + fmt)
    return struct.unpack(">" + fmt, s.read(sz))[0]

def decompress(data, comp, expected):
    if comp == 0: return data
    if comp in (2, 3): return lz4.block.decompress(data, uncompressed_size=expected)

def align(s, a):
    s.seek((-s.tell()) % a, os.SEEK_CUR)

bundle_path = Path(sys.argv[1])
raw = bundle_path.read_bytes()
src = io.BytesIO(raw)
sig = read_cstring(src)
ver = read_be(src, "I")
pv = read_cstring(src)
ev = read_cstring(src)
bsize = read_be(src, "Q")
cisize = read_be(src, "I")
uisize = read_be(src, "I")
flags = read_be(src, "I")
head_end = src.tell()

info_at_end = bool(flags & 0x80)
if info_at_end:
    src.seek(bsize - cisize)
else:
    if flags & 0x200: align(src, 16)

comp_info = src.read(cisize)
info_data = decompress(comp_info, flags & 0x3F, uisize)
info = io.BytesIO(info_data)
info.read(16)
bc = read_be(info, "I")
blocks = [(read_be(info, "I"), read_be(info, "I"), read_be(info, "H")) for _ in range(bc)]
nc = read_be(info, "I")
nodes = [(read_be(info, "Q"), read_be(info, "Q"), read_be(info, "I"), read_cstring(info)) for _ in range(nc)]

if info_at_end:
    src.seek(head_end)
    if flags & 0x200: align(src, 16)
elif flags & 0x200:
    align(src, 16)

data = bytearray()
for us, cs, bf in blocks:
    data.extend(decompress(src.read(cs), bf & 0x3F, us))

# Find CAB node and save DLL
for offset, size, nf, path in nodes:
    if path.startswith("CAB-"):
        dll = bytes(data[offset:offset+size])
        dll_path = bundle_path.parent / "_cab.dll"
        dll_path.write_bytes(dll)
        print(f"CAB={path} size={size}")
        
        # Search for key strings
        targets = [b"ForceQuitNotice", b"forcequit", b"ForceQuit", b"dataErrorTextId",
                   b"72000001", b"DBJDBDPCMNE", b"FODJBPAEILJ", b"DPNKPNAACPA",
                   b"\xe6\x95\xb0\xe6\x8d\xae\xe5\xbc\x82\xe5\xb8\xb8",  # "数据异常" UTF-8
                   b"\xe8\xaf\xb7\xe6\xa3\x80\xe6\x9f\xa5",              # "请检查"
                   ]
        for t in targets:
            idx = dll.find(t)
            if idx >= 0:
                ctx_before = dll[max(0,idx-32):idx]
                ctx_after = dll[idx:idx+min(64,len(dll)-idx)]
                print(f"  FOUND at 0x{idx:08X}: {t[:32]}")
                print(f"    before: {ctx_before.hex(' ').upper()}")
                print(f"    after:  {ctx_after.hex(' ').upper()}")
            else:
                print(f"  NOT FOUND: {t[:32]}")
        
        print(f"\nDLL saved to: {dll_path}")
        print(f"Run: python reanalyze_forcequit_dll.py {dll_path}")
        break
