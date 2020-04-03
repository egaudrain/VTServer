# Python 3.5+
# coding: utf-8

"""
``vt_server_logging``
=====================

VTServer logging facilities.

.. Created on 2020-03-20.
"""

import os, getpass
import logging, logging.handlers

LOG = logging.getLogger('VTServer')
LOG.setLevel('DEBUG')

class VTServerLogFormatter(logging.Formatter):
    def __init__(self):
        super().__init__('[%(asctime)s :: '+("%s(%d:%d)" % (getpass.getuser(), os.getuid(), os.getgid()))+'] %(message)s')

    def format(self, record):
        return super().format(record).strip().replace("\n", "\n\t")

def get_FileHandler(logfile):
    rtf = logging.handlers.RotatingFileHandler(logfile, maxBytes=5000)
    rtf.setFormatter(VTServerLogFormatter())
    rtf.setLevel('DEBUG')
    return rtf
