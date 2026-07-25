# -*- coding: utf-8 -*-
"""Unit test: value encode -> decode round trip for all optimized encodings."""
from esf import EsfFile, Reader, Value, TYPE_NAMES, U32, I32

def dummy_esf(buf=b""):
    d = EsfFile.__new__(EsfFile)
    d.data = buf
    d.names, d.utf16, d.ascii = [], {}, {}
    return d

def encode(code, v):
    d = dummy_esf()
    node = Value(d, None, 0, 0, 0, code)
    node.value = v
    return d._encode_value(node)

def decode(buf):
    d = dummy_esf(buf)
    r = Reader(buf)
    node = EsfFile._read_node(d, r, None)
    assert r.p == len(buf), "not all bytes consumed"
    return node.value, node.code

U32_CASES = [0, 1, 2, 255, 256, 40000, 65535, 65536, 0xFFFFFF, 0x1000000,
             4234240, 4294967295]
I32_CASES = [0, 1, -1, 127, -127, 128, -128, 32767, -32767, 32768, -32768,
             40000, -40000, 8388607, -8388607, 8388608, -8388608,
             2147483647, -2147483648]

for v in U32_CASES:
    buf = encode(U32, v)
    got, code = decode(buf)
    assert got == v, "u32 %d -> %s -> %d" % (v, buf.hex(), got)
    print("u32 %12d -> %-10s (%s)" % (v, buf.hex(), TYPE_NAMES[code]))
for v in I32_CASES:
    buf = encode(I32, v)
    got, code = decode(buf)
    assert got == v, "i32 %d -> %s -> %d" % (v, buf.hex(), got)
    print("i32 %12d -> %-10s (%s)" % (v, buf.hex(), TYPE_NAMES[code]))

# the exact case from the bug report: 40000 must be BE 24-bit 00 9c 40
assert encode(I32, 40000) == bytes.fromhex("1c009c40"), encode(I32, 40000).hex()
# and the OLD buggy LE bytes must decode to what David saw in game (4,234,240)
got, _ = decode(bytes.fromhex("1c409c00"))
assert got == 4234240, got
print("regression case OK: i32 40000 = 1c 00 9c 40 (BE); old LE bytes read as 4,234,240")
print("ENCODING TESTS PASSED")
