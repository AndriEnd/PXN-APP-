"""Alat bantu analisis statis updater x86 (tanpa menjalankan EXE)."""
import re
import struct

import capstone

SRC = "D:/pxn/pxn-v10-firmware-update-v0.47_1/PXN-V10 Firmware UpdateV0.47.exe"
d = open(SRC, "rb").read()
IB = 0x400000
pe = struct.unpack_from("<I", d, 0x3C)[0]
nsec = struct.unpack_from("<H", d, pe + 6)[0]
optsz = struct.unpack_from("<H", d, pe + 20)[0]
opt = pe + 24
secoff = opt + optsz
secs = [struct.unpack_from("<8sIIII", d, secoff + i * 40) for i in range(nsec)]


def r2o(r):
    for n, vs, va, rs, rp in secs:
        if va <= r < va + max(vs, rs):
            return r - va + rp
    return None


def cstr(off):
    return d[off:d.index(b"\0", off)].decode(errors="replace")


iat = {}
o = r2o(struct.unpack_from("<I", d, opt + 96 + 8)[0])
while True:
    oft, ts, fc, nm, ft = struct.unpack_from("<IIIII", d, o)
    if nm == 0:
        break
    t = r2o(oft or ft)
    a = ft
    while True:
        v = struct.unpack_from("<I", d, t)[0]
        if v == 0:
            break
        if not v & 0x80000000:
            iat[IB + a] = cstr(r2o(v) + 2)
        t += 4
        a += 4
    o += 20

text = next(s for s in secs if s[0].startswith(b".text"))
tb = d[text[4]:text[4] + text[3]]
tva = IB + text[2]
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)


def sites(name):
    a = next(k for k, v in iat.items() if v == name)
    return [tva + m.start() for m in re.finditer(re.escape(b"\xff\x15" + struct.pack("<I", a)), tb)]


def dis(start, length):
    off = start - tva
    out = []
    for i in md.disasm(tb[off:off + length], start):
        op = i.op_str
        m = re.search(r"dword ptr \[(0x[0-9a-f]+)\]", op)
        if i.mnemonic == "call" and m and int(m.group(1), 16) in iat:
            op = iat[int(m.group(1), 16)]
        out.append((i.address, i.mnemonic, op))
    return out
