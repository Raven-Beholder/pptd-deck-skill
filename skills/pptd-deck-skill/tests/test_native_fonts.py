"""Bounded font inventory: family aliases, collections and corrupt offsets."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/local-export'))
from native_fonts import families


def font_bytes(name, table_offset=28):
    value = name.encode('utf-16-be')
    names = struct.pack('>HHH', 0, 1, 18) + struct.pack('>HHHHHH', 3, 1, 1033, 16, len(value), 0) + value
    return struct.pack('>4sHHHH', b'OTTO', 1, 0, 0, 0) + struct.pack('>4sIII', b'name', 0, table_offset, len(names)) + names


class FontInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'font.otf'

    def test_reads_unicode_typographic_family_without_loading_font_body(self):
        self.file.write_bytes(font_bytes('Test 字体'))
        self.assertEqual(families(self.file), {'Test 字体'})

    def test_collection_offsets_are_absolute_and_names_are_not_duplicated(self):
        first = font_bytes('Family A', 48)
        second_offset = 20 + len(first)
        second = font_bytes('Family B', second_offset + 28)
        self.file.write_bytes(struct.pack('>4sIIII', b'ttcf', 0x10000, 2, 20, second_offset) + first + second)
        self.assertEqual(families(self.file), {'Family A', 'Family B'})
        self.assertEqual(families(self.file, 0), {'Family A'})
        self.assertEqual(families(self.file, 1), {'Family B'})

    def test_corrupt_table_offsets_and_excessive_collection_counts_are_bounded(self):
        for data in (font_bytes('Broken', 1 << 30), b'ttcf' + struct.pack('>II', 0x10000, 100000), b'OTTO'):
            self.file.write_bytes(data)
            with self.subTest(data=data[:12]), self.assertRaises(ValueError):
                families(self.file)


if __name__ == '__main__': unittest.main()
