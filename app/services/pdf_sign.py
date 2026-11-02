import secrets
import threading
import time

from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko import stamp
from pyhanko.pdf_utils.font.opentype import GlyphAccumulatorFactory
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.text import TextBoxStyle
from pyhanko.sign import fields, signers
from pyhanko_certvalidator.registry import SimpleCertificateStore

from .font_match import FontLibrary, family_key

CERT_TTL = 15 * 60
MAX_CERT_BYTES = 64 * 1024
STAMP_FONTS = ('DejaVu Sans', 'Liberation Sans', 'Arial', 'Noto Sans', 'Segoe UI')
FIELD_NAME = 'Signature'


class SignError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def der(certificate):
    return asn1_x509.Certificate.load(certificate.public_bytes(serialization.Encoding.DER))


def load_signer(data, password):
    try:
        key, certificate, extra = pkcs12.load_key_and_certificates(data, password.encode() if password else None)
    except ValueError as e:
        raise SignError('err_cert_password', str(e)) from e
    except Exception as e:
        raise SignError('err_cert_invalid', str(e)) from e
    if key is None or certificate is None:
        raise SignError('err_cert_invalid', 'The file has no private key and certificate')
    private = asn1_keys.PrivateKeyInfo.load(key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    registry = SimpleCertificateStore.from_certs([der(c) for c in extra or []])
    return signers.SimpleSigner(signing_cert=der(certificate), signing_key=private, cert_registry=registry), certificate


def describe(certificate):
    subject = certificate.subject.rfc4514_string()
    names = [a.value for a in certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)]
    return {'name': names[0] if names else subject, 'subject': subject, 'valid_to': certificate.not_valid_after_utc.isoformat()}


class CertificateStore:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()

    def prune(self):
        now = time.time()
        for key in [k for k, v in self.items.items() if v['expires'] < now]:
            del self.items[key]

    def put(self, owner, data, password):
        if len(data) > MAX_CERT_BYTES:
            raise SignError('err_cert_invalid', 'The file is too large')
        _signer, certificate = load_signer(data, password)
        cert_id = secrets.token_urlsafe(18)
        with self.lock:
            self.prune()
            self.items[cert_id] = {'owner': owner, 'data': data, 'password': password, 'expires': time.time() + CERT_TTL}
        return cert_id, describe(certificate)

    def take(self, cert_id, owner):
        with self.lock:
            self.prune()
            item = self.items.get(cert_id)
            if not item or item['owner'] != owner:
                return None
            del self.items[cert_id]
        return item['data'], item['password']


CERTIFICATES = CertificateStore()


def stamp_font():
    library = FontLibrary.shared().load()
    for name in STAMP_FONTS:
        entry = library.styled(family_key(name), False, False)
        if entry and not entry['number'] and entry['path'].lower().endswith(('.ttf', '.otf')):
            return entry['path']
    return None


def sign_pdf(source, target, certificate, placement):
    signer, _certificate = load_signer(*certificate)
    font = stamp_font()
    text_style = TextBoxStyle(font=GlyphAccumulatorFactory(font), font_size=9) if font else TextBoxStyle(font_size=9)
    style = stamp.TextStampStyle(stamp_text='%(signer)s\n%(ts)s', text_box_style=text_style, border_width=1)
    meta = signers.PdfSignatureMetadata(
        field_name=FIELD_NAME, subfilter=fields.SigSeedSubFilter.PADES, md_algorithm='sha256',
        reason=placement.get('reason') or None, location=placement.get('location') or None,
    )
    with open(source, 'rb') as handle:
        writer = IncrementalPdfFileWriter(handle, strict=False)
        fields.append_signature_field(writer, fields.SigFieldSpec(FIELD_NAME, on_page=placement['page'], box=placement['box']))
        with open(target, 'wb') as out:
            signers.PdfSigner(meta, signer=signer, stamp_style=style).sign_pdf(writer, output=out)
    return target
