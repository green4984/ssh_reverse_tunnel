#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (C) 2008  Robey Pointer <robeypointer@gmail.com>
#
# This file is part of paramiko.
#
# Paramiko is free software; you can redistribute it and/or modify it under the
# terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 2.1 of the License, or (at your option)
# any later version.
#
# Paramiko is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Paramiko; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA.

"""
Sample script showing how to do remote port forwarding over paramiko.
This script connects to the requested SSH server and sets up remote port
forwarding (the openssh -R option) from a remote port through a tunneled
connection to a destination reachable from the local machine.
"""

HELP = """\
Set up a reverse forwarding tunnel across an SSH server, using paramiko. A
port on the SSH server (given with -p) is forwarded across an SSH session
back to the local machine, and out to a remote site reachable from this
network. This is similar to the openssh -R option.
"""

import getpass
import socket
import select
import threading

import paramiko

SSH_PORT = 22
STATUS_FILE_PATH = '/var/tmp/skyeyes/'
g_verbose = True



class SSHReverse(object):
    """ ssh reverse tunnel:
    visitor visit server:port use browser which really means visit remote_server:port
    server <======> SSHReverse host server <======> remote_server
    """
    def __init__(self, server, bind_port, remote, username=None, password=None, key_file=None):
        """
        :param server:
        :param bind_port:
        :param remote:
        :return:
        Example : ssh = SSHReverse('101.199.126.121', (10000, 10200, 10022), '127.0.0.1:7775')
        """

        assert server
        assert remote
        #assert bind_port
        #assert bind_port[2] >= bind_port[0] and bind_port[1] >= bind_port[2]

        self.server = server
        self.remote = remote
        if bind_port is None or len(bind_port) != 3:
            bind_port = [bind_port for i in range(3)]
        self.bind_port_min = bind_port[0]
        self.bind_port_max = bind_port[1]
        self.bind_port_try = bind_port[2]
        self.bind_port_now = None
        self.username = username
        self.password = password
        self.key_file = key_file
        self.thread = None
        self.stop = False
        self._client_list = []
        self._client_curr = -1
        self._client_file = []
        self._client_extra = []

    def set_bind_port(self, port):
        bind_port=()
        if isinstance(port, int):
            bind_port = (port, port, port)
        if isinstance(port, str):
            bind_port = (int(port), int(port), int(port))
        self.bind_port_min = bind_port[0]
        self.bind_port_max = bind_port[1]
        self.bind_port_try = bind_port[2]



    @property
    def client(self):
        if self._client_curr == -1:
            return None
        return self._client_list[self._client_curr]

    @client.setter
    def client(self, value):
        self._client_list.append(value)
        self._client_curr+=1

    @property
    def status_file(self):
        if self._client_curr == -1:
            return None
        return self._client_extra[self._client_curr][1]

    @property
    def client_count(self):
        return len(self._client_list)

    @property
    def client_extra(self):
        if self._client_curr == -1:
            return None
        return self._client_extra[self._client_curr]

    @client_extra.setter
    def client_extra(self, value):
        """
        ((server_ip, server_port), status_file, (remote_ip, remote_port) )
        :param value:
        :return:
        """
        self._client_extra.append(value)

    def client_remove(self):
        if self._client_curr == -1:
            return None
        self._client_curr-=1
        return self._client_list.pop()


    def _parse_options(self):
        self.username = getpass.getuser() if self.username is None else self.username
        #self.password = getpass.getpass('Enter SSH password: ') if self.password is None else self.password
        self.look_for_keys = True

        server_host, server_port = self.get_host_port(self.server, SSH_PORT)
        remote_host, remote_port = self.get_host_port(self.remote, SSH_PORT)
        return (server_host, server_port), (remote_host, remote_port)

    def _test_remote_connectable(self, remote):
        self.verbose("begin to test the remote %s:%s is connectable ..." % remote)
        sock = socket.socket()
        try:
            sock.connect(remote)
        except Exception as e:
            SSHReverse.verbose('Forwarding request to %s:%d failed: %r' % (remote[0], remote[1], e))
            raise
        sock.close()
        self.verbose("the remote %s:%s is connectable !" % remote)

    def _connect_to_server(self, server, timeout):
        client = self.client
        self.verbose('Connecting to ssh host %s:%d ...' % (server[0], server[1]))
        try:
            # Test whether the server is able to connect or not
            client.connect(server[0], server[1], username=self.username, key_filename=self.key_file,
                           look_for_keys=self.look_for_keys, password=self.password, timeout=timeout/1000.00)
        except Exception as e:
            self.verbose('*** Failed to connect to %s:%d: %r' % (server[0], server[1], e))
            raise
        self.verbose('Connected to ssh host %s:%d ok!' % (server[0], server[1]))

    def create(self, timeout=5000, daemon=True, tunnel_close_callback=None, c_args=()):
        """
        :type conn_timeout: int
        """
        server, remote = self._parse_options()

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        self.client = client

        # Test whether the Server is able to connect or not
        self._connect_to_server(server, timeout)

        # Test whether the Remote is able to connect or not
        self._test_remote_connectable(remote)

        # Get an useable server port to bind, if not raise exception to the caller
        self._try_bind_server_port(client.get_transport())
        self.verbose('Now forwarding remote port %d to %s:%d ...' % (self.bind_port_now, remote[0], remote[1]))

        #create status_file
        #self._create_status_filename(server, remote, self.bind_port_now)

        thr = None
        event = None
        if daemon:
            event = threading.Event()
        try:
            self.thread = thr = threading.Thread(
                target=self._reverse_forward_tunnel,
                args=(remote, client.get_transport(), event, tunnel_close_callback, c_args))
            self.stop = False
            if daemon:
                thr.setDaemon(True)
                thr.start()
                if event:
                    event.wait(timeout=3)
            else:
                thr.setDaemon(False)
                thr.start()
                thr.join()
        except KeyboardInterrupt:
            self.stop = True
            self.verbose('C-c: Port forwarding stopped.')
            raise
        except Exception, e:
            self.stop = True
            self.verbose("thread %s id %d start catch exception : %s " % (thr.getName(), thr.ident, e.message))
            raise

    def remove(self, wait=True):
        """
        clear all connections and resources
        """
        self.stop = True
        if self.client_count == 0:
            return
        #cmd = "rm %s" % self.status_file
        #self._execute_command(cmd=cmd)
        client = self.client_remove()
        client.close()

    def _create_status_filename(self, server, remote, forward_port):
        hostname = socket.gethostname()
        status_file = STATUS_FILE_PATH + 'skyeye.%s.%s:%d.%d.lock' \
                                         % (socket.gethostname(), remote[0], remote[1], forward_port)
        cmd = "mkdir -p %s && touch %s" % (STATUS_FILE_PATH, status_file)
        err = self._execute_command(cmd=cmd)
        if len(err) > 0:
            raise Exception("create status file %s failure" % status_file)
        self.client_extra = (server, status_file, remote)
        return status_file

    def _execute_command(self, cmd):
        """
        execute command on server
        :rtype : str
        """
        try:
            if cmd is None:
                return None, None, None
            stdin, stdout, stderr = self.client.exec_command(command=cmd)
            err = stderr.read()
            if len(err) > 0:
                self.verbose("error occurred : %s" % err)
            return err
        except Exception, e:
            self.verbose("execute command %s on remote %s error : %r" % (cmd, self.remote, e))

    def _try_bind_server_port(self, transport):
        port_try = self.bind_port_try
        while True:
            try:
                transport.request_port_forward('', port_try)
                self.bind_port_now = port_try
                return
            except paramiko.SSHException as e:
                if port_try < self.bind_port_max:
                    port_try+=1
                if port_try == self.bind_port_max:
                    port_try = self.bind_port_min
                if port_try == self.bind_port_try:
                    raise Exception(
                        "forward port %d ~ %d already used!" % (self.bind_port_min, self.bind_port_max))
            except Exception as e:
                self.verbose("forward port error : %r" % e)
                raise

    def _reverse_forward_tunnel(self, remote, transport, event, failure_callback=None, args=()):
        if event:
            event.set()
        try:
            while True:
                chan = transport.accept(1000)
                if self.stop:
                    break
                if chan is None:
                    if not transport.is_alive():
                        #server close the ssh reverse or ssh reverse process killed [-9] by server
                        transport.close()
                        self.remove(wait=True)
                        self.verbose("server close or shutdown the ssh proxy, exit current thread now")
                        if failure_callback:
                            failure_callback(args)
                        return
                    continue
                thr = threading.Thread(target=self.handler, args=(self, chan, remote[0], remote[1]))
                thr.setDaemon(True)
                thr.start()
        except Exception as e:
            self.verbose("forward tunnel from %s:%d to %s:%d error : %r",
                         self.server[0], self.bind_port_now,
                         remote[0], remote[1], e)

    @staticmethod
    def get_host_port(spec, default_port):
        "parse 'hostname:22' into a host and port, with the port optional"
        args = (spec.split(':', 1) + [default_port])[:2]
        args[1] = int(args[1])
        return args[0], args[1]

    @staticmethod
    def verbose(s):
        if g_verbose:
            print(s)

    @staticmethod
    def handler(self, chan, host, port):
        assert isinstance(self, SSHReverse)
        sock = socket.socket()
        try:
            sock.connect((host, port))
        except Exception as e:
            SSHReverse.verbose('Forwarding request to %s:%d failed: %r' % (host, port, e))
            chan.close()
            sock.close()
            raise

        SSHReverse.verbose('Connected!  Tunnel open %r -> %r -> %r' % (chan.origin_addr,
                                                            chan.getpeername(), (host, port)))
        while True:
            r, w, x = select.select([sock, chan], [], [])
            if self.stop:
                break
            if sock in r:
                data = sock.recv(1024)
                if len(data) == 0:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(1024)
                if len(data) == 0:
                    break
                # this is just a test to check connection
                #if self.port_test(data, chan):
                #    continue
                sock.send(data)
        chan.close()
        sock.close()
        SSHReverse.verbose('Tunnel closed from %r' % (chan.origin_addr,))

    def port_test(self, data, chan):
        """
        just for test server bind port ok, and response hello skyeye
        """
        ret = False
        assert isinstance(data, str)
        if data.startswith('hello skyeye'):
            chan.send('hello skyeye back')
            ret = True
        return ret
