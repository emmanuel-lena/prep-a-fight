"""The bosses' portraits of the Encounter Journal (the round picture of each fight in the game), as PNG.

The Journal names each boss's picture by a game file id (JournalEncounterCreature.FileDataID); wago.tools serves the
game files, a BLP2 texture (DXT1/3/5 or uncompressed BGRA), decoded here in pure Python (no image library) and saved
once as PNG in <data>/bossimg/. The order of the bosses is the Journal's (its instance, then
JournalEncounter.OrderIndex).
"""

from __future__ import annotations

import struct
import urllib.request
import zlib
from pathlib import Path

from paf.config import data_dir

CASC = "https://wago.tools/api/casc/{fdid}?download"


def _rgb565(c: int) -> tuple[int, int, int]:
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def _color_block(data: bytes, off: int, dxt1: bool) -> list[tuple[int, int, int, int]]:
    c0, c1, bits = struct.unpack_from("<HHI", data, off)
    a, b = _rgb565(c0), _rgb565(c1)
    if c0 > c1 or not dxt1:
        pal = [a + (255,), b + (255,), tuple((2 * x + y) // 3 for x, y in zip(a, b, strict=True)) + (255,),
               tuple((x + 2 * y) // 3 for x, y in zip(a, b, strict=True)) + (255,)]
    else:
        pal = [a + (255,), b + (255,), tuple((x + y) // 2 for x, y in zip(a, b, strict=True)) + (255,), (0, 0, 0, 0)]
    return [pal[(bits >> (2 * i)) & 3] for i in range(16)]


def _alpha_dxt5(data: bytes, off: int) -> list[int]:
    a0, a1 = data[off], data[off + 1]
    bits = int.from_bytes(data[off + 2:off + 8], "little")
    if a0 > a1:
        pal = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    else:
        pal = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
    return [pal[(bits >> (3 * i)) & 7] for i in range(16)]


def decode_blp(data: bytes) -> tuple[int, int, bytes]:
    """(width, height, RGBA bytes) of the first mip of a BLP2 texture."""
    magic, _type, comp, adepth, atype, _mips, w, h = struct.unpack_from("<4sIBBBBII", data, 0)
    if magic != b"BLP2":
        raise ValueError("not a BLP2 texture")
    off, size = struct.unpack_from("<I", data, 20)[0], struct.unpack_from("<I", data, 84)[0]
    px = bytearray(w * h * 4)
    if comp == 3:  # uncompressed BGRA
        for i in range(w * h):
            b, g, r, a = data[off + 4 * i:off + 4 * i + 4]
            px[4 * i:4 * i + 4] = bytes((r, g, b, a))
        return w, h, bytes(px)
    if comp == 1:  # 256-color palette, then indices, then alpha
        pal = [struct.unpack_from("<BBBB", data, 148 + 4 * i) for i in range(256)]
        for i in range(w * h):
            b, g, r, _ = pal[data[off + i]]
            a = 255
            if adepth == 8:
                a = data[off + w * h + i]
            elif adepth == 1:
                a = 255 if data[off + w * h + i // 8] >> (i % 8) & 1 else 0
            elif adepth == 4:
                a = ((data[off + w * h + i // 2] >> (4 * (i % 2))) & 15) * 17
            px[4 * i:4 * i + 4] = bytes((r, g, b, a))
        return w, h, bytes(px)
    if comp != 2:
        raise ValueError(f"BLP2 compression {comp} not handled")
    dxt = 1 if adepth <= 1 else 3 if atype == 1 else 5
    step = 8 if dxt == 1 else 16
    pos = off
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            if pos + step > off + size:
                break
            if dxt == 1:
                colors, alphas = _color_block(data, pos, True), None
            elif dxt == 3:
                bits = int.from_bytes(data[pos:pos + 8], "little")
                alphas = [((bits >> (4 * i)) & 15) * 17 for i in range(16)]
                colors = _color_block(data, pos + 8, False)
            else:
                alphas, colors = _alpha_dxt5(data, pos), _color_block(data, pos + 8, False)
            pos += step
            for i in range(16):
                x, y = bx + i % 4, by + i // 4
                if x < w and y < h:
                    r, g, b, a = colors[i]
                    px[4 * (y * w + x):4 * (y * w + x) + 4] = bytes((r, g, b, alphas[i] if alphas else a))
    return w, h, bytes(px)


def png(w: int, h: int, rgba: bytes) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def journal() -> tuple[dict[int, int], dict[int, tuple[int, int]]]:
    """(encounter id -> portrait file id of its first boss, encounter id -> (its instance, its order in it))."""
    from paf.gamedata import table_rows

    rows = {r["ID"]: r for r in table_rows("JournalEncounter") if (r.get("DungeonEncounterID") or "").isdigit()}
    order = {int(r["DungeonEncounterID"]): (int(r.get("JournalInstanceID") or 0), int(r.get("OrderIndex") or 0))
             for r in rows.values()}
    files: dict[int, tuple[int, int]] = {}
    for c in table_rows("JournalEncounterCreature"):
        r = rows.get(c.get("JournalEncounterID") or "")
        fdid, idx = int(c.get("FileDataID") or 0), int(c.get("OrderIndex") or 0)
        if r and fdid:
            enc = int(r["DungeonEncounterID"])
            if enc not in files or idx < files[enc][1]:
                files[enc] = (fdid, idx)
    return {k: v[0] for k, v in files.items()}, order


def path(encounter_id: int) -> Path | None:
    """The boss's portrait as PNG (downloaded and converted once); None when the Journal has none."""
    out = data_dir() / "bossimg" / f"{encounter_id}.png"
    if out.is_file():
        return out
    fdid = journal()[0].get(encounter_id)
    if not fdid:
        return None
    req = urllib.request.Request(CASC.format(fdid=fdid), headers={"User-Agent": "prep-a-fight"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        w, h, rgba = decode_blp(resp.read())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png(w, h, rgba))
    return out
