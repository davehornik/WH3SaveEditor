# -*- coding: utf-8 -*-
"""
ESF (Empire Save Format) library for Total War: Warhammer 3 save files.

Supports the 0xABCB variant (WH3 post-7.0) and should also read 0xABCA
(WH1/2, Three Kingdoms, Troy) since the structural rules are identical;
only the string-table length prefixes differ (u32 vs u16).

Design: lazy tree over an immutable source buffer. Children are parsed on
demand. Serialization copies the original bytes verbatim for untouched
subtrees and re-encodes only dirty nodes (and their ancestors).
"""
import struct
import lzma

MAGIC_ABCB = 0xABCB
MAGIC_ABCA = 0xABCA

# --- node type codes -------------------------------------------------------
BOOL, I8, I16, I32, I64 = 0x01, 0x02, 0x03, 0x04, 0x05
U8, U16, U32, U64 = 0x06, 0x07, 0x08, 0x09
F32, F64 = 0x0A, 0x0B
COORD2D, COORD3D = 0x0C, 0x0D
UTF16, ASCII = 0x0E, 0x0F
ANGLE = 0x10
BOOL_TRUE, BOOL_FALSE = 0x12, 0x13
U32_ZERO, U32_ONE, U32_BYTE, U32_16BIT, U32_24BIT = 0x14, 0x15, 0x16, 0x17, 0x18
I32_ZERO, I32_BYTE, I32_16BIT, I32_24BIT = 0x19, 0x1A, 0x1B, 0x1C
F32_ZERO = 0x1D
UNK_21, UNK_23, UNK_24, UNK_25, UNK_26 = 0x21, 0x23, 0x24, 0x25, 0x26

# payload byte length of fixed-size value nodes
FIXED_SIZE = {BOOL: 1, I8: 1, I16: 2, I32: 4, I64: 8, U8: 1, U16: 2, U32: 4,
              U64: 8, F32: 4, F64: 8, COORD2D: 8, COORD3D: 12, UTF16: 4,
              ASCII: 4, ANGLE: 2, BOOL_TRUE: 0, BOOL_FALSE: 0, U32_ZERO: 0,
              U32_ONE: 0, U32_BYTE: 1, U32_16BIT: 2, U32_24BIT: 3, I32_ZERO: 0,
              I32_BYTE: 1, I32_16BIT: 2, I32_24BIT: 3, F32_ZERO: 0,
              UNK_21: 4, UNK_23: 1, UNK_24: 2, UNK_25: 4}

TYPE_NAMES = {0x01: "bool", 0x02: "i8", 0x03: "i16", 0x04: "i32", 0x05: "i64",
              0x06: "u8", 0x07: "u16", 0x08: "u32", 0x09: "u64", 0x0A: "f32",
              0x0B: "f64", 0x0C: "coord2d", 0x0D: "coord3d", 0x0E: "utf16",
              0x0F: "ascii", 0x10: "angle", 0x12: "bool", 0x13: "bool",
              0x14: "u32", 0x15: "u32", 0x16: "u32", 0x17: "u32", 0x18: "u32",
              0x19: "i32", 0x1A: "i32", 0x1B: "i32", 0x1C: "i32", 0x1D: "f32",
              0x21: "unk21", 0x23: "unk23", 0x24: "unk24", 0x25: "unk25",
              0x26: "unk26"}


def write_varint(value):
    """Big-endian 7-bit varint, high bit = continuation."""
    if value == 0:
        return b"\x00"
    out = bytearray()
    while value:
        out.append(value & 0x7F)
        value >>= 7
    out.reverse()
    for i in range(len(out) - 1):
        out[i] |= 0x80
    return bytes(out)


class Reader:
    __slots__ = ("d", "p")

    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def take(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def varint(self):
        result = 0
        b = self.u8()
        while b & 0x80:
            result = (result << 7) | (b & 0x7F)
            b = self.u8()
        return (result << 7) | b


# --- tree nodes ------------------------------------------------------------

class Node:
    __slots__ = ("esf", "parent", "dirty", "start", "cstart", "cend")

    def __init__(self, esf, parent, start, cstart, cend):
        self.esf = esf
        self.parent = parent
        self.dirty = False
        self.start = start      # first byte of the node (tag)
        self.cstart = cstart    # first byte of content/payload
        self.cend = cend        # one past last byte of node

    def mark_dirty(self):
        n = self
        while n is not None and not n.dirty:
            n.dirty = True
            n = n.parent

    @property
    def size(self):
        return self.cend - self.cstart


class Record(Node):
    __slots__ = ("name_idx", "version", "_children")

    def __init__(self, esf, parent, start, cstart, cend, name_idx, version):
        super().__init__(esf, parent, start, cstart, cend)
        self.name_idx = name_idx
        self.version = version
        self._children = None

    @property
    def name(self):
        return self.esf.names[self.name_idx]

    @property
    def children(self):
        if self._children is None:
            r = Reader(self.esf.data, self.cstart)
            kids = []
            while r.p < self.cend:
                kids.append(self.esf._read_node(r, self))
            if r.p != self.cend:
                raise ValueError("record %s overran: 0x%X != 0x%X" % (self.name, r.p, self.cend))
            self._children = kids
        return self._children

    def child(self, name):
        for c in self.children:
            if isinstance(c, (Record, RecordBlock)) and c.name == name:
                return c
        return None

    def walk(self, *names):
        node = self
        for nm in names:
            node = node.child(nm)
            if node is None:
                return None
        return node


class BlockEntry(Node):
    """One entry of a record block; behaves like an anonymous record."""
    __slots__ = ("_children", "deleted")

    def __init__(self, esf, parent, start, cstart, cend):
        super().__init__(esf, parent, start, cstart, cend)
        self._children = None
        self.deleted = False

    def delete(self):
        self.deleted = True
        self.mark_dirty()

    @property
    def children(self):
        if self._children is None:
            r = Reader(self.esf.data, self.cstart)
            kids = []
            while r.p < self.cend:
                kids.append(self.esf._read_node(r, self))
            if r.p != self.cend:
                raise ValueError("block entry overran: 0x%X != 0x%X" % (r.p, self.cend))
            self._children = kids
        return self._children


class RecordBlock(Node):
    __slots__ = ("name_idx", "version", "count", "_entries")

    def __init__(self, esf, parent, start, cstart, cend, name_idx, version, count):
        super().__init__(esf, parent, start, cstart, cend)
        self.name_idx = name_idx
        self.version = version
        self.count = count
        self._entries = None

    @property
    def name(self):
        return self.esf.names[self.name_idx]

    @property
    def entries(self):
        if self._entries is None:
            r = Reader(self.esf.data, self.cstart)
            ents = []
            for _ in range(self.count):
                estart = r.p
                esize = r.varint()
                ent = BlockEntry(self.esf, self, estart, r.p, r.p + esize)
                r.p = ent.cend
                ents.append(ent)
            if r.p != self.cend:
                raise ValueError("block %s overran: 0x%X != 0x%X" % (self.name, r.p, self.cend))
            self._entries = ents
        return self._entries


class Value(Node):
    __slots__ = ("code", "_value")

    def __init__(self, esf, parent, start, cstart, cend, code):
        super().__init__(esf, parent, start, cstart, cend)
        self.code = code
        self._value = None

    @property
    def type_name(self):
        return TYPE_NAMES.get(self.code, "0x%02X" % self.code)

    @property
    def value(self):
        if self.dirty:
            return self._value
        d, p, c = self.esf.data, self.cstart, self.code
        if c == BOOL:
            return d[p] != 0
        if c == BOOL_TRUE:
            return True
        if c == BOOL_FALSE:
            return False
        if c == I8:
            return struct.unpack_from("<b", d, p)[0]
        if c in (I16, ANGLE):
            return struct.unpack_from("<h", d, p)[0]
        if c == I32:
            return struct.unpack_from("<i", d, p)[0]
        if c == I64:
            return struct.unpack_from("<q", d, p)[0]
        if c == U8:
            return d[p]
        if c in (U16, UNK_24):
            return struct.unpack_from("<H", d, p)[0]
        if c in (U32, UNK_21, UNK_25):
            return struct.unpack_from("<I", d, p)[0]
        if c == U64:
            return struct.unpack_from("<Q", d, p)[0]
        if c == F32:
            return struct.unpack_from("<f", d, p)[0]
        if c == F64:
            return struct.unpack_from("<d", d, p)[0]
        if c == COORD2D:
            return struct.unpack_from("<ff", d, p)
        if c == COORD3D:
            return struct.unpack_from("<fff", d, p)
        if c == UTF16:
            return self.esf.utf16[struct.unpack_from("<I", d, p)[0]]
        if c == ASCII:
            return self.esf.ascii[struct.unpack_from("<I", d, p)[0]]
        if c in (U32_ZERO, I32_ZERO):
            return 0
        if c == U32_ONE:
            return 1
        if c in (U32_BYTE, UNK_23):
            return d[p]
        if c == U32_16BIT:
            return struct.unpack_from("<H", d, p)[0]
        if c == U32_24BIT:
            # 24-bit ints are BIG-endian (unlike 16/32-bit!)
            return (d[p] << 16) | (d[p + 1] << 8) | d[p + 2]
        if c == I32_BYTE:
            return struct.unpack_from("<b", d, p)[0]
        if c == I32_16BIT:
            return struct.unpack_from("<h", d, p)[0]
        if c == I32_24BIT:
            # big-endian sign-magnitude: high bit = sign, 23 bits magnitude
            v = ((d[p] & 0x7F) << 16) | (d[p + 1] << 8) | d[p + 2]
            return -v if d[p] & 0x80 else v
        if c == F32_ZERO:
            return 0.0
        if c == UNK_26:
            return bytes(d[self.cstart:self.cend]).hex()
        return bytes(d[self.cstart:self.cend]).hex()

    @value.setter
    def value(self, v):
        self._value = v
        self.mark_dirty()

    @property
    def editable(self):
        return self.code not in (UNK_21, UNK_23, UNK_24, UNK_25, UNK_26,
                                 COORD2D, COORD3D)


class ValueArray(Node):
    """Array of primitive values; payload kept raw, decoded on demand."""
    __slots__ = ("code", "_new")

    def __init__(self, esf, parent, start, cstart, cend, code):
        super().__init__(esf, parent, start, cstart, cend)
        self.code = code
        self._new = None

    def set_ascii_items(self, values):
        """Replace content of an ascii-ref array with the given strings."""
        self._new = list(values)
        self.mark_dirty()

    @property
    def base_code(self):
        return self.code & 0x3F

    @property
    def type_name(self):
        return TYPE_NAMES.get(self.base_code, "0x%02X" % self.base_code) + "[]"

    @property
    def raw(self):
        return self.esf.data[self.cstart:self.cend]

    def items(self, limit=None):
        """Decode array items (best effort, for display)."""
        c = self.base_code
        d = self.raw
        try:
            if c in (BOOL, U8, BOOL_TRUE, U32_BYTE, UNK_23):
                out = list(d)
            elif c == I8:
                out = list(struct.unpack("<%db" % len(d), d))
            elif c in (I16, ANGLE, I32_16BIT):
                out = list(struct.unpack("<%dh" % (len(d) // 2), d))
            elif c in (U16, U32_16BIT):
                out = list(struct.unpack("<%dH" % (len(d) // 2), d))
            elif c in (I32, I32_BYTE):
                out = list(struct.unpack("<%di" % (len(d) // 4), d))
            elif c in (U32, U32_ZERO, U32_ONE):
                out = list(struct.unpack("<%dI" % (len(d) // 4), d))
            elif c == I64:
                out = list(struct.unpack("<%dq" % (len(d) // 8), d))
            elif c == U64:
                out = list(struct.unpack("<%dQ" % (len(d) // 8), d))
            elif c == U32_24BIT:
                out = [(d[i] << 16) | (d[i + 1] << 8) | d[i + 2]
                       for i in range(0, len(d) - 2, 3)]
            elif c == I32_24BIT:
                out = [(-(((d[i] & 0x7F) << 16) | (d[i + 1] << 8) | d[i + 2])
                        if d[i] & 0x80 else
                        ((d[i] & 0x7F) << 16) | (d[i + 1] << 8) | d[i + 2])
                       for i in range(0, len(d) - 2, 3)]
            elif c in (F32, F32_ZERO):
                out = list(struct.unpack("<%df" % (len(d) // 4), d))
            elif c == F64:
                out = list(struct.unpack("<%dd" % (len(d) // 8), d))
            elif c == UTF16:
                idxs = struct.unpack("<%dI" % (len(d) // 4), d)
                out = [self.esf.utf16.get(i) for i in idxs]
            elif c == ASCII:
                idxs = struct.unpack("<%dI" % (len(d) // 4), d)
                out = [self.esf.ascii.get(i) for i in idxs]
            elif c == COORD2D:
                f = struct.unpack("<%df" % (len(d) // 4), d)
                out = list(zip(f[0::2], f[1::2]))
            elif c == COORD3D:
                f = struct.unpack("<%df" % (len(d) // 4), d)
                out = list(zip(f[0::3], f[1::3], f[2::3]))
            else:
                return None
        except struct.error:
            return None
        return out[:limit] if limit else out


# --- file ------------------------------------------------------------------

class EsfFile:
    def __init__(self, data):
        self.data = data
        r = Reader(data)
        self.magic = r.u32()
        if self.magic not in (MAGIC_ABCB, MAGIC_ABCA):
            raise ValueError("not a supported ESF file (magic 0x%X)" % self.magic)
        self.unknown = r.u32()
        self.timestamp = r.u32()
        table_off = r.u32()
        self._wide = self.magic == MAGIC_ABCB  # u32 string length prefixes
        # string tables live at the end of the file
        t = Reader(data, table_off)
        self.names = [t.take(t.u16()).decode("ascii") for _ in range(t.u16())]
        self.utf16 = {}
        for _ in range(t.u32()):
            n = t.u32() if self._wide else t.u16()
            s = t.take(n * 2).decode("utf-16-le")
            self.utf16[t.u32()] = s
        self.ascii = {}
        for _ in range(t.u32()):
            n = t.u32() if self._wide else t.u16()
            s = t.take(n).decode("latin-1")
            self.ascii[t.u32()] = s
        if t.p != len(data):
            raise ValueError("trailing bytes after string tables (%d)" % (len(data) - t.p))
        rr = Reader(data, 16)
        self.root = self._read_node(rr, None, is_root=True)

    @classmethod
    def from_path(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    # -- parsing -----------------------------------------------------------

    def _read_node(self, r, parent, is_root=False):
        start = r.p
        tag = r.u8()
        if tag & 0x80:
            if is_root or (tag & 0x20):
                name_idx = r.u16()
                version = r.u8()
            else:
                version = (tag & 0x1E) >> 1
                name_idx = ((tag & 1) << 8) | r.u8()
            if name_idx >= len(self.names):
                raise ValueError("bad record name index %d at 0x%X" % (name_idx, start))
            size = r.varint()
            if tag & 0x40:
                count = r.varint()  # block content size is anchored AFTER count
                node = RecordBlock(self, parent, start, r.p, r.p + size,
                                   name_idx, version, count)
            else:
                node = Record(self, parent, start, r.p, r.p + size,
                              name_idx, version)
            r.p = node.cend
            return node
        if tag & 0x40:
            size = r.varint()
            node = ValueArray(self, parent, start, r.p, r.p + size, tag)
            r.p = node.cend
            return node
        if tag in FIXED_SIZE:
            node = Value(self, parent, start, r.p, r.p + FIXED_SIZE[tag], tag)
            r.p = node.cend
            return node
        if tag == UNK_26:
            first = r.u8()
            n = first if (first % 8 == 0 and first != 0) else 7
            r.take(n)
            if r.p < len(self.data) and self.data[r.p] == 0x9C:
                r.p += 1
            return Value(self, parent, start, start + 1, r.p, tag)
        raise ValueError("unknown node tag 0x%02X at 0x%X" % (tag, start))

    # -- string management --------------------------------------------------

    def intern_utf16(self, s):
        for idx, v in self.utf16.items():
            if v == s:
                return idx
        idx = (max(self.utf16) + 1) if self.utf16 else 0
        self.utf16[idx] = s
        return idx

    def intern_ascii(self, s):
        for idx, v in self.ascii.items():
            if v == s:
                return idx
        idx = (max(self.ascii) + 1) if self.ascii else 0
        self.ascii[idx] = s
        return idx

    # -- serialization ------------------------------------------------------

    def _encode_value(self, node):
        """Re-encode a dirty Value with the game's optimized encoding."""
        v = node.value
        c = node.code
        tn = TYPE_NAMES.get(c)
        if tn == "bool":
            return bytes([BOOL_TRUE if v else BOOL_FALSE])
        if tn == "u32":
            # thresholds and encodings mirror EditSF's OptimizedUIntNode;
            # 24-bit is BIG-endian
            if v > 0xFFFFFF:
                return bytes([U32]) + struct.pack("<I", v)
            if v > 0xFFFF:
                return bytes([U32_24BIT, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])
            if v > 0xFF:
                return bytes([U32_16BIT]) + struct.pack("<H", v)
            if v > 1:
                return bytes([U32_BYTE, v])
            return bytes([U32_ONE if v == 1 else U32_ZERO])
        if tn == "i32":
            # mirrors EditSF's OptimizedIntNode; 24-bit is BIG-endian
            # sign-magnitude (high bit = sign, 23 bits = abs value)
            if v == 0:
                return bytes([I32_ZERO])
            if v == -0x80000000:
                return bytes([I32]) + struct.pack("<i", v)
            a = abs(v)
            if a & 0x7F800000:
                return bytes([I32]) + struct.pack("<i", v)
            if a & 0x7F8000:
                u = a | (0x800000 if v < 0 else 0)
                return bytes([I32_24BIT, (u >> 16) & 0xFF, (u >> 8) & 0xFF, u & 0xFF])
            if a & 0x7F80:
                return bytes([I32_16BIT]) + struct.pack("<h", v)
            return bytes([I32_BYTE]) + struct.pack("<b", v)
        if tn == "f32":
            if v == 0.0:
                return bytes([F32_ZERO])
            return bytes([F32]) + struct.pack("<f", v)
        if c == F64:
            return bytes([F64]) + struct.pack("<d", v)
        if c == I8:
            return bytes([I8]) + struct.pack("<b", v)
        if c == I16:
            return bytes([I16]) + struct.pack("<h", v)
        if c == ANGLE:
            return bytes([ANGLE]) + struct.pack("<h", v)
        if c == I64:
            return bytes([I64]) + struct.pack("<q", v)
        if c == U8:
            return bytes([U8, v & 0xFF])
        if c == U16:
            return bytes([U16]) + struct.pack("<H", v)
        if c == U64:
            return bytes([U64]) + struct.pack("<Q", v)
        if c in (UNK_21, UNK_25):
            return bytes([c]) + struct.pack("<I", v)
        if c == UNK_23:
            return bytes([c, v & 0xFF])
        if c == UNK_24:
            return bytes([c]) + struct.pack("<H", v)
        if c == UTF16:
            return bytes([UTF16]) + struct.pack("<I", self.intern_utf16(v))
        if c == ASCII:
            return bytes([ASCII]) + struct.pack("<I", self.intern_ascii(v))
        raise ValueError("cannot encode dirty value of type 0x%02X" % c)

    def _record_header(self, node, is_block, content_len, count=None, is_root=False):
        name_idx, version = node.name_idx, node.version
        body = write_varint(content_len)
        if is_block:
            body += write_varint(count)
        if is_root:
            return bytes([0x80]) + struct.pack("<H", name_idx) + bytes([version]) + body
        if name_idx <= 0x1FF and version <= 15:
            tag = 0x80 | (0x40 if is_block else 0) | ((version & 0xF) << 1) | (name_idx >> 8)
            return bytes([tag, name_idx & 0xFF]) + body
        tag = 0x80 | (0x40 if is_block else 0) | 0x20
        return bytes([tag]) + struct.pack("<H", name_idx) + bytes([version]) + body

    def _serialize(self, node, force=False, is_root=False):
        if not node.dirty and not force:
            return self.data[node.start:node.cend]
        if isinstance(node, Record):
            content = b"".join(self._serialize(c, force) for c in node.children)
            return self._record_header(node, False, len(content), is_root=is_root) + content
        if isinstance(node, RecordBlock):
            blob = bytearray()
            entries = [e for e in node.entries if not e.deleted]
            for e in entries:
                if not e.dirty and not force:
                    blob += self.data[e.start:e.cend]   # size varint + content
                    continue
                ec = b"".join(self._serialize(c, force) for c in e.children)
                blob += write_varint(len(ec)) + ec
            return self._record_header(node, True, len(blob), count=len(entries)) + bytes(blob)
        if isinstance(node, ValueArray):
            if node.dirty and node._new is not None:
                if isinstance(node._new, (bytes, bytearray)):
                    payload = bytes(node._new)
                else:
                    payload = b"".join(struct.pack("<I", self.intern_ascii(v))
                                       for v in node._new)
            else:
                payload = self.data[node.cstart:node.cend]
            return bytes([node.code]) + write_varint(len(payload)) + payload
        if isinstance(node, Value):
            if node.dirty:
                return self._encode_value(node)
            if node.code == UNK_26:
                return self.data[node.start:node.cend]
            return bytes([node.code]) + self.data[node.cstart:node.cend]
        raise TypeError(type(node))

    def to_bytes(self, force=False):
        body = self._serialize(self.root, force=force, is_root=True)
        out = bytearray()
        out += struct.pack("<IIII", self.magic, self.unknown, self.timestamp, 16 + len(body))
        out += body
        out += struct.pack("<H", len(self.names))
        for nm in self.names:
            b = nm.encode("ascii")
            out += struct.pack("<H", len(b)) + b
        out += struct.pack("<I", len(self.utf16))
        for idx, s in self.utf16.items():
            b = s.encode("utf-16-le")
            out += (struct.pack("<I", len(b) // 2) if self._wide else struct.pack("<H", len(b) // 2))
            out += b + struct.pack("<I", idx)
        out += struct.pack("<I", len(self.ascii))
        for idx, s in self.ascii.items():
            b = s.encode("latin-1")
            out += (struct.pack("<I", len(b)) if self._wide else struct.pack("<H", len(b)))
            out += b + struct.pack("<I", idx)
        return bytes(out)


# --- WH3 save wrapper ------------------------------------------------------

LZMA_FILTER = [{"id": lzma.FILTER_LZMA1, "lc": 3, "lp": 0, "pb": 2,
                "dict_size": 0x40000}]


class SaveFile:
    """A WH3 .save / .save_multiplayer: outer ESF + LZMA-compressed inner ESF."""

    def __init__(self, path):
        self.path = path
        self.outer = EsfFile.from_path(path)
        self.inner = None
        cd = self.outer.root.child("COMPRESSED_DATA")
        self._compressed = cd is not None
        if cd is not None:
            blob = next(c for c in cd.children if isinstance(c, ValueArray))
            info = cd.child("COMPRESSED_DATA_INFO")
            usize = info.children[0].value
            props = info.children[1].raw
            # primárně dekódovat s deklarovanou velikostí v hlavičce — bez ní
            # LZMA1 stream bez EOS markeru občas vyplivne bajt(y) navíc
            # (zbytkové bity paddingu), viz "decompressed size mismatch"
            raw = self.outer.data[blob.cstart:blob.cend]
            data = None
            try:
                header = bytes(props) + struct.pack("<Q", usize)
                data = lzma.LZMADecompressor(
                    format=lzma.FORMAT_ALONE).decompress(header + raw)
            except lzma.LZMAError:
                data = None
            if data is None or len(data) != usize:
                # fallback: "unknown size" (streamy s EOS markerem)
                header = bytes(props) + b"\xff" * 8
                data = lzma.LZMADecompressor(
                    format=lzma.FORMAT_ALONE).decompress(header + raw)
                if len(data) > usize:
                    data = data[:usize]
            if len(data) != usize:
                raise ValueError("decompressed size mismatch: %d != %d" % (len(data), usize))
            self.inner = EsfFile(data)

    @property
    def is_multiplayer(self):
        return self.outer.root.name == "MULTIPLAYER_CAMPAIGN_SAVE_GAME"

    @property
    def campaign_root(self):
        """Root of the actual campaign data (inner file if compressed)."""
        return (self.inner or self.outer).root

    def save(self, path):
        if self.inner is not None and (self.inner.root.dirty or True):
            inner_bytes = self.inner.to_bytes()
            comp = lzma.compress(inner_bytes, format=lzma.FORMAT_ALONE,
                                 filters=LZMA_FILTER)
            props, stream = comp[:5], comp[13:]
            # rebuild COMPRESSED_DATA node content manually
            cd = self.outer.root.child("COMPRESSED_DATA")
            info = cd.child("COMPRESSED_DATA_INFO")
            blob_bytes = bytes([0x46]) + write_varint(len(stream)) + stream
            usize_val = info.children[0]
            usize_val.value = len(inner_bytes)
            info_content = self.outer._serialize(usize_val) + bytes([0x46]) + write_varint(5) + props
            info_bytes = self.outer._record_header(info, False, len(info_content)) + info_content
            cd_content = blob_bytes + info_bytes
            cd_bytes = self.outer._record_header(cd, False, len(cd_content)) + cd_content
            # serialize outer root with COMPRESSED_DATA replaced
            parts = []
            for c in self.outer.root.children:
                if c is cd:
                    parts.append(cd_bytes)
                else:
                    parts.append(self.outer._serialize(c))
            content = b"".join(parts)
            body = self.outer._record_header(self.outer.root, False, len(content), is_root=True) + content
            out = bytearray()
            out += struct.pack("<IIII", self.outer.magic, self.outer.unknown,
                               self.outer.timestamp, 16 + len(body))
            out += body
            out += struct.pack("<H", len(self.outer.names))
            for nm in self.outer.names:
                b = nm.encode("ascii")
                out += struct.pack("<H", len(b)) + b
            out += struct.pack("<I", len(self.outer.utf16))
            for idx, s in self.outer.utf16.items():
                b = s.encode("utf-16-le")
                out += struct.pack("<I", len(b) // 2) + b + struct.pack("<I", idx)
            out += struct.pack("<I", len(self.outer.ascii))
            for idx, s in self.outer.ascii.items():
                b = s.encode("latin-1")
                out += struct.pack("<I", len(b)) + b + struct.pack("<I", idx)
            data = bytes(out)
        else:
            data = self.outer.to_bytes()
        with open(path, "wb") as f:
            f.write(data)
        return len(data)
