import base64
import struct
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
from werkzeug.exceptions import InternalServerError

from trytond.modules.wopi import wopi_proof


class TestWopiProof(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537,
            key_size=2048)
        cls.old_private_key = rsa.generate_private_key(public_exponent=65537,
            key_size=2048)
        numbers = cls.private_key.public_key().public_numbers()
        old_numbers = cls.old_private_key.public_key().public_numbers()
        cls.discovery = ElementTree.fromstring(
            ('<discovery><proof-key modulus="%s" exponent="%s" '
                'oldmodulus="%s" oldexponent="%s"/></discovery>') % (
                    cls._encode_number(numbers.n),
                    cls._encode_number(numbers.e),
                    cls._encode_number(old_numbers.n),
                    cls._encode_number(old_numbers.e)))

    @staticmethod
    def _encode_number(value):
        size = (value.bit_length() + 7) // 8
        return base64.b64encode(value.to_bytes(size, 'big')).decode()

    @staticmethod
    def _request(token, timestamp, proof, proof_old):
        builder = EnvironBuilder(
            method='GET', base_url='https://tryton.example.com',
            path='/onlyoffice/wopi/files/file-id',
            query_string={'access_token': token},
            headers={
                'X-WOPI-Proof': proof,
                'X-WOPI-ProofOld': proof_old,
                'X-WOPI-TimeStamp': str(timestamp),
                })
        return Request(builder.get_environ())

    @staticmethod
    def _expected(request, token, timestamp):
        token_bytes = token.encode()
        url_bytes = request.url.upper().encode()
        timestamp_bytes = struct.pack('>Q', timestamp)
        return b''.join((
            struct.pack('>I', len(token_bytes)), token_bytes,
            struct.pack('>I', len(url_bytes)), url_bytes,
            struct.pack('>I', len(timestamp_bytes)), timestamp_bytes))

    @classmethod
    def _proof(cls, request, token, timestamp):
        return base64.b64encode(cls.private_key.sign(
                cls._expected(request, token, timestamp),
                padding.PKCS1v15(), hashes.SHA256())).decode()

    @classmethod
    def _old_proof(cls, request, token, timestamp):
        return base64.b64encode(cls.old_private_key.sign(
                cls._expected(request, token, timestamp),
                padding.PKCS1v15(), hashes.SHA256())).decode()

    def test_valid_current_proof_is_accepted(self):
        token = 'signed-token'
        timestamp = wopi_proof.timestamp_now()
        unsigned_request = self._request(token, timestamp, '', '')
        proof = self._proof(unsigned_request, token, timestamp)
        request = self._request(token, timestamp, proof, proof)

        with (
                patch.object(wopi_proof, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(wopi_proof, 'get_office_discovery',
                    return_value=self.discovery)):
            wopi_proof.validate(request, token)

    def test_current_proof_signed_by_old_key_is_accepted(self):
        token = 'signed-token'
        timestamp = wopi_proof.timestamp_now()
        unsigned_request = self._request(token, timestamp, '', '')
        proof = self._old_proof(unsigned_request, token, timestamp)
        request = self._request(token, timestamp, proof, 'invalid')

        with (
                patch.object(wopi_proof, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(wopi_proof, 'get_office_discovery',
                    return_value=self.discovery)):
            wopi_proof.validate(request, token)

    def test_invalid_proofs_are_rejected(self):
        token = 'signed-token'
        timestamp = wopi_proof.timestamp_now()
        request = self._request(token, timestamp, 'invalid', 'invalid')

        with (
                patch.object(wopi_proof, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(wopi_proof, 'get_office_discovery',
                    return_value=self.discovery),
                self.assertRaises(InternalServerError)):
            wopi_proof.validate(request, token)

    def test_stale_timestamp_is_rejected(self):
        token = 'signed-token'
        timestamp = wopi_proof.timestamp_now() - 20 * 60 * 10_000_000 - 1
        unsigned_request = self._request(token, timestamp, '', '')
        proof = self._proof(unsigned_request, token, timestamp)
        request = self._request(token, timestamp, proof, proof)

        with (
                patch.object(wopi_proof, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(wopi_proof, 'get_office_discovery',
                    return_value=self.discovery),
                self.assertRaises(InternalServerError)):
            wopi_proof.validate(request, token)

    def test_missing_proof_is_rejected_when_discovery_has_keys(self):
        token = 'signed-token'
        timestamp = wopi_proof.timestamp_now()
        request = self._request(token, timestamp, '', '')

        with (
                patch.object(wopi_proof, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(wopi_proof, 'get_office_discovery',
                    return_value=self.discovery),
                self.assertRaises(InternalServerError)):
            wopi_proof.validate(request, token)

    def test_missing_proof_key_preserves_collabora_compatibility(self):
        token = 'signed-token'
        timestamp = wopi_proof.timestamp_now()
        request = self._request(token, timestamp, '', '')
        discovery = ElementTree.fromstring(b'<discovery/>')

        with (
                patch.object(wopi_proof, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(wopi_proof, 'get_office_discovery',
                    return_value=discovery),
                patch.object(wopi_proof, 'config_requires_proof',
                    return_value=False)):
            wopi_proof.validate(request, token)


del unittest
