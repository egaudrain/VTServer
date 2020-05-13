#!/usr/bin/env python3
# coding: utf-8

"""
``vt_server_module_world``
==========================

This module defines the *world* processor based on `pyworld <https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder>`_,
a module wrapping `Morise's WORLD vocoder <https://github.com/mmorise/World>`_.

Here are some examples of module instructions:

.. code-block:: json

    {
        "module": "world",
        "f0":     "*2",
        "vtl":    "-3.8st"
    }

If a key is missing (here, ``duration``) it is considered as ``None``, which means this part is left unchanged.

``f0`` can take the following forms:

    * ``*`` followed by a number, in which case it is multiplicating ratio applied to the
      whole f0 contour. For instance ``*2``.

    * a positive or negative number followed by a unit (``Hz`` or ``st``). This will behave
      like an offset, adding so many Hertz or so many semitones to the f0 contour.

    * ``~`` followed by a number, followed by a unit (only ``Hz``). This will
      set the *average* f0 to the defined value.

``vtl`` is defined similarly:

    * ``*`` represents a multiplier for the vocal-tract length. Beware, this is not a multiplier
      for the spectral envelope, but its inverse.

    * offsets are defined using the unit ``st`` only.

``duration``:

    * the ``*`` multiplier can also be used.

    * an offset can be defined in seconds (using unit ``s``).

    * the absolute duration can be set using ``~`` followed by a value and the ``s`` unit.

Note that in v0.2.8, WORLD is making the sounds 1 frame (5 ms) too long if no duration is specified. If you
specify the duration, it is generated accurately.

.. Created on 2020-03-20.
"""

import vt_server_config as vsc
import vt_server_logging as vsl
import vt_server_common_tools as vsct

import time, os, re, pickle

import numpy as np
import scipy.interpolate as spi

import pyworld
import soundfile as sf

RE = dict()
RE['f0'] = re.compile(r"([*+-~]?)\s*((?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)\s*(Hz|st)?")
RE['vtl'] = re.compile(r"([*+-]?)\s*((?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)\s*(st)?")
RE['duration'] = re.compile(r"([*+-~]?)\s*((?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)\s*(s)?")

def check_arguments(mo, purpose):
    """
    Receives an ``re`` match object from parsing module arguments and do some basic checking.
    Return a tuple ``(args_ok, args)``. ``args_ok`` is True or False depending on whether
    the argument is fine or not. ``args`` contains a dictionary with the parsed out argument:

    ``v``
        is the value as a float.

    ``u``
        is the unit for offsets, or None for ratios.

    ``~``
        if ``True``, then it denotes an absolute (average) value instead of an offset.
    """

    if mo is None:
        return False, "Not a valid argument."

    s, v, unit = mo.groups()

    if s=='*':
        if unit!=None:
            return False, "If a ratio is given (*), no unit should be given (got '%s')." % (unit)

        try:
            v_f = float(v)
        except ValueError:
            return False, "Could not parse value '%s'" % (v)

        return True, {'v': v_f, 'u': None, '~': False} # r for ratio

    if s=='~':
        if purpose=='f0' and unit!='Hz':
            return False, "If an average is given, the unit has to be 'Hz' (got '%s')." % unit
        elif purpose=='duration' and unit!='s':
            return False, "If fixed duration is given, the unit has to be 's' (got '%s')." % unit

        try:
            v_f = float(v)
        except ValueError:
            return False, "Could not parse value '%s'" % (v)

        return True, {'v': v_f, 'u': unit, '~': True} # r for ratio
    else:
        if unit==None:
            return False, "If an offset value is given ({}), a unit has to be given.".format(s+v)

        try:
            v_f = float(s+v)
        except ValueError:
            return False, "Could not parse value '%s'" % (s+v)

        return True, {'v': v_f, 'u': unit, '~': False} # o for offset


def parse_arguments(m):
    for k in ['f0', 'vtl', 'duration']:
        if k not in m:
            m[k] = None
        else:
            args_ok, args = check_arguments(RE[k].match(m[k]), k)
            if not args_ok:
                raise ValueError("[world] Error while parsing argument %s (%s): %s" % (k, m[k], args))
            else:
                m[k] = args

    return m


def process_world(in_filename, m, out_filename):
    """
    Processes the file ``in_filename`` according to options ``m``, and store results in ``out_filename``.

    The first step is to analyse the sound file to extract its f0, spectral envelope and
    aperiodicity map. The results of this operation are cached in a pickle file.

    The options for this module are:

    * ``f0``: either an absolute f0 value in Hertz {### Hz}, a change in semitones {### st} or a ratio {* ###}.

    * ``vtl``: same for vocal-tract length (only semitones and ratio).

    * ``duration``: either an absolute duration in seconds {~###s}, an offset in seconds {+/-###s}, or a ratio {*###}.
    """

    created_files = list()
    used_files    = list()

    # Analysis
    dat_folder   = os.path.join(vsc.CONFIG['cachefolder'], m['module'])
    if not os.path.exists(dat_folder):
        os.makedirs(dat_folder)

    # To change the frame period, the default_frame_period has to be changed
    # pyworld.default_frame_period

    dat_filename = os.path.join(dat_folder, "dat_"+vsct.signature((os.path.abspath(in_filename), 'world v'+pyworld.__version__))+'.pickle')
    try:
        # The file already exists so we just load it
        t1 = time.time()
        tp1 = time.process_time()

        dat = pickle.load(open(dat_filename, "rb"))
        # We could check some things here like the file and the World version, but it should
        # be builtin the file signature.
        #f0, sp, ap, fs, rms_x, sp_interp, ap_interp = dat['f0'], dat['sp'], dat['ap'], dat['fs'], dat['rms'], dat['sp_interp'], dat['ap_interp']
        f0, sp, ap, fs, rms_x = dat['f0'], dat['sp'], dat['ap'], dat['fs'], dat['rms']

        if 'frame_period' in dat and pyworld.default_frame_period != dat['frame_period']:
            raise Exception("The frame period in the pickled file does not match that of the version of pyworld. We regenerate it.")

        t2 = time.time()
        tp2 = time.process_time()
        vsl.LOG.info("[world (v%s)] Loaded f0, sp and ap from '%s' in %.2f ms (%.2f ms of processing time)" % (pyworld.__version__, dat_filename, (t2-t1)*1e3, (tp2-tp1)*1e3))

        used_files.append(dat_filename)

    except:
        t1 = time.time()
        tp1 = time.process_time()
        x, fs = sf.read(in_filename)
        rms_x = vsct.rms(x)
        f0, sp, ap = pyworld.wav2world(x, fs)

        # Note: I thought of keeping the interpolant in the pickle file, but it
        # makes it way too big and the processing gain is relatively small

        pickle.dump({'f0': f0, 'sp': sp, 'ap': ap, 'fs': fs, 'rms': rms_x, 'file': in_filename, 'world_version': pyworld.__version__, 'frame_period': pyworld.default_frame_period}, open(dat_filename, 'wb'))

        t2 = time.time()
        tp2 = time.process_time()
        vsl.LOG.info("[world (v%s)] Extracted f0, sp and ap from '%s' in %.2f ms (%.2f ms of processing time)" % (pyworld.__version__, in_filename, (t2-t1)*1e3, (tp2-tp1)*1e3))

        created_files.append(dat_filename)

    # Modification of decomposition
    m = parse_arguments(m)

    nfft = (sp.shape[1]-1)*2
    f = np.arange( sp.shape[1] ) / nfft * fs
    t = np.arange( sp.shape[0] ) * pyworld.default_frame_period / 1e3

    # F0
    if (m['f0'] is None) or (m['f0']['u'] is None and m['f0']['v']==1) or (m['f0']['u'] is not None and m['f0']['v']==0 and not m['f0']['~']):
        # No change
        new_f0 = f0
    elif m['f0']['u'] is None:
        new_f0 = f0*m['f0']['v']
    else:
        if m['f0']['u']=='Hz':
            if m['f0']['~']:
                m_f0 = np.exp(np.mean(np.log(f0[f0!=0])))
                new_f0 = f0 / m_f0 * m['f0']['v']
            else:
                new_f0 = f0 + m['f0']['v']
        elif m['f0']['u']=='st':
            new_f0 = f0 * 2**(m['f0']['v']/12)

    # VTL
    if (m['vtl'] is None) or (m['vtl']['u'] is None and m['vtl']['v']==1) or (m['vtl']['u'] is not None and m['vtl']['v']==0):
        new_f = None
    else:
        if m['vtl']['u'] is None:
            vtl_ratio = m['vtl']['v']
        elif m['vtl']['u']=='st':
            vtl_ratio = 2**(m['vtl']['v']/12)
        new_f = f * vtl_ratio

    # Duration
    if (m['duration'] is None) or (m['duration']['u'] is None and m['duration']['v']==1) or (m['duration']['u'] is not None and m['duration']['v']==0 and not m['duration']['~']):
        new_t = None
    else:
        if m['duration']['u'] is None:
            # A ratio
            new_t = np.linspace(t[0], t[-1], int(m['duration']['v']*len(t)))
        elif m['duration']['u']=='s':
            if m['duration']['~']:
                # We assign a new duration
                new_t = np.linspace(t[0], t[-1], int(m['duration']['v']/pyworld.default_frame_period*1e3))
            else:
                # We extend the duration with a certain offset
                new_duration = m['duration']['v'] + t[-1] #len(t)/pyworld.default_frame_period
                if new_duration<=0:
                    raise ValueError("[world] This is not good, the new duration is negative or null (%.3f s)... This is what we parsed: %s." % (new_duration, repr(m['duration'])))
                new_t = np.linspace(t[0], t[-1], int(new_duration/pyworld.default_frame_period*1e3))

    # Now we rescale f0, sp and ap if necessary
    if new_f is None and new_t is None:
        # Both VTL and duration are unchanged
        new_sp = sp
        new_ap = ap
    else:
        if new_t is None:
            # Duration is not changed, we keep f0 as it is
            new_t = t
        else:
            # Duration is changed, we need to interpolate f0
            # This is a bit of a tricky business because there are zeros and we do
            # not want to interpolate those.
            uv = new_f0==0 # The unvoiced samples
            # We first interpolate over the unvoiced samples and stretch
            new_f0_tmp = new_f0[np.logical_not(uv)]
            new_f0 = spi.interp1d(t[np.logical_not(uv)], new_f0_tmp, kind='cubic', fill_value=(new_f0_tmp[0], new_f0_tmp[-1]), bounds_error=False, assume_sorted=True)(new_t)
            # Then we stretch the voice/unvoice information
            new_uv = spi.interp1d(t, uv*1.0, assume_sorted=True)(new_t)>.5
            new_f0[new_uv] = 0

        if new_f is None:
            # VTL is not changed
            new_f = f

        # Interp of spectral envelope and aperiodicity map
        new_sp = Fast2DInterp(t, f, sp)(new_t, new_f)
        new_ap = Fast2DInterp(t, f, ap)(new_t, new_f)

    new_f0, new_sp, new_ap = regularize_arrays(new_f0, new_sp, new_ap)
    y = pyworld.synthesize(new_f0, new_sp, new_ap, fs)

    y = y / vsct.rms(y) * rms_x

    y, s = vsct.clipping_prevention(y)
    if s!=1:
        vsl.LOG.info("[world (v%s)] Clipping was avoided during processing of '%s' to '%s' by rescaling with a factor of %.3f (%.1f dB)." % (pyworld.__version__, in_filename, out_filename, s, 20*np.log10(s)))


    sf.write(out_filename, y, fs)

    return out_filename, created_files, used_files


def regularize_arrays(*args):
    """
    Making sure the arrays passed as arguments are in the right format for pyworld.
    """
    out = list()
    for x in args:
        out.append( np.require(x, requirements='C'))
    return tuple(out)


class Fast2DInterp():
    """
    Creates an interpolant object based on ``scipy.interpolate.RectBivariateSpline`` but
    dealing with out of range values.

    The constructor is: ``Fast2DInterp(x, y, z, ofrv=None)`` where ``x`` and ``y``
    are 1D arrays and ``z`` is a 2D array. The optional argument ``ofrv`` defines
    the value used for out of range inputs. If ``ofrv`` is ``None``, then the
    default behaviour of ``RectBivariateSpline`` is kept, i.e. the closest value is
    returned.

    The default type is ``linear``, which then makes use of ``scipy.interpolate.interp2d``.
    With ``cubic``, the ``RectBivariateSpline`` is used.

    Note that the class is not so useful in the end when used with ``linear``, but
    is useful if you want to use cubic-splines.
    """

    def __init__(self, x, y, z, ofrv=None, type='linear'):
        self.type = type

        if self.type=='cubic':
            self.interpolant = spi.RectBivariateSpline(x, y, z)
        elif self.type=='linear':
            self.interpolant = spi.interp2d(y, x, z, kind='linear')
        else:
            raise ValueError('Interpolant type unknown: "%s"' % type)

        self.x_range = (x[0], x[-1])
        self.y_range = (y[0], y[-1])

        # Out of range value:
        self.ofrv = ofrv

    def is_in_range(self, w, r):
        return np.logical_and(w>=r[0], w<=r[1])

    def __call__(self, x, y):
        return self.interp(x, y)

    def interp_(self, x, y):
        if self.type=='cubic':
            return self.interpolant(x, y)
        elif self.type=='linear':
            return self.interpolant(y, x)

    def interp(self, x, y):
        if (np.isscalar(x) or len(x)==1) and (np.isscalar(y) or len(y)==1):
            if self.ofrv is not None:
                if self.is_in_range(x, self.x_range) and self.is_in_range(y, self.y_range):
                    o = self.interp_(x, y)[0,0]
                else:
                    o = self.ofrv
            else:
                o = self.interp_(x, y)[0,0]
        else:
            o = self.interp_(x, y)

            if self.ofrv is not None:
                s = np.logical_and(self.is_in_range(xx, self.x_range), self.is_in_range(yy, self.y_range))
                o[s] = self.ofrv

        return o


if __name__=="__main__":
    # test parse_arguments

    vsc.CONFIG['cachefolder'] = '../test/cache'
    vsc.CONFIG['logfile'] = '../test/vt_server.log'

    if not os.path.exists(vsc.CONFIG['cachefolder']):
        os.makedirs(vsc.CONFIG['cachefolder'])

    vsl.LOG.addHandler(vsl.get_FileHandler(vsc.CONFIG['logfile']))

    m = {'module': 'world', 'duration': '~.2s'}
    #in_file  = "test/Beer.wav"
    #out_file = "test/Beer_test_cubic.wav"
    in_file  = "../test/Man480.wav"
    out_file = "../test/Man480_test.wav"
    print("Starting to process files...")
    vsl.LOG.debug("Starting to process files...")

    t0 = time.time()

    f = process_world(in_file, m, out_file)

    print("Well, it took %.2f ms" % ((time.time()-t0)*1e3))

    print(f)
