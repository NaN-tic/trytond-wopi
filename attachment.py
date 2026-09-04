from trytond.model import fields, ModelView
from trytond.pool import PoolMeta
from trytond.pyson import Bool, Eval

from .editor import get_editor_url, is_editable_filename


class Attachment(metaclass=PoolMeta):
    __name__ = 'ir.attachment'

    office_url = fields.Function(
        fields.Char('Open', states={
                'invisible': ~Bool(Eval('office_url')),
                }),
        'get_office_url')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
                'open': {
                    'invisible': ~Bool(Eval('office_url')),
                    'depends': ['office_url'],
                    'icon': 'tryton-open',
                    },
                })

    @classmethod
    def get_office_url(cls, attachments, name):
        return {
            attachment.id: (
                get_editor_url(cls.__name__, attachment.id, 'data',
                    attachment.name)
                if attachment.type == 'data'
                and is_editable_filename(attachment.name) else None)
            for attachment in attachments}

    @classmethod
    @ModelView.button
    def open(cls, attachments):
        if not attachments:
            return
        attachment, = attachments
        return {
            'type': 'ir.action.url',
            'url': attachment.office_url,
            }
