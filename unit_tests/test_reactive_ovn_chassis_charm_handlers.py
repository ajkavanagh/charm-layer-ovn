# Copyright 2019 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

import reactive.ovn_chassis_charm_handlers as handlers

import charms_openstack.test_utils as test_utils


class TestRegisteredHooks(test_utils.TestRegisteredHooks):

    def test_hooks(self):
        defaults = [
            'charm.installed',
            'config.changed',
            'config.rendered',
            'update-status',
            'upgrade-charm',
            'certificates.available',
        ]
        hook_set = {
            'when': {
                'enable_chassis_reactive_code': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,),
                'configure_ovs': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'ovsdb.available',
                    'certificates.available',
                    'endpoint.certificates.changed'),
                'disable_openstack': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,),
                'enable_openstack': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'nova-compute.connected',),
                'configure_bridges': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'charm.installed',),
            },
            'when_not': {
                'disable_openstack': ('nova-compute.connected',),
            },
            'when_any': {
                'configure_bridges': (
                    'config.changed.ovn-bridge-mappings',
                    'config.changed.interface-bridge-mappings',
                    'run-default-upgrade-charm',),
            },
        }
        # test that the hooks were registered via the
        # reactive.ovn_handlers
        handlers.enable_chassis_reactive_code()
        self.registered_hooks_test_helper(handlers, hook_set, defaults)


class TestOvnHandlers(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        self.charm = mock.MagicMock()
        self.patch_object(handlers.charm, 'provide_charm_instance',
                          new=mock.MagicMock())
        self.provide_charm_instance().__enter__.return_value = \
            self.charm
        self.provide_charm_instance().__exit__.return_value = None

    def test_disable_openstack(self):
        self.patch_object(handlers.reactive, 'clear_flag')
        handlers.disable_openstack()
        self.clear_flag.assert_called_once_with(
            'charm.ovn-chassis.enable-openstack')

    def test_enable_openstack(self):
        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        self.patch_object(handlers.reactive, 'set_flag')
        nova_compute = mock.MagicMock()
        self.endpoint_from_flag.return_value = nova_compute
        handlers.enable_openstack()
        self.set_flag.assert_called_once_with(
            'charm.ovn-chassis.enable-openstack')
        nova_compute.publish_shared_secret.assert_called_once_with()
        self.charm.install.assert_called_once_with()
        self.charm.assess_status.assert_called_once_with()

    def configure_ovs(self):
        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        self.patch_object(handlers.reactive, 'clear_flag')
        ovsdb = mock.MagicMock()
        self.endpoint_from_flag.return_value = ovsdb
        self.charm.configure_ovs.assert_called_once_with(ovsdb)
        self.charm.render_with_interfaces.assert_called_once_with(
            (ovsdb),)
        self.clear_flag.assert_called_once_with(
            'endpoint.certificates.changed')
        self.charm.assess_status.assert_called_once_with()
