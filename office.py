from trytond.pool import PoolMeta
from trytond.wizard import StateAction


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
