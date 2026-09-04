"""Signed WOPI capabilities for stable document identifiers.

The file identifier contains only the document identity so all users share the
same WOPISrc.  The signed access token contains the user-specific permissions.
Its lifetime is managed by ``wopi.lease``.
"""
import base64
import binascii
import hashlib
import hmac
import json
import secrets

from werkzeug.exceptions import abort

from .editor import get_wopi_config


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _decode(value):
    padding = '=' * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode('ascii'))


def _secret():
    secret = get_wopi_config('secret', default='')
    if len(secret.encode('utf-8')) < 32:
        raise RuntimeError(
            'wopi.secret must contain at least 32 bytes')
    return secret.encode('utf-8')


def _signature(database, file_id, token_claim):
    return _encode(hmac.new(
            _secret(), ('%s:%s:%s' % (
                    database, file_id, token_claim)).encode('ascii'),
            hashlib.sha256).digest())


def make(database, user, model, record, field, writable, name):
    file_claim = {
        'database': database,
        'field': field,
        'model': model,
        'record': record,
        }
    token_claim = {
        'name': name,
        'nonce': secrets.token_urlsafe(16),
        'user': user,
        'writable': bool(writable),
        }
    file_id = _encode(json.dumps(
            file_claim, sort_keys=True,
            separators=(',', ':')).encode('utf-8'))
    token_claim = _encode(json.dumps(
            token_claim, sort_keys=True,
            separators=(',', ':')).encode('utf-8'))
    access_token = '%s.%s' % (
        token_claim, _signature(database, file_id, token_claim))
    return file_id, access_token


def check(database, file_id, access_token):
    try:
        token_claim, separator, signature = access_token.partition('.')
        if (not separator or not hmac.compare_digest(
                    _signature(database, file_id, token_claim), signature)):
            raise ValueError
        file_claim = json.loads(_decode(file_id))
        token_claim = json.loads(_decode(token_claim))
        if (set(file_claim) != {'database', 'field', 'model', 'record'}
                or file_claim['database'] != database
                or set(token_claim) != {'name', 'nonce', 'user', 'writable'}
                or not isinstance(token_claim['nonce'], str)):
            raise ValueError
    except (TypeError, ValueError, UnicodeError, binascii.Error,
            json.JSONDecodeError):
        abort(401)
    return file_claim | token_claim
