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
