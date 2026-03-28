"""
Generate simple placeholder icons for the Agora extension.
Run once: python make_icons.py
"""
import struct, zlib, os

def make_png(size, color=(26, 91, 92)):
    """Generate a minimal solid-color PNG."""
    def chunk(name, data):
        c = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)

    r, g, b = color
    raw = b""
    for _ in range(size):
        row = b"\x00" + bytes([r, g, b, 255] * size)
        raw += row

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    compressed = zlib.compress(raw)
    idat = chunk(b"IDAT", compressed)
    iend = chunk(b"IEND", b"")

    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend

os.makedirs("icons", exist_ok=True)
for size in [16, 48, 128]:
    with open(f"icons/icon{size}.png", "wb") as f:
        f.write(make_png(size, color=(26, 58, 92)))
    print(f"Created icons/icon{size}.png")

print("Icons created.")
