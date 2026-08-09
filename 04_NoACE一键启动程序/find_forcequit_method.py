"""Use dnfile to find ForceQuitNotice type==1 handler - simplified & fixed."""
import sys
from pathlib import Path
import dnfile
from dncil.cil.body.reader import read_method_body_from_bytes
from dncil.clr.token import Token

dll_path = Path(sys.argv[1])
pe = dnfile.dnPE(str(dll_path))

# Build type map
types = {}
for idx, row in enumerate(pe.net.mdtables.TypeDef.rows, 1):
    ns = str(getattr(row, "TypeNamespace", ""))
    name = str(row.TypeName)
    fqn = f"{ns}.{name}" if ns else name
    types[idx] = fqn

# Build method owners
method_owners = {}
for row in pe.net.mdtables.TypeDef.rows:
    owner_ns = str(getattr(row, "TypeNamespace", ""))
    owner_name = str(row.TypeName)
    owner = f"{owner_ns}.{owner_name}" if owner_ns else owner_name
    for method in row.MethodList:
        method_owners[method.row_index] = owner

# Build method list sorted by file offset
methods = []
for index, row in enumerate(pe.net.mdtables.MethodDef.rows, 1):
    if row.Rva:
        methods.append((pe.get_offset_from_rva(row.Rva), index, row))
methods.sort()

def ot(value) -> str:
    if isinstance(value, Token): return str(value)
    if isinstance(value, list): return ", ".join(f"IL_{x:04X}" for x in value)
    if value is None: return ""
    return str(value)

print(f"Scanning {len(methods):,} methods for ldfld; ldc.i4.1; bne.un.s; call...\n")

found = 0
for method_file_offset, index, row in methods:
    try:
        body = read_method_body_from_bytes(pe.get_data(row.Rva, 0x100000))
    except Exception:
        continue
    
    insts = body.instructions
    owner = method_owners.get(index, "?")
    hdr_size = body.header_size if hasattr(body, 'header_size') else 0
    
    for i, inst in enumerate(insts[:-3]):
        if not inst.opcode.name.startswith("ldfld"):
            continue
        if i+3 >= len(insts):
            continue
        # Check for ldc.i4.1 (opcode 0x17) - single byte instruction
        b1 = insts[i+1].get_bytes()
        if b1 != b'\x17':
            continue
        if not insts[i+2].opcode.name.startswith("bne.un"):
            continue
        if insts[i+3].opcode.name != "call":
            continue
        
        found += 1
        token = f"0x060{index:05X}"
        fld = inst.operand
        cal = insts[i+3].operand
        
        # Get old 3 bytes (ldc.i4.1 + bne.un.s XX)
        b1 = insts[i+1].get_bytes()
        b2 = insts[i+2].get_bytes()
        old_3 = b1 + b2
        bne_off = b2[1] if len(b2) > 1 else 0
        new_off = (bne_off - 1) & 0xFF
        
        # PE file offset of the ldc.i4.1 instruction
        pe_offset = method_file_offset + hdr_size + insts[i+1].offset
        # CAB offset = PE offset + 0xB1C
        cab_offset = pe_offset + 0xB1C
        
        print(f"[{found:3d}] {owner}::{row.Name}")
        print(f"      MethodDef={token} RVA=0x{row.Rva:X} PE_off=0x{method_file_offset:X}")
        print(f"      Field: {ot(fld)}")
        print(f"      Call:  {ot(cal)}")
        print(f"      IL_{insts[i+1].offset:04X}: {' '.join(f'{b:02X}' for b in old_3)} -> 26 2B {new_off:02X}")
        print(f"      PE offset: 0x{pe_offset:X}")
        print(f"      CAB offset: 0x{cab_offset:X}")
        print()
        
        if found >= 50:
            break
    
    if found >= 50:
        break

print(f"\nTotal matches: {found}")
