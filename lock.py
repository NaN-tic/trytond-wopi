from trytond.model import ModelSQL, ModelView, Unique, fields


class WopiLock(ModelSQL, ModelView):
    """A WOPI lock is deliberately separate from Tryton record locks."""
    __name__ = 'wopi.lock'

    file_id = fields.Char('File ID', required=True)
    value = fields.Char('Value', required=True)
    expires_at = fields.DateTime('Expires At', required=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints += [
            ('file_id_unique', Unique(table, table.file_id),
                'wopi.msg_lock_file_unique'),
            ]
