#!/usr/bin/env python3
# coding: utf-8

# VTServer daemon

# This is a generic Unix daemon form

from vt_server import main
from daemonize import Daemonize

pid = "/var/run/VTServer.pid"

daemon = Daemonize(app="VTServer", pid=pid, action=vt_server.main)
daemon.start()
