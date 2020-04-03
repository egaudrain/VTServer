#!/usr/bin/env python3
# coding: utf-8

# VTServer systemd daemon

from systemd import journal
import vt_server_logging as vsl
import vt_server

jh = journal.JournalHandler()
jh.setLevel('WARNING')
vsl.LOG.addHandler(jh)

if __name__=='__main__':
    vt_server.main()
