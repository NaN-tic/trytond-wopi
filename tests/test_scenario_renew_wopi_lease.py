import base64
import datetime as dt
import unittest
from unittest.mock import patch

from proteus import Model
from trytond.modules.wopi import routes, wopi_token
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction
from trytond.wsgi import app
from werkzeug.test import Client
from werkzeug.wrappers import Response


class TestRenewWopiLease(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('wopi')

        Attachment = Model.get('ir.attachment')
        User = Model.get('res.user')
        attachment = Attachment(
            name='document.odt', type='data', data=b'document',
            resource=User(config.user))
        attachment.save()
        attachment_id = attachment.id
        attachment_name = attachment.name
        user = User(config.user)
        user_login = user.login
        user.password = 'collabora-test-password'
        user.save()

        secret = b'wopi-test-secret-with-at-least-32-bytes'
        with (
                patch.object(wopi_token, '_secret', return_value=secret),
                patch.object(routes, 'validate_wopi_proof'),
                patch(
                    'trytond.modules.wopi.lease.WopiLease.lease_time',
                    return_value=600),
                patch.object(routes, 'get_wopi_url',
                    return_value='https://tryton.example.com'),
                patch.object(routes, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(routes, '_editor_action_url',
                    return_value='https://office.example.com/edit')):
            client = Client(app, Response)
            authorization = 'Basic ' + base64.b64encode(
                ('%s:collabora-test-password' % user_login).encode()
                ).decode()
            response = client.get(
                '/%s/collabora/open/ir.attachment/%s/data?name=%s' % (
                    config.database_name, attachment_id, attachment_name),
                headers={'Authorization': authorization})
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'access_token_ttl" value="0', response.data)

            with Transaction().start(config.database_name, config.user):
                Lease = Pool().get('wopi.lease')
                leases = Lease.search([])
                self.assertEqual(len(leases), 1)
                Lease.delete(leases)

            with Transaction().start(
                    config.database_name, config.user,
                    context=config.context):
                Lease = Pool().get('wopi.lease')
                file_id, access_token = wopi_token.make(
                    config.database_name, config.user, 'ir.attachment',
                    attachment_id, 'data', True, attachment_name)
                Lease.start(access_token)
                lease, = Lease.search([
                        ('token_id', '=', Lease.get_token_id(access_token)),
                        ])
                Lease.write([lease], {
                        'expires_at': dt.datetime.utcnow()
                        + dt.timedelta(seconds=5),
                        })
            url = '/%s/wopi/files/%s?access_token=%s' % (
                config.database_name, file_id, access_token)
            response = client.get(url)
            self.assertEqual(response.status_code, 200)

            with Transaction().start(config.database_name, config.user):
                Lease = Pool().get('wopi.lease')
                lease, = Lease.search([
                        ('token_id', '=', Lease.get_token_id(access_token)),
                        ])
                self.assertGreater(
                    lease.expires_at,
                    dt.datetime.utcnow() + dt.timedelta(seconds=590))
                Lease.write([lease], {
                        'expires_at': dt.datetime.utcnow()
                        + dt.timedelta(seconds=5),
                        })

                other_file_id, other_access_token = wopi_token.make(
                    config.database_name, config.user + 1, 'ir.attachment',
                    attachment_id, 'data', True, attachment_name)
                Lease.start(other_access_token)
                self.assertEqual(other_file_id, file_id)
                self.assertNotEqual(other_access_token, access_token)
                self.assertEqual(len(Lease.search([])), 2)
                self.assertEqual(wopi_token.check(
                        config.database_name, other_file_id,
                        other_access_token)['user'], config.user + 1)

            response = client.get(url.replace('?access_token=',
                    '/contents?access_token='))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'document')

            with Transaction().start(config.database_name, config.user):
                Lease = Pool().get('wopi.lease')
                lease, = Lease.search([
                        ('token_id', '=', Lease.get_token_id(access_token)),
                        ])
                self.assertGreater(
                    lease.expires_at,
                    dt.datetime.utcnow() + dt.timedelta(seconds=590))
                Lease.write([lease], {
                        'expires_at': dt.datetime.utcnow()
                        - dt.timedelta(seconds=1),
                        })

            response = client.get(url)
            self.assertEqual(response.status_code, 401)
