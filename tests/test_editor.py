import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree

from trytond.modules.wopi import editor, routes


class TestEditor(unittest.TestCase):

    def test_editor_url_uses_web_base_url(self):
        def get_config(section, option, default=None):
            values = {
                ('web', 'base_url'): 'http://localhost:8023',
                ('wopi', 'url'): 'http://172.17.0.1:8023',
            }
            return values.get((section, option), default)

        transaction = SimpleNamespace(
            database=SimpleNamespace(name='onlyoffice'))
        with (
                patch.object(editor.config, 'get', side_effect=get_config),
                patch.object(editor, 'Transaction',
                    return_value=transaction)):
            url = editor.get_editor_url(
                'ir.attachment', 1, 'data', 'unnamed document.docx')

        self.assertTrue(url.startswith(
            'http://localhost:8023/onlyoffice/wopi/open/'))

    def test_office_url_uses_office_configuration(self):
        def get_config(section, option, default=None):
            values = {
                ('office', 'url'): 'https://office.example.com',
                ('wopi', 'url'): 'https://tryton.example.com',
            }
            return values.get((section, option), default)

        with patch.object(editor.config, 'get', side_effect=get_config):
            self.assertEqual(
                editor.get_office_url(),
                'https://office.example.com')
            self.assertEqual(
                editor.get_wopi_url(),
                'https://tryton.example.com')

    def test_editor_launch_uses_an_iframe(self):
        response = routes._editor_form(
            'https://office.example.com/editor', 'signed-token')

        self.assertIn(b'target="office_frame"', response.data)
        self.assertIn(b'<iframe', response.data)
        self.assertIn(
            b'allow="autoplay; camera; microphone; display-capture"',
            response.data)
        self.assertIn(b'name="access_token" value="signed-token"',
            response.data)

    def test_editor_uses_configured_office_discovery_action(self):
        discovery = BytesIO(
            b'<discovery><action name="edit" ext="docx" '
            b'urlsrc="https://onlyoffice.example.com/editor?"/>'
            b'</discovery>')
        with (
                patch.object(routes, 'get_office_config_int', return_value=10),
                patch.object(
                    routes, 'get_office_discovery',
                    return_value=ElementTree.parse(discovery))):
            action_url = routes._editor_action_url(
                'https://onlyoffice.example.com', 'document.docx',
                'https://tryton.example.com/db/wopi/files/1')

        self.assertEqual(
            action_url,
            'https://onlyoffice.example.com/editor?WOPISrc='
            'https%3A%2F%2Ftryton.example.com%2Fdb%2Fwopi%2Ffiles%2F1')

    def test_wopi_uses_dedicated_numeric_configuration(self):
        def getint(section, option, default=None):
            values = {('wopi', 'lease_time'): 900}
            return values.get((section, option), default)

        with patch.object(editor.config, 'getint', side_effect=getint):
            self.assertEqual(editor.get_wopi_config_int('lease_time'), 900)

    def test_editable_formats_are_common_to_office_servers(self):
        discovery = ElementTree.fromstring(
            b'<discovery><action name="edit" ext="doc" '
            b'urlsrc="https://office.example.com/editor?"/>'
            b'</discovery>')
        with (
                patch.object(
                    editor, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(
                    editor, 'get_office_discovery', return_value=discovery)):
            self.assertTrue(editor.is_editable_filename('document.doc'))
            self.assertFalse(editor.is_editable_filename('document.docx'))


del unittest
