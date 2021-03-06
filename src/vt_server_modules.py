#!/usr/bin/env python3
# coding: utf-8

"""
vt_server_modules
=================

This module contains a number of ``process_...`` functions, imports
the other process modules and defines the :py:data:`PATCH` that dispatches
process module names to the right process function.

.. Created on 2020-03-24.
"""

#See :ref:`How to make a module` for details about how to implement your own module.

import vt_server_config as vsc
import vt_server_logging as vsl
import vt_server_common_tools as vsct

import soundfile as sf
import numpy as np
import scipy, scipy.signal

#: The :py:data:`PATCH` is used to dispatch stack item modules to their corresponding function
PATCH = dict()

#-------------------------------------------------------

def process_time_reverse(in_filename, m, out_filename):
    """
    `"time-reverse"` flips temporally the input. It doesn't take any argument.
    """
    x, fs = sf.read(in_filename)
    sf.write(out_filename, np.flip(x, axis=0), fs)
    return out_filename

PATCH['time-reverse'] = process_time_reverse

#-------------------------------------------------------

def process_mixin(in_filename, m, out_filename):
    """
    `"mixin"` adds another sound file (B) to the input file (A). The arguments are:

    :param file: The file that needs to be added to the input file.

    :param levels: A 2-element array containing the gains in dB applied to the A and B.

    :param pad: A 4-element array that specifies the before and after padding of A and B (in seconds): ``[A.before, A.after, B.before, B.after]``.
                Note that this could also be done with sub-queries, but doing it here will reduce the number of cache files generated.

    :param align: 'left', 'center', or 'right'. When the two sounds files are not the same length,
          the shorter one will be padded so as to be aligned as described with the other one. This is
          applied after padding.

    If the two sound files are not of the same sampling frequency, they are resampled to the max of the two.

    If the two sound files are not the same shape (number of channels), the one with fewer channels is duplicated to have the same number of channels as the one with the most.

    """

    if 'pad' not in m:
        m['pad'] = [0,0,0,0]
    if 'align' not in m:
        m['align'] = 'left'
    if 'levels' not in m:
        m['levels'] = [0, 0]

    A, fs_A = sf.read(in_filename, always_2d=True)
    B, fs_B = sf.read(m['file'], always_2d=True)

    # Normalizing the sampling frequency
    fs = max(fs_A, fs_B)
    if fs_A != fs:
        A = scipy.signal.resample(A, int(A.shape[0]*fs/fs_A))
    if fs_B != fs:
        B = scipy.signal.resample(B, int(B.shape[0]*fs/fs_B))

    # Normalizing the shape
    n  = max(len(A.shape), len(B.shape))
    if len(A.shape)!=n:
        A = np.tile(A, (1, np.ceil(n/A.shape[1])))[:,0:n]
    if len(B.shape)!=n:
        B = np.tile(B, (1, np.ceil(n/B.shape[1])))[:,0:n]

    # Adding padding
    A = np.concatenate((np.zeros((int(m['pad'][0]*fs), A.shape[1])), A, np.zeros((int(m['pad'][1]*fs), A.shape[1]))), axis=0)
    B = np.concatenate((np.zeros((int(m['pad'][2]*fs), B.shape[1])), B, np.zeros((int(m['pad'][3]*fs), B.shape[1]))), axis=0)

    n = max(A.shape[0], B.shape[0])
    dnA = n-A.shape[0]
    dnB = n-B.shape[0]
    if m['align']=='center':
        if dnA!=0:
            dn1 = int(dnA/2)
            dn2 = dnA-dn1
            A = np.concatenate((np.zeros((dn1, A.shape[1])), A, np.zeros((dn2, A.shape[1]))), axis=0)
        if dnB!=0:
            dn1 = int(dnB/2)
            dn2 = dnB-dn1
            B = np.concatenate((np.zeros((dn1, B.shape[1])), B, np.zeros((dn2, B.shape[1]))), axis=0)
    elif m['align']=='left':
        if dnA!=0:
            A = np.concatenate((A, np.zeros((dnA, A.shape[1]))), axis=0)
        if dnB!=0:
            B = np.concatenate((B, np.zeros((dnB, B.shape[1]))), axis=0)
    elif m['align']=='right':
        if dnA!=0:
            A = np.concatenate((np.zeros((dnA, A.shape[1])), A), axis=0)
        if dnB!=0:
            B = np.concatenate((np.zeros((dnB, B.shape[1])), B), axis=0)

    y = 10**(m['levels'][0]/20)*A + 10**(m['levels'][1]/20)*B

    y, s = vsct.clipping_prevention(y)
    if s!=1:
        vsl.LOG.info("[mixin] Clipping was avoided during processing of '%s' to '%s' by rescaling with a factor of %.3f (%.1f dB)." % (in_filename, out_filename, s, 20*np.log10(s)))

    sf.write(out_filename, y, fs)

    return out_filename, None, m['file']

PATCH['mixin'] = process_mixin

#-------------------------------------------------------

def process_pad(in_filename, m, out_filename):
    """
    `"pad"` adds silence before and/or after the sound. It takes **before** and/or **after**
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
    `"ramp"` smoothes the onset and/or offset of a signal by applying a ramp. The parameters are:

    :param duration: In seconds. If a single number, it is applied to both onset and offset.
      If a vector is given, then it specifies `[onset, offset]`. A value of zero means no ramp.

    :param shape: Either 'linear' (default) or 'cosine'.

    """

    x, fs = sf.read(in_filename)
    if type(m['duration']) == type(0.0) or type(m['duration'])==type(0):
        dur = [m['duration']]*2
    elif type(m['duration']) != type([]):
        raise ValueError("[ramp] Duration must be number or a list (%s given)." % repr(m['duration']))

    if m['shape'] not in ['linear', 'cosine']:
        raise ValueError("[ramp] Shape is not recognized (%s given)." % repr(m['shape']))

    x = vsct.ramp(x, fs, dur, m['shape'])

    sf.write(out_filename, x, fs)

    return out_filename

PATCH['ramp'] = process_ramp

#-------------------------------------------------------

from vt_server_module_world import process_world
PATCH['world']        = process_world

#-------------------------------------------------------

from vt_server_module_vocoder import process_vocoder
PATCH['vocoder']      = process_vocoder
