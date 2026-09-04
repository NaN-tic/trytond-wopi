import base64
import binascii
import datetime as dt
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from werkzeug.exceptions import abort

import trytond.config as config

from .editor import (
    OfficeDiscoveryError, get_office_config_int, get_office_discovery,
    get_office_url)

PROOF_WINDOW_SECONDS = 20 * 60
TICKS_PER_SECOND = 10_000_000


def timestamp_now():
    value = dt.datetime.now(dt.timezone.utc) - dt.datetime(
        1, 1, 1, tzinfo=dt.timezone.utc)
    return ((value.days * 86400 + value.seconds) * TICKS_PER_SECOND
        + value.microseconds * 10)


def _key(element, prefix=''):
    try:
        modulus = int.from_bytes(base64.b64decode(
            element.attrib[prefix + 'modulus'], validate=True), 'big')
        exponent = int.from_bytes(base64.b64decode(
            element.attrib[prefix + 'exponent'], validate=True), 'big')
        return rsa.RSAPublicNumbers(exponent, modulus).public_key()
    except (KeyError, ValueError, binascii.Error, TypeError):
        abort(500)


def _proof_data(request, access_token, timestamp):
    token = access_token.encode('utf-8')
    url = request.url.upper().encode('utf-8')
    timestamp_bytes = struct.pack('>Q', timestamp)
    return b''.join((
        struct.pack('>I', len(token)), token,
        struct.pack('>I', len(url)), url,
        struct.pack('>I', len(timestamp_bytes)), timestamp_bytes))


def _verify(public_key, proof, expected):
    try:
        signature = base64.b64decode(proof, validate=True)
        public_key.verify(signature, expected, padding.PKCS1v15(),
            hashes.SHA256())
    except (InvalidSignature, ValueError, binascii.Error, TypeError):
        return False
    return True


def validate(request, access_token):
    """Validate WOPI proof headers against the configured office discovery."""
    office_url = get_office_url()
    if not office_url:
        abort(500)
    try:
        discovery = get_office_discovery(
            office_url, get_office_config_int('discovery_timeout', default=10))
    except OfficeDiscoveryError:
        abort(503)
    proof_key = next(discovery.iter('proof-key'), None)
    if proof_key is None:
        if config_requires_proof():
            abort(500)
        return

    proof = request.headers.get('X-WOPI-Proof', '')
    proof_old = request.headers.get('X-WOPI-ProofOld', '')
    timestamp = request.headers.get('X-WOPI-TimeStamp', '')
    if not proof or not proof_old or not timestamp:
        abort(500)
    try:
        timestamp_value = int(timestamp)
    except ValueError:
        abort(500)
    if abs(timestamp_now() - timestamp_value) > (
            PROOF_WINDOW_SECONDS * TICKS_PER_SECOND):
        abort(500)

    expected = _proof_data(request, access_token, timestamp_value)
    current_key = _key(proof_key)
    old_key = _key(proof_key, 'old')
    if not (_verify(current_key, proof, expected)
            or _verify(current_key, proof_old, expected)
            or _verify(old_key, proof, expected)):
        abort(500)


def config_requires_proof():
    return config.getboolean('wopi', 'require_proof', default=True)
