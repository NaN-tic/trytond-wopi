from trytond.pool import Pool

from . import attachment, lease, lock, office, routes

__all__ = ['register', 'routes']


def register():
    Pool.register(
        attachment.Attachment,
        lease.WopiLease,
        lock.WopiLock,
        module='wopi', type_='model')
    Pool.register(
        office.AttachmentCategoryOpen,
        office.DocumentCreate,
        module='wopi', type_='wizard', depends=['office'])
