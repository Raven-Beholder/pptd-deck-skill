"""Local PNG/JPEG bytes and aspect-preserving placement. See NATIVE_NOTICE.md."""
import hashlib
import struct
from native_common import NativeExportError, choice, fields, number, project_path

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_MEDIA_BYTES = 200 * 1024 * 1024


def image_size(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 33 and data[12:16] == b'IHDR':
        width, height = struct.unpack('>II', data[16:24])
        kind = 'png'
    elif data.startswith(b'\xff\xd8'):
        offset, width, height, kind = 2, 0, 0, 'jpeg'
        # JPEG marker lengths include their own two-byte length field.
        while offset < len(data):
            if data[offset] != 255:
                break
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xD9, 0xDA):
                break
            if marker in (0x01, *range(0xD0, 0xD9)):
                continue
            if offset + 2 > len(data):
                break
            length = int.from_bytes(data[offset:offset + 2], 'big')
            if length < 2 or offset + length > len(data):
                break
            if marker in (0xC0, 0xC1, 0xC2) and length >= 8:
                height, width = struct.unpack('>HH', data[offset + 3:offset + 7])
                break
            offset += length
    else:
        raise NativeExportError('native-v1 supports PNG and baseline/progressive JPEG media only')
    if not width or not height or width * height > 100_000_000:
        raise NativeExportError('invalid or oversized image dimensions')
    return width, height, kind


class Media:
    def __init__(self, root, package):
        self.root, self.package = root, package
        self.cache = {}
        self.total = 0

    def load(self, source):
        path = project_path(self.root, source)
        if path not in self.cache:
            with path.open('rb') as stream:
                data = stream.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise NativeExportError('image exceeds 20 MiB')
            width, height, kind = image_size(data)
            part = 'ppt/media/' + hashlib.sha256(data).hexdigest() + '.' + kind
            if part not in self.package.parts:
                self.total += len(data)
                if self.total > MAX_MEDIA_BYTES:
                    raise NativeExportError('embedded media exceeds 200 MiB')
                self.package.add(part, data, 'image/' + kind)
            self.cache[path] = part, width, height
        return self.cache[path]


def placement(bounds, dimensions, fit, crop):
    fields(fit, 'mode', 'image.fit')
    mode = choice(fit.get('mode', 'cover'), ('cover', 'contain', 'fill'), 'image.fit.mode')
    fields(crop, 'left top right bottom', 'image.crop')
    left, top, right, bottom = [number(crop.get(k, 0), f'crop.{k}', -21474.83648, 21474.83647)
                                for k in ('left', 'top', 'right', 'bottom')]
    if left + right >= 1 or top + bottom >= 1:
        raise NativeExportError('image crop removes the entire source')
    x, y, width, height = bounds
    source_width, source_height = dimensions
    ratio = source_width * (1 - left - right) / (source_height * (1 - top - bottom))
    target_ratio = width / height
    if mode == 'cover':
        if ratio > target_ratio:
            inset = (1 - left - right) * (1 - target_ratio / ratio) / 2
            left, right = left + inset, right + inset
        else:
            inset = (1 - top - bottom) * (1 - ratio / target_ratio) / 2
            top, bottom = top + inset, bottom + inset
    elif mode == 'contain':
        # Expand the source rectangle with transparent margins, retaining bounds
        # so borders, rotation centers and selection geometry remain compatible.
        if ratio > target_ratio:
            outset = (1 - top - bottom) * (ratio / target_ratio - 1) / 2
            top, bottom = top - outset, bottom - outset
        else:
            outset = (1 - left - right) * (target_ratio / ratio - 1) / 2
            left, right = left - outset, right - outset
    # ST_Percentage is a signed 32-bit integer; reject unrepresentable outsets.
    percentages = [round(number(v * 100000, 'computed crop', -2147483648, 2147483647))
                   for v in (left, top, right, bottom)]
    return [x, y, width, height], dict(zip(('l', 't', 'r', 'b'), percentages))
