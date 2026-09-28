"""Build a signed APK that claims a package name and holds it forever.

Android will not replace an installed package with one signed by a different
key. An apk that declares a package name, contains no code, and is signed with
a key nobody has is therefore a permanent lock on that name: the real app can
never be installed over it, by the Play Store or anything else.

This is how the developer-verification component is kept off a device that
does not want it. The apk is generated once, committed, and never regenerated
-- the private key is discarded at the end of this script and is not recorded
anywhere, which is the point. Regenerating it would produce a different key
and a package that is no longer the one people have installed.

Usage: mkblocker.py <package-name> <label> <out.apk>
"""

import base64
import struct
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---- binary XML -----------------------------------------------------------

RES_XML_TYPE = 0x0003
CHUNK_STRING_POOL = 0x0001
CHUNK_RESOURCE_MAP = 0x0180
CHUNK_START_NS = 0x0100
CHUNK_END_NS = 0x0101
CHUNK_START_ELEMENT = 0x0102
CHUNK_END_ELEMENT = 0x0103

TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_BOOLEAN = 0x12

ANDROID_NS = "http://schemas.android.com/apk/res/android"

# Framework attribute ids. These never change; that is the whole reason
# attributes are referenced by id rather than by name.
ATTRS = [
    ("versionCode", 0x0101021B),
    ("versionName", 0x0101021C),
    ("minSdkVersion", 0x0101020C),
    ("targetSdkVersion", 0x01010270),
    ("hasCode", 0x0101000C),
    ("label", 0x01010001),
]
NO_ENTRY = 0xFFFFFFFF


class Pool:
    """String pool. Attribute names come first: the resource map is indexed by
    pool position, so the two have to line up."""

    def __init__(self):
        self.items = []
        for name, _ in ATTRS:
            self.add(name)

    def add(self, s: str) -> int:
        if s not in self.items:
            self.items.append(s)
        return self.items.index(s)

    def chunk(self) -> bytes:
        offsets, data = [], bytearray()
        for s in self.items:
            offsets.append(len(data))
            encoded = s.encode("utf-16-le")
            data += struct.pack("<H", len(s)) + encoded + b"\x00\x00"
        while len(data) % 4:
            data += b"\x00"
        header = 28
        strings_start = header + 4 * len(self.items)
        size = strings_start + len(data)
        return (struct.pack("<HHIIIIII", CHUNK_STRING_POOL, header, size,
                            len(self.items), 0, 0, strings_start, 0)
                + struct.pack(f"<{len(offsets)}I", *offsets) + bytes(data))


def resource_map() -> bytes:
    ids = [rid for _, rid in ATTRS]
    return (struct.pack("<HHI", CHUNK_RESOURCE_MAP, 8, 8 + 4 * len(ids))
            + struct.pack(f"<{len(ids)}I", *ids))


def node(kind: int, ext: bytes) -> bytes:
    return struct.pack("<HHIII", kind, 16, 16 + len(ext), 0, NO_ENTRY) + ext


def attribute(ns: int, name: int, raw: int, dtype: int, data: int) -> bytes:
    return struct.pack("<IIIHBBI", ns, name, raw, 8, 0, dtype, data)


def start_element(ns: int, name: int, attrs: list[bytes]) -> bytes:
    ext = struct.pack("<IIHHHHHH", ns, name, 20, 20, len(attrs), 0, 0, 0)
    return node(CHUNK_START_ELEMENT, ext + b"".join(attrs))


def end_element(ns: int, name: int) -> bytes:
    return node(CHUNK_END_ELEMENT, struct.pack("<II", ns, name))


def manifest_xml(package: str, label: str, version_code: int,
                 version_name: str) -> bytes:
    p = Pool()
    android = p.add("android")
    ns_uri = p.add(ANDROID_NS)
    s_package = p.add("package")
    s_manifest = p.add("manifest")
    s_uses_sdk = p.add("uses-sdk")
    s_application = p.add("application")
    v_package = p.add(package)
    v_version = p.add(version_name)
    v_label = p.add(label)

    i = {name: n for n, (name, _) in enumerate(ATTRS)}

    manifest_attrs = [
        attribute(ns_uri, i["versionCode"], NO_ENTRY, TYPE_INT_DEC, version_code),
        attribute(ns_uri, i["versionName"], v_version, TYPE_STRING, v_version),
        attribute(NO_ENTRY, s_package, v_package, TYPE_STRING, v_package),
    ]
    # Staying under API 28 keeps a v1 signature sufficient. Nothing here runs,
    # so the target level costs nothing.
    sdk_attrs = [
        attribute(ns_uri, i["minSdkVersion"], NO_ENTRY, TYPE_INT_DEC, 21),
        attribute(ns_uri, i["targetSdkVersion"], NO_ENTRY, TYPE_INT_DEC, 27),
    ]
    app_attrs = [
        attribute(ns_uri, i["hasCode"], NO_ENTRY, TYPE_INT_BOOLEAN, 0),
        attribute(ns_uri, i["label"], v_label, TYPE_STRING, v_label),
    ]

    body = (node(CHUNK_START_NS, struct.pack("<II", android, ns_uri))
            + start_element(NO_ENTRY, s_manifest, manifest_attrs)
            + start_element(NO_ENTRY, s_uses_sdk, sdk_attrs)
            + end_element(NO_ENTRY, s_uses_sdk)
            + start_element(NO_ENTRY, s_application, app_attrs)
            + end_element(NO_ENTRY, s_application)
            + end_element(NO_ENTRY, s_manifest)
            + node(CHUNK_END_NS, struct.pack("<II", android, ns_uri)))

    payload = p.chunk() + resource_map() + body
    return struct.pack("<HHI", RES_XML_TYPE, 8, 8 + len(payload)) + payload


# ---- signing --------------------------------------------------------------

def digest(data: bytes) -> str:
    from hashlib import sha256
    return base64.b64encode(sha256(data).digest()).decode()


def jar_sections(entries: dict[str, bytes]) -> tuple[bytes, bytes]:
    """Return MANIFEST.MF and the CERT.SF that attests to it."""
    head = b"Manifest-Version: 1.0\r\nCreated-By: 306gapps mkblocker\r\n\r\n"
    manifest = bytearray(head)
    sf_sections = bytearray()
    for name, data in entries.items():
        section = f"Name: {name}\r\nSHA-256-Digest: {digest(data)}\r\n\r\n".encode()
        manifest += section
        # The signature file attests to each manifest section, not to the file.
        sf_sections += (f"Name: {name}\r\n"
                        f"SHA-256-Digest: {digest(section)}\r\n\r\n").encode()

    sf = (b"Signature-Version: 1.0\r\nCreated-By: 306gapps mkblocker\r\n"
          + f"SHA-256-Digest-Manifest: {digest(bytes(manifest))}\r\n".encode()
          + f"SHA-256-Digest-Manifest-Main-Attributes: {digest(head)}\r\n".encode()
          + b"\r\n" + bytes(sf_sections))
    return bytes(manifest), sf


def sign(sf: bytes, subject: str):
    """Sign with a throwaway key and return (pkcs7, certificate_pem).

    The key is created here and never leaves this function. Discarding it is
    deliberate: a key nobody holds is a package name nobody can take back.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs7
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, subject),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "306gapps"),
    ])
    not_before = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(1)
            .not_valid_before(not_before)
            .not_valid_after(not_before + timedelta(days=365 * 60))
            .sign(key, hashes.SHA256()))

    p7 = (pkcs7.PKCS7SignatureBuilder()
          .set_data(sf)
          .add_signer(cert, key, hashes.SHA256())
          .sign(serialization.Encoding.DER,
                [pkcs7.PKCS7Options.DetachedSignature,
                 pkcs7.PKCS7Options.Binary,
                 pkcs7.PKCS7Options.NoAttributes]))
    return p7, cert.public_bytes(serialization.Encoding.PEM)


def write_apk(path: Path, entries: dict[str, bytes], subject: str) -> bytes:
    manifest_mf, sf = jar_sections(entries)
    p7, cert_pem = sign(sf, subject)

    fixed = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in [("META-INF/MANIFEST.MF", manifest_mf),
                           ("META-INF/CERT.SF", sf),
                           ("META-INF/CERT.RSA", p7)] + list(entries.items()):
            info = zipfile.ZipInfo(name, fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return cert_pem


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    package, label, out = argv[1], argv[2], Path(argv[3])

    xml = manifest_xml(package, label, 2100000000, "blocked")
    cert_pem = write_apk(out, {"AndroidManifest.xml": xml}, package)
    out.with_suffix(".pem").write_bytes(cert_pem)

    # Read it back with the same parser the manifest builder uses. A blocker
    # that does not parse is a blocker that does not block.
    sys.path.insert(0, str(Path(__file__).parent))
    from axml import manifest_attributes
    with zipfile.ZipFile(out) as z:
        got = manifest_attributes(z.read("AndroidManifest.xml"))
    if got.get("package") != package:
        print(f"error: wrote {package} but read back {got}", file=sys.stderr)
        return 1

    print(f"{out}  {out.stat().st_size} bytes")
    print(f"  package     {got['package']}")
    print(f"  versionCode {got['versionCode']}")
    print(f"  certificate {out.with_suffix('.pem')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
