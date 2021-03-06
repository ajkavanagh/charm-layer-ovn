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
import json
import os
import subprocess


OVS_RUNDIR = '/var/run/openvswitch'


def _run(*args):
    """Run a process, check result, capture decoded output from STDERR/STDOUT.

    :param args: Command and arguments to run
    :type args: Tuple[str, ...]
    :returns: Information about the completed process
    :rtype: subprocess.CompletedProcess
    :raises subprocess.CalledProcessError
    """
    return subprocess.run(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True,
        universal_newlines=True)


def ovs_appctl(target, *args):
    """Run `ovs-appctl` for target with args and return output.

    :param target: Name of daemon to contact.  Unless target begins with '/',
                   `ovs-appctl` looks for a pidfile and will build the path to
                   a /var/run/openvswitch/target.pid.ctl for you.
    :type target: str
    :param args: Command and arguments to pass to `ovs-appctl`
    :type args: Tuple[str, ...]
    :returns: Output from command
    :rtype: str
    :raises: subprocess.CalledProcessError
    """
    # NOTE(fnordahl): The ovsdb-server processes for the OVN databases use a
    # non-standard naming scheme for their daemon control socket and we need
    # to pass the full path to the socket.
    if target in ('ovnnb_db', 'ovnsb_db',):
        target = os.path.join(OVS_RUNDIR, target + '.ctl')
    return _run('ovs-appctl', '-t', target, *args).stdout


def cluster_status(target, schema=None):
    """Retrieve status information from clustered OVSDB.

    :param target: Usually one of 'ovsdb-server', 'ovnnb_db', 'ovnsb_db', can
                   also be full path to control socket.
    :type target: str
    :param schema: Database schema name, deduced from target if not provided
    :type schema: Optional[str]
    :returns: Structured cluster status data
    :rtype: Dict[str, Union[str, List[str], Tuple[str, str]]]
    :raises: subprocess.CalledProcessError
    """
    schema_map = {
        'ovnnb_db': 'OVN_Northbound',
        'ovnsb_db': 'OVN_Southbound',
    }
    status = {}
    k = ''
    for line in ovs_appctl(
            target,
            'cluster/status',
            schema or schema_map.get(target)).splitlines():
        if k and line.startswith(' '):
            status[k].append(line.lstrip())
        elif ':' in line:
            k, v = line.split(':', 1)
            k = k.lower()
            k = k.replace(' ', '_')
            if v:
                if k in ('cluster_id', 'server_id',):
                    v = v.replace('(', '')
                    v = v.replace(')', '')
                    status[k] = tuple(v.split())
                else:
                    status[k] = v.lstrip()
            else:
                status[k] = []
    return status


def is_cluster_leader(target, schema=None):
    """Retrieve status information from clustered OVSDB.

    :param target: Usually one of 'ovsdb-server', 'ovnnb_db', 'ovnsb_db', can
                   also be full path to control socket.
    :type target: str
    :param schema: Database schema name, deduced from target if not provided
    :type schema: Optional[str]
    :returns: Whether target is cluster leader
    :rtype: bool
    """
    try:
        return cluster_status(target, schema=schema).get('leader') == 'self'
    except subprocess.CalledProcessError:
        return False


def is_northd_active():
    """Query `ovn-northd` for active status.

    :returns: True if local `ovn-northd` instance is active, False otherwise
    :rtype: bool
    """
    try:
        for line in ovs_appctl('ovn-northd', 'status').splitlines():
            if line.startswith('Status:') and 'active' in line:
                return True
    except subprocess.CalledProcessError:
        pass
    return False


def add_br(bridge, external_id=None):
    """Add bridge and optionally attach a external_id to bridge.

    :param bridge: Name of bridge to create
    :type bridge: str
    :param external_id: Key-value pair
    :type external_id: Optional[Tuple[str,str]]
    :raises: subprocess.CalledProcessError
    """
    cmd = ['ovs-vsctl', 'add-br', bridge, '--', 'set', 'bridge', bridge,
           'protocols=OpenFlow13']
    if external_id:
        cmd.extend(('--', 'br-set-external-id', bridge))
        cmd.extend(external_id)
    _run(*cmd)


def del_br(bridge):
    """Remove bridge.

    :param bridge: Name of bridge to remove
    :type bridge: str
    :raises: subprocess.CalledProcessError
    """
    _run('ovs-vsctl', 'del-br', bridge)


def add_port(bridge, port, external_id=None):
    """Add port to bridge and optionally attach a external_id to port.

    :param bridge: Name of bridge to attach port to
    :type bridge: str
    :param port: Name of port as represented in netdev
    :type port: str
    :param external_id: Key-value pair
    :type external_id: Optional[Tuple[str,str]]
    :raises: subprocess.CalledProcessError
    """
    _run('ip', 'link', 'set', port, 'up')
    _run('ovs-vsctl', 'add-port', bridge, port)
    if external_id:
        ports = SimpleOVSDB('ovs-vsctl', 'port')
        for port in ports.find('name={}'.format(port)):
            ports.set(port['_uuid'],
                      'external_ids:{}'.format(external_id[0]),
                      external_id[1])


def del_port(bridge, port):
    """Remove port from bridge.

    :param bridge: Name of bridge to remove port from
    :type bridge: str
    :param port: Name of port to remove
    :type port: str
    :raises: subprocess.CalledProcessError
    """
    _run('ovs-vsctl', 'del-port', bridge, port)


def list_ports(bridge):
    """List ports on a bridge.

    :param bridge: Name of bridge to list ports on
    :type bridge: str
    :returns: List of ports
    :rtype: List
    """
    cp = _run('ovs-vsctl', 'list-ports', bridge)
    return cp.stdout.splitlines()


class SimpleOVSDB(object):
    """Simple interface to OVSDB through the use of command line tools.

    OVS and OVN is managed through a set of databases.  These databases have
    similar command line tools to manage them.  We make use of the similarity
    to provide a generic class that can be used to manage them.

    The OpenvSwitch project does provide a Python API, but on the surface it
    appears to be a bit too involved for our simple use case.

    Examples:
    chassis = SimpleOVSDB('ovn-sbctl', 'chassis')
    for chs in chassis:
        print(chs)

    bridges = SimpleOVSDB('ovs-vsctl', 'bridge')
    for br in bridges:
        if br['name'] == 'br-test':
            bridges.set(br['uuid'], 'external_ids:charm', 'managed')
    """

    def __init__(self, tool, table):
        """SimpleOVSDB constructor

        :param tool: Which tool with database commands to operate on.
                     Usually one of `ovs-vsctl`, `ovn-nbctl`, `ovn-sbctl`
        :type tool: str
        :param table: Which table to operate on
        :type table: str
        """
        self.tool = tool
        self.tbl = table

    def _find_tbl(self, condition=None):
        cmd = [self.tool, '-f', 'json', 'find', self.tbl]
        if condition:
            cmd.append(condition)
        cp = _run(*cmd)
        data = json.loads(cp.stdout)
        for row in data['data']:
            values = []
            for col in row:
                if isinstance(col, list):
                    values.append(col[1])
                else:
                    values.append(col)
            yield dict(zip(data['headings'], values))

    def __iter__(self):
        return self._find_tbl()

    def clear(self, rec, col):
        _run(self.tool, 'clear', self.tbl, rec, col)

    def find(self, condition):
        return self._find_tbl(condition=condition)

    def remove(self, rec, col, value):
        _run(self.tool, 'remove', self.tbl, rec, col, value)

    def set(self, rec, col, value):
        _run(self.tool, 'set', self.tbl, rec, '{}={}'.format(col, value))
