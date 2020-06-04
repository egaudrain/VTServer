#!/usr/bin/env python3
# coding: utf-8

import pickle, hashlib
import numpy as np

def signature(desc):
    return hashlib.md5(pickle.dumps(desc, 2)).hexdigest()

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
            w = np.tile(w, (1,x.shape[1]))
        x[0:n] = x[0:n] * w

    if dur[1] != 0:
        n = int(fs*dur[1])
        w = np.linspace(1,0,n)
        if shape=='cosine':
            w = (1-np.cos(w*np.pi))/2
        if len(x.shape)>1:
            w = np.tile(w, (1,x.shape[1]))
        x[-n:] = x[-n:] * w

    return x
