"""Read the package name out of an Android binary XML manifest.

An apk's AndroidManifest.xml is compiled, so the package id cannot be grepped
out reliably -- the string pool holds plenty of other things that look like
package names. This walks the chunks far enough to read the `package`
attribute of the manifest element, which is all we need.
"""

import struct

CHUNK_STRING_POOL = 0x0001
CHUNK_START_ELEMENT = 0x0102
FLAG_UTF8 = 1 << 8


class MalformedAXML(Exception):
    pass


def _string_pool(data: bytes, off: int) -> list[str]:
    kind, header_size, size = struct.unpack_from("<HHI", data, off)
    if kind != CHUNK_STRING_POOL:
        raise MalformedAXML("expected a string pool")
    count, _style_count, flags, strings_start, _styles_start = struct.unpack_from(
        "<IIIII", data, off + 8)
    utf8 = bool(flags & FLAG_UTF8)

    offsets = struct.unpack_from(f"<{count}I", data, off + header_size)
    base = off + strings_start
    out = []
    for o in offsets:
        p = base + o
        if utf8:
            # Two lengths (characters, then bytes), each 1 or 2 bytes.
            n = data[p]
            p += 2 if n & 0x80 else 1
            n = data[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p + 1]
                p += 2
            else:
                p += 1
            out.append(data[p:p + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", data, p)[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p)[0]
                p += 2
            out.append(data[p:p + n * 2].decode("utf-16-le", "replace"))
    return out


def package_name(manifest: bytes) -> str:
    """Return the package id declared by a compiled AndroidManifest.xml."""
    if len(manifest) < 8:
        raise MalformedAXML("too short")

    _magic, _size = struct.unpack_from("<II", manifest, 0)
    strings = _string_pool(manifest, 8)

    off = 8
    while off + 8 <= len(manifest):
        kind, header_size, size = struct.unpack_from("<HHI", manifest, off)
        if size == 0:
            raise MalformedAXML("zero-length chunk")
        if kind == CHUNK_START_ELEMENT:
            # A node is: chunk header (8) + lineNumber (4) + comment (4).
            # The attribute extension follows, and attributeStart is measured
            # from the start of that extension, not from the chunk.
            ext = off + 16
            attr_start, attr_size, attr_count = struct.unpack_from("<HHH", manifest, ext + 8)
            base = ext + attr_start
            for i in range(attr_count):
                a = base + i * attr_size
                if a + 12 > len(manifest):
                    break
                _ns, name_idx, raw_idx = struct.unpack_from("<III", manifest, a)
                if name_idx < len(strings) and strings[name_idx] == "package":
                    if raw_idx < len(strings):
                        return strings[raw_idx]
            raise MalformedAXML("manifest element declares no package")
        off += size
    raise MalformedAXML("no start element found")
