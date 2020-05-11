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

#-------------------------------------------------------

def process_time_reverse(in_filename, m, out_filename):
    """
    ``time-reverse`` flips temporally the input. It doesn't take any argument.
    """
    x, fs = sf.read(in_filename)
    sf.write(out_filename, np.flip(x, axis=0), fs)
    return out_filename

PATCH['time-reverse'] = process_time_reverse

#-------------------------------------------------------

def process_pad(in_filename, m, out_filename):
    """
    ``pad`` adds silence before and/or after the sound. It takes `'before'` and/or `'after'`
    as arguments, specifying the duration of silence in seconds.
    """

    x, fs = sf.read(in_filename)
    if 'before' not in m:
        m['before'] = 0
    if 'after' not in m:
        m['after'] = 0
    if len(x.shape)>1:
        x = np.concatenate((np.zeros((int(m['before']*fs), x.shape[1])), x, np.zeros((int(m['after']*fs), x.shape[1]))), axis=0)
    else:
        x = np.concatenate((np.zeros((int(m['before']*fs),)), x, np.zeros((int(m['after']*fs),))), axis=0)
    sf.write(out_filename, x, fs)

    return out_filename

PATCH['pad'] = process_pad

#-------------------------------------------------------

def process_ramp(in_filename, m, out_filename):
    """
    ``ramp`` smoothes the onset and/or offset of a signal by applying a ramp. The parameters are:

        * 'duration': in seconds. If a single number, it is applied to both onset and offset.
          If a vector is given, then it specifies `[onset, offset]`. A value of zero means no ramp.

        * 'shape': Either 'linear' (default) or 'cosine'.
    
    """

    x, fs = sf.read(in_filename)
    if type(m['duration']) == type(0.0) or type(m['duration'])==type(0):
        dur = [m['duration']]*2
    elif type(m['duration']) != type([]):
        raise ValueError("[ramp] Duration must be number or a list (%s given)." % repr(m['duration']))

    if m['shape'] not in ['linear', 'cosine']:
        raise ValueError("[ramp] Shape is not recognized (%s given)." % repr(m['shape']))

    if dur[0] != 0:
        n = int(fs*dur[0])
        w = np.linspace(0,1,n)
        if m['shape']=='cosine':
            w = (1-np.cos(w*np.pi))/2
        if len(x.shape)>1:
            w = np.tile(w, (1,x.shape[1]))
        x[0:n] = x[0:n] * w

    if dur[1] != 0:
        n = int(fs*dur[1])
        w = np.linspace(1,0,n)
        if m['shape']=='cosine':
            w = (1-np.cos(w*np.pi))/2
        if len(x.shape)>1:
            w = np.tile(w, (1,x.shape[1]))
        x[-n:] = x[-n:] * w

    sf.write(out_filename, x, fs)

    return out_filename

PATCH['ramp'] = process_ramp

#-------------------------------------------------------

from vt_server_module_world import process_world
PATCH['world']        = process_world

#-------------------------------------------------------

from vt_server_module_vocoder import process_vocoder
PATCH['vocoder']      = process_vocoder
