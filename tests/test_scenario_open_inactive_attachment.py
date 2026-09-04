import base64
import json
import unittest
from unittest.mock import patch

from proteus import Model
from trytond.modules.wopi import routes, wopi_token
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.wsgi import app
from werkzeug.test import Client
from werkzeug.wrappers import Response


class TestOpenInactiveAttachment(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules(['wopi', 'office'])

        Attachment = Model.get('ir.attachment', config=config)
        User = Model.get('res.user', config=config)
        attachment = Attachment(
            name='document.odt', type='data', data=b'document',
            resource=User(config.user), active=False)
        attachment.save()
        user = User(config.user)
        user.password = 'collabora-test-password'
        user.save()

        secret = b'wopi-test-secret-with-at-least-32-bytes'
        with (
                patch.object(wopi_token, '_secret', return_value=secret),
                patch.object(routes, 'validate_wopi_proof'),
                patch.object(routes, 'get_wopi_url',
                    return_value='https://tryton.example.com'),
                patch.object(routes, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(routes, '_editor_action_url',
                    return_value='https://office.example.com/edit')):
            client = Client(app, Response)
            authorization = 'Basic ' + base64.b64encode(
                ('%s:collabora-test-password' % user.login).encode()
                ).decode()
            response = client.get(
                '/%s/collabora/open/ir.attachment/%s/data?name=%s' % (
                    config.database_name, attachment.id, attachment.name),
                headers={'Authorization': authorization})
            self.assertEqual(response.status_code, 200)
            access_token = response.data.split(
                b'name="access_token" value="', 1)[1].split(b'"', 1)[0]
            access_token = access_token.decode()
            file_id = wopi_token.make(
                config.database_name, config.user, 'ir.attachment',
                attachment.id, 'data', False, attachment.name)[0]
            url = '/%s/wopi/files/%s?access_token=%s' % (
                config.database_name, file_id, access_token)

            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            information = json.loads(response.data)
            self.assertTrue(information['ReadOnly'])
            self.assertFalse(information['UserCanWrite'])

            response = client.post(
                url.replace('?access_token=', '/contents?access_token='),
                data=b'changed', headers={'X-WOPI-Override': 'PUT'})
            self.assertEqual(response.status_code, 403)
