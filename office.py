from trytond.pool import Pool, PoolMeta
from trytond.wizard import StateAction


class AttachmentCategoryOpen(metaclass=PoolMeta):
    __name__ = 'office.attachment.category.open'

    def do_start(self, action):
        action, data = super().do_start(action)
        if action.get('res_model') == 'ir.attachment' and data.get('res_id'):
            Attachment = Pool().get('ir.attachment')
            attachment = Attachment(data['res_id'])
            office_url = attachment.office_url
            if office_url:
                return {
                    'id': action['id'],
                    'name': attachment.rec_name,
                    'type': 'ir.action.url',
                    'url': office_url,
                    }, {}
        return action, data


class DocumentCreate(metaclass=PoolMeta):
    __name__ = 'office.document.create'

    open_office = StateAction('wopi.action_open_office_document')

    def transition_create_(self):
        state = super().transition_create_()
        if state == 'end' and self.attachment.office_url:
            return 'open_office'
        return state

    def transition_open_(self):
        if self.attachment.office_url:
            return 'open_office'
        return 'end'

    def do_open_office(self, action):
        action['url'] = self.attachment.office_url
        return action, {}
