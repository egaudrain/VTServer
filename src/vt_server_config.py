# Python 3.5+
# coding: utf-8

"""
``vt_server_config``
====================

VTServer configuration file management.

.. Created on 2020-03-24.
"""

import os, json
import vt_server_logging as vsl

# TODO: switch from JSON config format to something else to be able to have comments...
def find_configuration():
    """
    Attempts to find a configuration file in known places:
    ``["/usr/local/etc/vt_server", "/etc/vt_server", "./"]``.
    """
    filename = "vt_server.conf.json"
    possible_locations = ["/usr/local/etc/vt_server", "/etc/vt_server", "./"]
    for p in possible_locations:
        fp = os.path.join(p, filename)
        if os.path.exists(fp):
            vsl.LOG.info("Found configuration file in [{}].".format(fp))
            return fp
    return None

def read_configuration(config_filename=None):
    """
    Reads a configuration file. If none is provided, will try to find one in default
    places. If that fails or if the config file is invalid will fall back to default
    options.
    """

    if config_filename is None:
        config_filename = find_configuration()

    if config_filename is None:
        vsl.LOG.warning("Hey watchout, we didn't find any config file!")
        config = dict()
    else:
        try:
            config = json.load(open(config_filename, "r"))
        except Exception as err:
            vsl.LOG.error("Loading configuration file '%s' raised error: %s." % (config_filename, repr(err)))
            config = dict()

    if 'host' not in config:
        config['host'] = 'localhost'
        vsl.LOG.warning("Hey watchout, the 'host' wasn't defined! Setting to default '%s'." % config['host'])

    if 'port' not in config:
        config['port'] = 1996
        vsl.LOG.warning("Hey watchout, the 'port' wasn't defined! Setting to default %d." % config['port'])

    if 'logfile' not in config:
        config['logfile'] = "/var/log/vt_server.log"
        vsl.LOG.warning("Hey watchout, the 'logfile' wasn't defined! Setting to default '%s'." % config['logfile'])

    if 'cachefolder' not in config:
        config['cachefolder'] = "/var/cache/vt_server"
        vsl.LOG.warning("Hey watchout, the 'cachefolder' wasn't defined! Setting to default '%s'." % config['cachefolder'])

    if 'cacheformat' not in config:
        config['cacheformat'] = "flac"
        vsl.LOG.warning("Hey watchout, the 'cacheformat' wasn't defined! Setting to default '%s'." % config['cacheformat'])

    if 'cacheformatoptions' not in config:
        config['cacheformatoptions'] = None
        vsl.LOG.warning("Hey watchout, the 'cacheformatoptions' wasn't defined! Setting to default '%s'." % config['cacheformatoptions'])

    return config

#: The dictionary holding the current configuration (used in other modules).
#: It is instanciated with :py:func:`read_configuration`.
CONFIG = read_configuration()
