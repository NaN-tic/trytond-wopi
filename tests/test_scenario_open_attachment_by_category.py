import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from proteus import Model, launch_action
from trytond.modules.wopi import editor
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestOpenAttachmentByCategory(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules(['wopi', 'office'])
        Attachment = Model.get('ir.attachment', config=config)
        Category = Model.get('office.category', config=config)
        Union = Model.get('office.attachment.category', config=config)
        category = Category(name='Documents')
        category.save()
        with config.set_context(default_unlinked=True):
            document = Attachment(
                name='Document.odt', type='data', data=b'document')
            document.categories.append(category)
            document.save()
            archive = Attachment(
                name='Archive.bin', type='data', data=b'archive')
            archive.categories.append(Category(category.id))
            archive.save()

        discovery = ElementTree.fromstring(
            '<wopi-discovery><action name="edit" ext="odt" />'
            '</wopi-discovery>')
        with (
                patch.object(editor, 'get_office_url',
                    return_value='https://office.example.com'),
                patch.object(editor, 'get_office_discovery',
                    return_value=discovery),
                patch.object(editor, 'get_wopi_url',
                    return_value='https://tryton.example.com')):
            for attachment in [document, archive]:
                row, = Union.find([
                    ('name', '=', attachment.name)])
                opened = launch_action(
                    'office.wizard_attachment_category_open',
                    [row], config=config)
                if attachment == document:
                    self.assertTrue(attachment.office_url)
                    self.assertIn('/wopi/open/ir.attachment/',
                        attachment.office_url)
                    self.assertEqual(opened.actions, [attachment.office_url])
                else:
                    self.assertFalse(attachment.office_url)
                    self.assertEqual(len(opened.actions), 1)
                    self.assertEqual(opened.actions[0][0].id, attachment.id)

            opened = launch_action(
                'office.wizard_attachment_category_open_from_category',
                [category], config=config)
            self.assertEqual(
                {row.name for row in opened.actions[0]},
                {'Document.odt', 'Archive.bin'})
