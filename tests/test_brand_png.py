"""Le immagini del marchio sono PNG validi 256x256 (firma, IHDR e CRC di ogni chunk)."""
import struct
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "images" / "logo.png",
    ROOT / "custom_components" / "consumi_sii" / "brand" / "icon.png",
    ROOT / "custom_components" / "consumi_sii" / "brand" / "logo.png",
]


class BrandPngTests(unittest.TestCase):
    def test_png_valid_and_square(self):
        for path in FILES:
            with self.subTest(path=path.name):
                data = path.read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                pos, chunks = 8, []
                while pos < len(data):
                    length, kind = struct.unpack(">I4s", data[pos:pos + 8])
                    body = data[pos + 8:pos + 8 + length]
                    crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
                    self.assertEqual(zlib.crc32(kind + body) & 0xFFFFFFFF, crc, kind)
                    chunks.append(kind)
                    if kind == b"IHDR":
                        self.assertEqual(struct.unpack(">II", body[:8]), (256, 256))
                    pos += 12 + length
                self.assertEqual(chunks[0], b"IHDR")
                self.assertEqual(chunks[-1], b"IEND")


if __name__ == "__main__":
    unittest.main()
