#!/usr/bin/env python3
# coding: utf-8

"""
vt_server_module_gibberish
==========================

This module contains a function to create a gibberish masker,
created out of random sentence chunks, that can be used in the CRM experiment.

.. code-block:: json

    {
        "module": "gibberish",
        "seed":   8,
        "files": ["sp1F/cat_8_red.wav", "sp1F/cat_9_black.wav", "..."],
        "chunk_dur_min": 0.2,
        "chunk_dur_max": 0.7,
        "total_dur": 1.2,
        "ramp": 0.05,
        "force_nb_channels": 1,
        "force_fs": 44100,
        "stack": [
            {
                "module": "world",
                "f0":     "*2",
                "vtl":    "-3.8st"
            }
        ]
    }

**This module is intended to be used at the top of the stack**

If the source files have different sampling frequencies, the sampling frequency of the first chunk
will be used as reference, and all the following segments will be resampled to that sampling frequency.
Alternatively, it is possible to specify ``force_fs`` to impose a sampling frequency. If ``force_fs`` is
0 or ``None``, the default method is used.

A similar mechanism is used for stereo vs. mono files. The number of channels can be imposed with ``force_nb_channels``.
Again, if ``force_nb_channels`` is 0 or ``None``, the default method based on the first chunk is used. If the number
of channels of a segment is greater than the number of channels in the output, all channels are averaged and
duplicated to the appropriate number of channels. This is fine for stereo/mono conversion, but keep that in mind
if you ever use files with more channels. If a segment has fewer channels than needed, the extra channels are created
by recycling the existing values. Again, for stero/mono conversion, this is fine, but might not be what you want
for multi-channel audio.

Files
-----

The module will look through the provided ``files`` to generate the output. As much as possible, it will try to
not reuse a file, but will recycle the list if necessary.

If the module is first in the stack, the filenames provided in ``files`` (or ``shell_pattern``, or ``re_pattern``)
are relative to the folder specified in the ``file`` field of the query. Make sure that the folder name ends with a `/`.

However, note that if the module is not used at the top of the stack, but lower, there may be unexpected results as the folder will be the cache folder of the previous module.

The list will be shuffled randomly based on the ``seed`` parameter.

Instead of ``files``, we can have ``shell_pattern`` which defines a shell-like patterns as an object:

.. code-block:: json

    {
        "module": "gibberish",
        "seed":   8,
        "shell_pattern": {
            "include": "sp1F/cat*.wav",
            "exclude": ["sp1F/cat_8_*.wav", "sp1F/cat_*_red.wav"]
        },
        "...": "..."
    }

If a list of patterns is provided, the outcome is cumulative.

Alternatively, a regular expression can be used as ``re_pattern``.

If all ``files``, and ``shell_pattern`` and/or ``re_pattern`` are provided, only one is used by prioritising in the order they are presented here.

Segment properties
------------------

``chunk_dur_min`` and ``chunk_dur_max`` define the minimum and maximum segment duration. ``total_dur`` is the total duration we are aiming to generate. ``ramp`` defines the duration of the ramps applied to each segment.


Stack
-----

``stack`` is an optional processing stack that will be applied to all the selected files before concatenation.

Seed
----

The ``seed`` parameter is mandatory to make sure cache is managed properly.

.. Created on 2020-06-09.
"""

import vt_server_config as vsc
import vt_server_logging as vsl
import vt_server_common_tools as vsct
from vt_server_brain import process_module

import numpy as np

import soundfile as sf
import random

import os
from fnmatch import fnmatch
from glob import glob

import re
import datetime

# This is a generator module, we need to specify the MODULE_TYPE
MODULE_TYPE = 'generator'

cache_expiration = 720 # hours

def get_file_list_from_array(file_array, folder):
    lst = list()
    for f in file_array:
        if '..'+os.path.sep in f:
            raise ValueError("[gibberish] It is not allowed to look outside of '%s' ('%s')" % (folder, f))
        lst.append(os.path.join(folder, f))
        if not os.path.exists(lst[-1]):
            raise ValueError("[gibberish] The specified file does not exist: '%s'" % lst[-1])
    return lst

def get_file_list_from_shell_pattern(patterns, folder):

    if not isinstance(patterns, dict):
        raise ValueError("[gibberish] 'shell_pattern' has to be a dict object: %s" % repr(patterns))
    if 'include' not in patterns:
        raise ValueError("[gibberish] 'shell_pattern' has to have an 'include' attribute: %s" % repr(patterns))
    if 'exclude' not in patterns:
        patterns['exclude'] = []

    if isinstance(patterns['include'], str):
        patterns['include'] = [patterns['include']]
    if isinstance(patterns['exclude'], str):
        patterns['exclude'] = [patterns['exclude']]

    # Making sure we always have a / at the end of folder
    if not folder.endswith(os.path.sep):
        folder += os.path.sep

    incl_lst = list()
    for ip in patterns['include']:
        if '..'+os.path.sep in ip:
            raise ValueError("[gibberish] It is not allowed to look outside of '%s' ('%s')" % (folder, ip))
        incl_lst.extend( glob(os.path.join(folder,ip)) )
    lst = list()
    for f in incl_lst:
        keep = True
        for ep in patterns['exclude']:
            if fnmatch(f.replace(folder, '', 1), ep):
                keep = False
                break
        if keep:
            lst.append(f)

    return lst


def get_file_list_from_re_pattern(pattern, folder):
    try:
        reP = re.compile(pattern)
    except Exception as err:
        raise ValueError("[gibberish] The regular expression could not be compiled '%s': %s" % (repr(pattern), err))

    # Making sure we always have a / at the end of folder
    if not folder.endswith(os.path.sep):
        folder += os.path.sep

    lst = list()
    for root, _, files in os.walk(folder):
        for f in files:
            ff = os.path.join(root, f)
            if reP.fullmatch(ff.replace(folder, '', 1)) is not None:
                lst.append(ff)

    return lst

def process_gibberish(in_filename, m, out_filename):

    # Checking parameters
    #--------------------

    folder = os.path.dirname(in_filename)
    if not os.path.exists(folder):
        raise ValueError("[gibberish] The specified folder does not exist: '%s'" % folder)

    # Seed
    if 'seed' not in m:
        raise ValueError("[gibberish] A 'seed' parameter needs to be provided: %s" % repr(m))
    try:
        rnd = random.Random(m['seed'])
    except Exception as e:
        raise ValueError("[gibberish] Could not initialise random number generator with seed '%s': %s" (repr(m['seed']), e))

    # Segments
    for k in ['chunk_dur_min', 'chunk_dur_max', 'total_dur']:
        if k not in m:
            raise ValueError("[gibberish] The mandatory argument '%s' is missing: %s" % (k, repr(m)))
        try:
            m[k] = float(m[k])
        except:
            raise ValueError("[gibberish] Argument '%s' needs to be a float (%s provided)" % (k, repr(m[k])))

    # Ramp
    if 'ramp' not in m:
        m['ramp'] = 50e-3
    else:
        k = 'ramp'
        try:
            m[k] = float(m[k])
        except:
            raise ValueError("[gibberish] Argument 'ramp' needs to be a float (%s provided)" % repr(m[k]))

    # force_fs, force_nb_channels
    for k in ['force_fs', 'force_nb_channels']:
        if k not in m:
            m[k] = None
        else:
            try:
                if m[k] is not None and m[k] is not 0:
                    m[k] = int(m[k])
            except:
                raise ValueError("[gibberish] Argument '%s' needs to be an int or None (%s provided)" % (k,repr(m[k])))

        if m[k]==0:
            m[k] = None

    # Stack
    if 'stack' not in m:
        m['stack'] = []
    elif not isinstance(m['stack'], list):
        raise ValueError("[gibberish] The 'stack' needs to be a list: %s" % repr(m['stack']))

    # Files or patterns
    if 'files' in m:
        lst = get_file_list_from_array(m['files'], folder)
    elif 'shell_pattern' in m:
        lst = get_file_list_from_shell_pattern(m['shell_pattern'], folder)
    elif 're_pattern' in m:
        lst = get_file_list_from_re_pattern(m['re_pattern'], folder)
    else:
        raise ValueError("[gibberish] One of 'files', 'shell_pattern', or 're_pattern' needs to be provided: %s" % repr(m))

    if len(lst)==0:
        raise ValueError("[gibberish] The provided query does not match any file in `%s`: %s" % (folder, repr(m)))
    else:
        # We want to make sure files are always listed in the same order, independtly from the system
        lst.sort()

    masker_struct = []
    masker = np.array([])
    n_chunk = 1

    d = 0

    # We will shuffle the list in order to avoid repetitions as much as possible
    lstr = [].__iter__()

    source_files = list()

    while d < m['total_dur']:

        try:
            soundfile = lstr.__next__()
        except StopIteration:
            lstr = rnd.sample(lst, k=len(lst)).__iter__()
            soundfile = lstr.__next__()

        f = soundfile
        for sm in m['stack']:
            f = process_module(f, sm, vsc.CONFIG['cacheformat'], cache=(datetime.datetime.now() + datetime.timedelta(hours=cache_expiration), cache_expiration)) # We keep these files 1 month
        source_files.append(f)

        # Process masker file
        y, fs = sf.read(f, always_2d=True)

        if d==0:

            if m['force_fs'] is None:
                fs_ref = fs
            else:
                fs_ref = m['force_fs']

            if m['force_nb_channels'] is None:
                nb_channels_ref = y.shape[1]
            else:
                nb_channels_ref = m['force_nb_channels']

            masker = np.zeros((int(m['total_dur']*fs_ref), nb_channels_ref))
            masker_i = 0

        if fs!=fs_ref:
            y = vsct.resample(y, fs_ref/fs)
            fs = fs_ref

        if y.shape[1]!=nb_channels_ref:
            if y.shape[1]<nb_channels_ref:
                y = np.pad(y, ((0,0),(0,nb_channels_ref-y.shape[1])), mode='wrap')
            else:
                y = np.tile(np.mean(y, axis=1, keepdims=True), (1, nb_channels_ref))


        chunk_duration = rnd.uniform(m['chunk_dur_min'], m['chunk_dur_max'])
        chunk_duration = int(chunk_duration * fs_ref)

        chunk_start = rnd.randint(0, y.shape[0]-chunk_duration)
        chunk_ind = chunk_start + np.array([0, chunk_duration])

        #curr_maskerfile = {'soundfile': soundfile, 'chunk_indices': chunk_ind}
        #masker_struct.append(curr_maskerfile)

        chunk = y[chunk_ind[0]:chunk_ind[1],:]

        # Apply cosine ramp
        chunk = vsct.ramp(chunk, fs_ref, [m['ramp']]*2)

        i1 = masker_i
        i2 = min(masker_i+chunk.shape[0], masker.shape[0])
        masker[i1:i2,:] = chunk[0:i2-i1,:]
        masker_i += chunk.shape[0]
        d = masker_i / fs_ref

    masker = vsct.ramp(masker, fs, [0, m['ramp']])

    sf.write(out_filename, masker, fs_ref)

    return out_filename, source_files

#
# def combine_target_masker(in_target, in_masker, m, out_filename):
#     # add silence before and after target sentence
#     target = process_pad(in_target, m, 'padded_target.wav')
#
#     # combine target and masker soundfiles


# #-------------------------------------------------------
#
# def parse_crm_corpus(m):
#     """
#     'returns call_signs, colours, and numbers for CRM stimuli in three lists'
#     """
#
#     call_signs = list()
#     colours = list()
#     numbers = list()
#     for file in glob(folder+filemask+'*.wav'):
#         filename = os.path.splitext(os.path.basename(file))[0]
#
#         parts = filename.split('_')
#
#         call_signs.append(parts[0])
#         colours.append(parts[1])
#         numbers.append(parts[2])
#
#     call_signs = list(set(call_signs))
#     colours = list(set(colours))
#     numbers = list(set(list(map(int, numbers))))
#
#     return call_signs, colours, numbers
#
#
# #-------------------------------------------------------
#
# def get_file_list(folder, mask):
#     lst = [os.path.basename(x) for x in glob(folder+mask+'*.wav')]
#
#     return lst

#===============================================================================
if __name__ == '__main__':

    # patterns = dict()
    # patterns['include'] = ['*.wav', '*.mp3', '*.txt']
    # patterns['exclude'] = ['K*', '2*.txt']
    # lst = get_file_list_from_shell_pattern(patterns, '/Users/egaudrain/Music')

    # lst = get_file_list_from_re_pattern("(.*/)?2[^/]*", '/Users/egaudrain/Music')
    #
    # print("\n".join(lst))

    m = dict()
    m['module'] = 'gibberish'
    m['seed'] = 1
    m['shell_pattern'] = {'include': '*.wav'}
    m['force_fs'] = 22050
    m['chunk_dur_min'] = .4
    m['chunk_dur_max'] = .5
    m['total_dur'] = 2
    m['ramp'] = .05


    f, s = process_gibberish('../test/gibberish_stereo/', m, '../test/test_gibberish.wav')
    print(f)
    print(s)
