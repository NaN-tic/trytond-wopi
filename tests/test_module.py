from trytond.tests.test_tryton import ModuleTestCase


class WopiTestCase(ModuleTestCase):
    'Test WOPI module'
    module = 'wopi'
    extras = ['papyrus']


del ModuleTestCase
