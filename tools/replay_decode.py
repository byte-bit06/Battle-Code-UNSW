"""Decode a UNSW Battlecode replay (packed Cap'n Proto, optionally gzipped).

Schema taken from the official replay viewer (replay-viewer.vsix, webview.js).
decode(path) -> dict(map=str, botA, botB, events=[...], result={...})
"""
import gzip
import struct

DIRS = "NESW"
DEATH = {0: "hit wall", 1: "hit self", 2: "hit other body", 3: "head-to-head", 4: "no valid action"}
END = {0: "team eliminated", 1: "round limit"}


def unpack(data: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        tag = data[i]; i += 1
        word = bytearray(8)
        for b in range(8):
            if tag & (1 << b):
                word[b] = data[i]; i += 1
        out += word
        if tag == 0x00:
            out += bytes(8 * data[i]); i += 1
        elif tag == 0xFF:
            cnt = data[i]; i += 1
            out += data[i:i + 8 * cnt]; i += 8 * cnt
    return bytes(out)


class Msg:
    def __init__(self, raw: bytes):
        nseg = struct.unpack_from("<I", raw, 0)[0] + 1
        sizes = struct.unpack_from(f"<{nseg}I", raw, 4)
        off = 4 + 4 * nseg
        off += (8 - off % 8) % 8
        self.segs = []
        for s in sizes:
            self.segs.append(raw[off:off + 8 * s]); off += 8 * s

    def word(self, seg, w):
        return struct.unpack_from("<Q", self.segs[seg], 8 * w)[0]

    def resolve(self, seg, w):
        """Follow a pointer at (seg, word w). Returns (kind, seg, target_word, pointer_word_value)."""
        p = self.word(seg, w)
        if p == 0:
            return None
        kind = p & 3
        if kind == 2:  # far pointer
            double = (p >> 2) & 1
            pad = (p >> 3) & ((1 << 29) - 1)
            tseg = (p >> 32) & 0xFFFFFFFF
            if not double:
                return self.resolve(tseg, pad)
            land = self.word(tseg, pad)
            tag = self.word(tseg, pad + 1)
            seg2 = (land >> 32) & 0xFFFFFFFF
            start = (land >> 3) & ((1 << 29) - 1)
            return (tag & 3, seg2, start, tag)
        off = (p >> 2) & ((1 << 30) - 1)
        if off & (1 << 29):
            off -= 1 << 30
        return (kind, seg, w + 1 + off, p)


class Struct:
    def __init__(self, m, seg, start, dw, pw):
        self.m, self.seg, self.start, self.dw, self.pw = m, seg, start, dw, pw

    def _bytes(self):
        return self.m.segs[self.seg]

    def u16(self, byte):
        return struct.unpack_from("<H", self._bytes(), 8 * self.start + byte)[0] if byte + 2 <= 8 * self.dw else 0

    def i32(self, byte):
        return struct.unpack_from("<i", self._bytes(), 8 * self.start + byte)[0] if byte + 4 <= 8 * self.dw else 0

    def u32(self, byte):
        return struct.unpack_from("<I", self._bytes(), 8 * self.start + byte)[0] if byte + 4 <= 8 * self.dw else 0

    def bit(self, n):
        return bool(self._bytes()[8 * self.start + n // 8] >> (n % 8) & 1) if n // 8 < 8 * self.dw else False

    def ptr(self, i):
        if i >= self.pw:
            return None
        return self.m.resolve(self.seg, self.start + self.dw + i)

    def struct(self, i):
        r = self.ptr(i)
        if r is None:
            return None
        kind, seg, start, p = r
        return Struct(self.m, seg, start, (p >> 32) & 0xFFFF, (p >> 48) & 0xFFFF)

    def list(self, i):
        r = self.ptr(i)
        if r is None:
            return []
        kind, seg, start, p = r
        esize = (p >> 32) & 7
        count = (p >> 35) & ((1 << 29) - 1)
        if esize == 7:  # composite
            tag = self.m.word(seg, start)
            n = (tag >> 2) & ((1 << 30) - 1)
            dw, pw = (tag >> 32) & 0xFFFF, (tag >> 48) & 0xFFFF
            return [Struct(self.m, seg, start + 1 + k * (dw + pw), dw, pw) for k in range(n)]
        data = self.m.segs[seg][8 * start:]
        if esize == 2:   # byte
            return list(data[:count])
        if esize == 3:   # 2 bytes
            return list(struct.unpack_from(f"<{count}H", data, 0))
        if esize == 4:
            return list(struct.unpack_from(f"<{count}i", data, 0))
        raise ValueError(f"list element size {esize}")

    def text(self, i):
        b = self.list(i)
        return bytes(b[:-1]).decode("utf8", "replace") if b else ""


def point(s):
    return None if s is None else (s.i32(0), s.i32(4))


def decode(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    m = Msg(unpack(raw))
    p = (m.word(0, 0))
    root = Struct(m, 0, 1 + (((p >> 2) & ((1 << 30) - 1))), (p >> 32) & 0xFFFF, (p >> 48) & 0xFFFF)
    events = []
    for ev in root.list(3):
        which = ev.u16(0)
        s = ev.struct(0)
        if which == 0:
            events.append(("round", s.i32(0)))
        elif which == 1:
            events.append(("turn", s.i32(0)))
        elif which == 3:
            events.append(("tile", point(s.struct(0)), s.bit(0)))
        elif which == 4:
            a = s.struct(0)
            if a is None:
                events.append(("noaction", s.i32(0)))
            elif a.u16(0) == 0:
                events.append(("move", s.i32(0), "".join(DIRS[d] for d in a.list(0))))
            else:
                events.append(("splitcmd", s.i32(0), a.i32(4)))
        elif which == 9:
            events.append(("update", s.i32(0), DIRS[s.u16(4)], point(s.struct(0)), point(s.struct(1))))
        elif which == 10:
            events.append(("split", s.i32(0), s.i32(4), "AB"[s.u16(8)], DIRS[s.u16(10)],
                           [point(q) for q in s.list(0)], [point(q) for q in s.list(1)]))
        elif which == 11:
            events.append(("death", s.i32(0), DEATH.get(s.u16(4), s.u16(4))))
        elif which == 12:
            hit = s.i32(12) if s.u16(6) == 1 else None
            events.append(("sonar", s.i32(0), DIRS[s.u16(4)], s.u32(8), point(s.struct(0)), point(s.struct(1)), hit))
        elif which == 5:
            events.append(("enginelog", s.i32(0), s.text(0)))
        # 2 pearlCountdown, 6 dragonLog, 7 indicator, 8 debugDraw: not needed
    res = root.struct(4)
    standing = lambda t: None if t is None else {"dragons": t.i32(0), "longest": t.i32(4), "total": t.i32(8)}
    result = {"terminated": res.bit(0), "end": END.get(res.u16(2), res.u16(2)),
              "winner": "AB"[res.u16(6)] if res.u16(4) == 1 else None,
              "A": standing(res.struct(0)), "B": standing(res.struct(1))}
    return {"map": root.text(0), "botA": root.text(1), "botB": root.text(2), "events": events, "result": result}


if __name__ == "__main__":
    import collections, sys
    r = decode(sys.argv[1])
    print(r["botA"], "vs", r["botB"], r["result"])
    print(collections.Counter(e[0] for e in r["events"]))
    for e in r["events"][:60]:
        print(e)
