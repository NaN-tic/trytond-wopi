import unittest
from unittest.mock import patch

from proteus import Model, Wizard
from trytond.modules.wopi import attachment as wopi_attachment, editor
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestCreateOfficeDocument(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules(['wopi', 'office'])

        Attachment = Model.get('ir.attachment', config=config)
        Template = Model.get('office.document.template', config=config)

        for template in Template.find([
                ('extension', 'in', ['xlsx', 'pptx']),
                ]):
            template.active = False
            template.save()

        editable_template, = Template.find([
                ('extension', '=', 'docx'),
                ])

        with patch.object(
                editor, 'get_wopi_url',
                return_value='https://tryton.example.com'), patch.object(
                wopi_attachment, 'is_editable_filename', return_value=True):
            wizard = Wizard('office.document.create', config=config)
            self.assertEqual(wizard.form.template, editable_template)
            wizard.execute('create_')

        attachment, = Attachment.find([
                ('name', '=', 'unnamed document.docx'),
                ])
        self.assertEqual(len(wizard.actions), 2)
        self.assertIn(
            '/wopi/open/ir.attachment/%s/data' % attachment.id,
            wizard.actions[0])
        self.assertEqual(wizard.actions[1][0], attachment)

        existing = Attachment(
            name='existing.txt', type='data', data=b'existing', unlinked=True)
        existing.save()
        with patch.object(
                editor, 'get_wopi_url',
                return_value='https://tryton.example.com'), patch.object(
                wopi_attachment, 'is_editable_filename', return_value=True):
            wizard = Wizard(
                'office.document.create', [existing], config=config)
            wizard.form.template = editable_template
            wizard.execute('create_')

        existing.reload()
        self.assertEqual(existing.name, 'existing.docx')
        self.assertEqual(len(wizard.actions), 1)
        self.assertIn(
            '/wopi/open/ir.attachment/%s/data' % existing.id,
            wizard.actions[0])

        pdf_template = Template(
            name='PDF Document', type='data', extension='pdf',
            mime_type='application/pdf', data=b'PDF')
        pdf_template.save()

        with patch.object(
                editor, 'get_wopi_url',
                return_value='https://tryton.example.com'):
            wizard = Wizard('office.document.create', config=config)
            wizard.form.template = pdf_template
            wizard.execute('create_')

        self.assertEqual(len(wizard.actions), 1)
        self.assertEqual(wizard.actions[0][0].name, 'unnamed document.pdf')
