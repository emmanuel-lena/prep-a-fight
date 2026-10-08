import struct

from paf import bossimg


def blp(w: int, h: int, comp: int, adepth: int, atype: int, data: bytes) -> bytes:
    head = struct.pack("<4sIBBBBII", b"BLP2", 1, comp, adepth, atype, 0, w, h)
    offsets = struct.pack("<16I", 1172, *([0] * 15))
    sizes = struct.pack("<16I", len(data), *([0] * 15))
    return head + offsets + sizes + bytes(1172 - 148) + data


def test_uncompressed_and_dxt1_decode():
    w, h, px = bossimg.decode_blp(blp(1, 1, 3, 8, 0, bytes((10, 20, 30, 40))))  # BGRA
    assert (w, h, px) == (1, 1, bytes((30, 20, 10, 40)))
    # one DXT1 block, every texel color 0 = pure red (565: 0xF800)
    w, h, px = bossimg.decode_blp(blp(4, 4, 2, 0, 0, struct.pack("<HHI", 0xF800, 0x0000, 0)))
    assert (w, h) == (4, 4) and px[:4] == bytes((255, 0, 0, 255)) and len(px) == 64


def test_png_is_a_png():
    data = bossimg.png(2, 1, bytes((255, 0, 0, 255, 0, 255, 0, 128)))
    assert data.startswith(bytes((0x89,)) + b"PNG") and b"IHDR" in data and data[-8:-4] == b"IEND"
