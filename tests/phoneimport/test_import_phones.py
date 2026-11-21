"""The user's phones (the Inboxes page's): kept whether plugged in or not, added, renamed and removed by the user; a
phone plugged in that isn't one of theirs shown as new, and not imported from until it's added"""
import os
from unittest import mock

import helpers
from dirdelta.known import replicas
from dirdelta.phoneimport import sources
from dirdelta.web import importing
from import_support import ImportTest

PHONE = 'SAMSUNG_SAMSUNG_Android_RZCY502XMHE'


class PhonesTest(ImportTest):
    def setUp(self):
        super().setUp()
        self.gvfs = os.path.join(self.temp, 'gvfs')
        self.storage = os.path.join(self.gvfs, sources.MTP_PREFIX + PHONE, 'Internal storage')
        helpers.make_files(self.storage, ['DCIM/Camera/a.jpg'])
        for patcher in (mock.patch('dirdelta.phoneimport.sources.GVFS_DIR', self.gvfs),
                        mock.patch('dirdelta.known.replicas.REPLICAS_FILE', os.path.join(self.temp, 'replicas.json'))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.routes = {path: route for (_, path), route in importing.routes().items()}

    def phones(self):
        return [(inbox['kind'], inbox['name'], inbox['there']) for inbox in importing.inboxes()
                if inbox['kind'] in ('phone', 'newphone')]

    def test_a_phone_plugged_in_is_new_until_its_added_and_kept_once_unplugged(self):
        self.assertEqual([('newphone', 'SAMSUNG Android', True)], self.phones())
        dest = os.path.join(self.temp, 'replica')
        os.makedirs(dest, exist_ok=True)
        self.assertEqual({'error': "Add this phone first."}, self.routes['/api/imports/new']({}, {'source': self.storage, 'dest': dest}))
        self.assertTrue(self.routes['/api/phones/add']({}, {'phone': PHONE, 'name': "Dana's phone"})['ok'])
        self.assertEqual([('phone', "Dana's phone", True)], self.phones())
        with mock.patch('dirdelta.phoneimport.sources.GVFS_DIR', os.path.join(self.temp, 'nothing plugged in')):
            self.assertEqual([('phone', "Dana's phone", False)], self.phones())

    def test_a_phone_is_renamed_and_removed(self):
        self.routes['/api/phones/add']({}, {'phone': PHONE, 'name': 'phone'})
        self.routes['/api/phones/add']({}, {'phone': PHONE, 'name': 'work phone'})
        self.assertEqual({PHONE: {'name': 'work phone'}}, replicas.load().phones)
        self.assertTrue(self.routes['/api/phones/remove']({}, {'phone': PHONE})['ok'])
        self.assertEqual([('newphone', 'SAMSUNG Android', True)], self.phones())
