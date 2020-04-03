#!/usr/bin/env python3
# coding: utf-8

"""
``vt_server_modules``
=====================

This module contains a number of ``process_...`` functions, imports
the other process modules and defines the ``PATCH`` that dispatches
process module names to the right process function.

.. Created on 2020-03-24.
"""

import vt_server_config as vsc
import vt_server_logging as vsl
import vt_server_common_tools as vsct

import soundfile as sf
import numpy as np

#: The ``PATCH`` is used to dispatch stack item modules to their corresponding function
PATCH = dict()

def process_time_reverse(in_filename, m, out_filename):
    x, fs = sf.read(in_filename)
    sf.write(out_filename, np.flip(x, axis=0), fs)
    return out_filename

PATCH['time-reverse'] = process_time_reverse



from vt_server_module_world import process_world
PATCH['world']        = process_world

from vt_server_module_vocoder import process_vocoder
PATCH['vocoder']      = process_vocoder
