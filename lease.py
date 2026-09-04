import datetime as dt
import hashlib

from trytond.model import ModelSQL, ModelView, Unique, fields

from .editor import get_wopi_config_int


class WopiLease(ModelSQL, ModelView):
    """The lifetime of a WOPI capability while a document is in use."""
    __name__ = 'wopi.lease'

    token_id = fields.Char('Token ID', required=True)
    expires_at = fields.DateTime('Expires At', required=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints += [
            ('token_id_unique', Unique(table, table.token_id),
                'wopi.msg_lease_token_unique'),
            ]

    @staticmethod
    def lease_time():
        token_lifetime = get_wopi_config_int('token_lifetime', default=1800)
        return get_wopi_config_int('lease_time', default=token_lifetime)

    @staticmethod
    def get_token_id(access_token):
        return hashlib.sha256(access_token.encode('ascii')).hexdigest()

    @classmethod
    def start(cls, access_token):
        now = dt.datetime.utcnow()
        expired = cls.search([('expires_at', '<=', now)])
        if expired:
            cls.delete(expired)
        cls.create([{
                    'token_id': cls.get_token_id(access_token),
                    'expires_at': now + dt.timedelta(seconds=cls.lease_time()),
                    }])

    @classmethod
    def renew(cls, access_token):
        now = dt.datetime.utcnow()
        leases = cls.search([
                ('token_id', '=', cls.get_token_id(access_token)),
                ], limit=1)
        if not leases or leases[0].expires_at <= now:
            return False
        cls.write(leases, {
                'expires_at': now + dt.timedelta(seconds=cls.lease_time()),
                })
        return True
