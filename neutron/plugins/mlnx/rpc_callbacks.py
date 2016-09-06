# Copyright 2013 Mellanox Technologies, Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from oslo.config import cfg

from neutron.common import constants as q_const
from neutron.common import rpc as n_rpc
from neutron.db import api as db_api
from neutron.db import securitygroups_rpc_base as sg_db_rpc
from neutron.openstack.common import log as logging
from neutron.plugins.mlnx.db import mlnx_db_v2 as db

LOG = logging.getLogger(__name__)


class MlnxRpcCallbacks(n_rpc.RpcCallback,
                       sg_db_rpc.SecurityGroupServerRpcCallbackMixin):
    # History
    #  1.1 Support Security Group RPC
    #  1.2 Support get_devices_details_list
    RPC_API_VERSION = '1.2'

    #to be compatible with Linux Bridge Agent on Network Node
    TAP_PREFIX_LEN = 3

    @classmethod
    def get_port_from_device(cls, device):
        """Get port according to device.

        To maintain compatibility with Linux Bridge L2 Agent for DHCP/L3
        services get device either by linux bridge plugin
        device name convention or by mac address
        """
        port = db.get_port_from_device(device[cls.TAP_PREFIX_LEN:])
        if port:
            port['device'] = device
        else:
            port = db.get_port_from_device_mac(device)
            if port:
                port['device'] = device
        return port

    def get_device_details(self, rpc_context, **kwargs):
        """Agent requests device details."""
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s details requested from %(agent_id)s"),
                  {'device': device, 'agent_id': agent_id})
        port = self.get_port_from_device(device)
        if port:
            binding = db.get_network_binding(db_api.get_session(),
                                             port['network_id'])
            entry = {'device': device,
                     'physical_network': binding.physical_network,
                     'network_type': binding.network_type,
                     'segmentation_id': binding.segmentation_id,
                     'network_id': port['network_id'],
                     'port_mac': port['mac_address'],
                     'port_id': port['id'],
                     'admin_state_up': port['admin_state_up']}
            if cfg.CONF.AGENT.rpc_support_old_agents:
                entry['vlan_id'] = binding.segmentation_id
            new_status = (q_const.PORT_STATUS_ACTIVE if port['admin_state_up']
                          else q_const.PORT_STATUS_DOWN)
            if port['status'] != new_status:
                db.set_port_status(port['id'], new_status)
        else:
            entry = {'device': device}
            LOG.debug(_("%s can not be found in database"), device)
        return entry

    def get_devices_details_list(self, rpc_context, **kwargs):
        return [
            self.get_device_details(
                rpc_context,
                device=device,
                **kwargs
            )
            for device in kwargs.pop('devices', [])
        ]

    def update_device_down(self, rpc_context, **kwargs):
        """Device no longer exists on agent."""
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s no longer exists on %(agent_id)s"),
                  {'device': device, 'agent_id': agent_id})
        port = self.get_port_from_device(device)
        if port:
            entry = {'device': device,
                     'exists': True}
            if port['status'] != q_const.PORT_STATUS_DOWN:
                # Set port status to DOWN
                db.set_port_status(port['id'], q_const.PORT_STATUS_DOWN)
        else:
            entry = {'device': device,
                     'exists': False}
            LOG.debug(_("%s can not be found in database"), device)
        return entry

    def update_device_up(self, rpc_context, **kwargs):
        """Device is up on agent."""
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s up %(agent_id)s"),
                  {'device': device, 'agent_id': agent_id})
        port = self.get_port_from_device(device)
        if port:
            if port['status'] != q_const.PORT_STATUS_ACTIVE:
                # Set port status to ACTIVE
                db.set_port_status(port['id'], q_const.PORT_STATUS_ACTIVE)
        else:
            LOG.debug(_("%s can not be found in database"), device)
