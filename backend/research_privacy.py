"""Conservative local preparation, not irreversible anonymisation."""
import hashlib
import hmac
import re
import unicodedata

VERSION = 'direct-identifiers-v1'
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[\w-]+', re.UNICODE)
MENTION = re.compile(r'(?<!\w)@[\w.]+', re.UNICODE)
URL = re.compile(r'(?i)\b(?:https?://|www\.)\S+')
PHONE = re.compile(r'(?<!\w)(?:\+?\d[\d ()-]{6,}\d)(?!\w)')
LONG_ID = re.compile(r'(?<!\w)\d{7,}(?!\w)')


def prepare_record(raw, study_id, secret, *, max_length=4000):
    """Return an explicit allowlist. Never retain author, original ID or payload."""
    identity = raw.get('record_id')
    text = raw.get('text')
    if (not isinstance(identity, str) or not identity or len(identity) > 200
            or not isinstance(text, str) or not text.strip() or len(text) > max_length):
        return None
    text = unicodedata.normalize('NFC', text).strip()
    if any(unicodedata.category(char) == 'Cc' and char not in '\n\r\t' for char in text):
        return None
    redactions = 0
    for pattern, replacement in ((URL, '[enlace]'), (EMAIL, '[correo]'),
                                 (MENTION, '[mención]'), (PHONE, '[teléfono]'), (LONG_ID, '[identificador]')):
        text, count = pattern.subn(replacement, text)
        redactions += count
    # Content consisting only of direct identifiers has no useful prepared text.
    remaining = re.sub(r'\[[^\]]+\]', '', text)
    if not any(char.isalpha() for char in remaining):
        return None
    key = hmac.new(bytes.fromhex(secret),
                   f'{study_id}\0{raw["publication_id"]}\0{identity}'.encode(), hashlib.sha256).hexdigest()
    return {'record_key': key, 'publication_id': raw['publication_id'], 'text': text,
            'synthetic': True, 'privacy_version': VERSION, 'redactions': redactions}
