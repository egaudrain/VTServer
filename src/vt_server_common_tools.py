#!/usr/bin/env python3
# coding: utf-8

"""
vt_server_common_tools
======================

This module contains function that may be useful across other VTServer modules.

"""

import pickle, hashlib, os, datetime, base64
import numpy as np

def signature(desc):
    return base64.b32encode( hashlib.blake2b(pickle.dumps(desc, 2), digest_size=30).digest() ).decode().lower()

def job_file(target_file, source_files, cache_expiration=None, stack=None, error=None):
    """
    Creates a job file for the `target_file` specified.

    :param target_file: The output file that this job file concerns.

    :param source_files: The list of source files that were used to produce the target file. During cache clean-up, if one of the source files is removed, the target will be removed.

    :param cache_expiration: A tuple with the cache expiration datetime and the duration of validity in hours, or `None` (default if omitted).

    :param stack: Optionnally a stack can be provided. `None` otherwise.

    """

    job_info = dict()
    job_info['target_file'] = os.path.abspath(target_file)
    job_info['source_files'] = list(set([os.path.abspath(p) for p in source_files]))
    job_info['cache_expiration'] = cache_expiration
    job_info['stack'] = stack

    job_filename = os.path.splitext(target_file)[0]+".job"

    with open(job_filename, "wb") as f:
        pickle.dump(job_info, f)

def update_job_file(target_file):
    """
    Updates the `target_file` cache expiration date if necessary. Note that `target_file`
    is not the job file itself, but the file targeted by the job-file.
    """

    job_filename = os.path.splitext(target_file)[0]+".job"
    job_info = pickle.load(open(job_filename, 'rb'))

    if job_info['cache_expiration'] is not None:
        job_info['cache_expiration'] = (datetime.datetime.now() + datetime.timedelta(hours=job_info['cache_expiration'][1]), job_info['cache_expiration'][1])
        pickle.dump(job_info, open(job_filename, 'wb'))





#-----------------------------------------------------
# Audio tools
#-----------------------------------------------------

import scipy.signal as sg
try:
    import samplerate
    DEFAULT_RESAMPLING_METHOD = 'samplerate'
except ImportError:
    DEFAULT_RESAMPLING_METHOD = 'scipy'

def resample(x, ratio, method=None):
    """
    The common resampling function.

    Each module can use their own resampling function, but this one will default to the best
    available option. If `samplerate <https://github.com/tuxu/python-samplerate>`_ is installed,
    it will be used. Otherwise, the :py:func:`scipy.signal.resample` function is used.

    :param x: The input sound as a numpy array.
    :param ratio: The ratio of new frequency / old frequency.
    :param method: 'scipy', 'samplerate', 'samplerate-fast'. Defaults to 'samplerate' if
        the module is available, and 'scipy' otherwise.
    """

    if method is None:
        method = DEFAULT_RESAMPLING_METHOD

    if method=='samplerate':
        return samplerate.resample(x, ratio, 'sinc_best')
    elif method=='samplerate-fast':
        return samplerate.resample(x, ratio, 'sinc_fastest')
    elif method=='scipy':
        return sg.resample(x, int(y.shape[0]*ratio))


def rms(x):
    return np.sqrt(np.mean(x**2))

def clipping_prevention(x):
    m = np.max(abs(x))
    s = 1
    if m>=1.0:
        s = .98/m
        x = x*s
    return x, s

def ramp(x, fs, dur, shape='cosine'):
    """
    The underlying function to the `"ramp"` processing module.

    :param x: The input sound.

    :param fs: The sampling frequency.

    :param dur: The duration of the ramps (a two-element iterable).

    :param shape: The shape of the ramp ('cosine' or 'linear'). Defaults to 'cosine'.

    :return: The ramped sound.
    """

    if dur[0] != 0:
        n = int(fs*dur[0])
        w = np.linspace(0,1,n)
        if shape=='cosine':
            w = (1-np.cos(w*np.pi))/2
        if len(x.shape)>1:
            w.shape = (w.shape[0],1)
            w = np.tile(w, (1, x.shape[1]))
            x[0:n,:] = x[0:n,:] * w
        else:
            x[0:n] = x[0:n] * w

    if dur[1] != 0:
        n = int(fs*dur[1])
        w = np.linspace(1,0,n)
        if shape=='cosine':
            w = (1-np.cos(w*np.pi))/2
        if len(x.shape)>1:
            w.shape = (w.shape[0],1)
            w = np.tile(w, (1,x.shape[1]))
        x[-n:] = x[-n:] * w

    return x
