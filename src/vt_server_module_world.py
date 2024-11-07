#!/usr/bin/env python3
# coding: utf-8

MODULE_TYPE = 'modifier'

"""
vt_server_module_world
======================

This module defines the *world* processor based on `pyworld <https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder>`_,
a module wrapping `Morise's WORLD vocoder <https://github.com/mmorise/World>`_.

Here are some examples of module instructions:

.. code-block:: json

    {
        "module": "world",
        "f0":     "*2",
        "vtl":    "-3.8st"
    }

If a key is missing (here, **duration**) it is considered as ``None``, which means this part is left unchanged.

**f0** can take the following forms:

    * ``*`` followed by a number, in which case it is multiplicating ratio applied to the
      whole f0 contour. For instance ``*2``.

    * a positive or negative number followed by a unit (``Hz`` or ``st``). This will behave
      like an offset, adding so many Hertz or so many semitones to the f0 contour.

    * ``~`` followed by a number, followed by a unit (only ``Hz``). This will
      set the *average* f0 to the defined value.

**vtl** is defined similarly:

    * ``*`` represents a multiplier for the vocal-tract length. Beware, this is not a multiplier
      for the spectral envelope, but its inverse.

    * offsets are defined using the unit ``st`` only.

**duration**:

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
    Receives an :mod:`re` match object from parsing module arguments and do some basic checking.

    :param mo: The argument to parse.
    :type mo:  re.Match
    :param purpose: Purpose is `'f0'`, `'vtl'` or `'duration'`.

    :return: A tuple of the form ``(args_ok, args)``: ``args_ok`` is True or False depending on whether
             the argument is fine or not. ``args`` contains a dictionary with the parsed out argument:

                `v`
                    is the value as a float.

                `u`
                    is the unit for offsets, or None for ratios.

                `~`
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
            if isinstance(m[k], dict):
                if 'u' in m[k] and 'v' in m[k] and '~' in m[k]:
                    continue
            elif m[k] is None:
                continue
            else:
                args_ok, args = check_arguments(RE[k].match(m[k]), k)
                if not args_ok:
                    raise ValueError("[world] Error while parsing argument %s (%s): %s" % (k, m[k], args))
                else:
                    m[k] = args

    return m

class Fast2DInterp():
    """
    Creates an interpolant object using modern scipy interpolation methods.
    For linear interpolation, uses RegularGridInterpolator.
    For cubic interpolation, uses RectBivariateSpline.
    """
    def __init__(self, x, y, z, ofrv=None, type='linear'):
        self.type = type
        self.x = x
        self.y = y
        self.z = z.copy()  # Make a copy to ensure we don't modify the original data
        
        if self.type == 'cubic':
            self.interpolant = spi.RectBivariateSpline(x, y, z)
        elif self.type == 'linear':
	    # normalization	
            z_min, z_max = np.min(z), np.max(z)
            self.z = np.clip(z, z_min, z_max)
            # Ensure z is in the correct orientation for RegularGridInterpolator
            if z.shape[0] == len(x) and z.shape[1] == len(y):
                self.z = z
            else:
                self.z = z.T
            
	    # z_min for out of range values
            self.interpolant = spi.RegularGridInterpolator(
                (self.x, self.y), 
                self.z,
                method='linear',
                bounds_error=False,
                fill_value=ofrv if ofrv is not None else z_min
            )

        self.x_range = (x[0], x[-1])
        self.y_range = (y[0], y[-1])
        self.ofrv = ofrv

    def is_in_range(self, w, r):
        return np.logical_and(w >= r[0], w <= r[1])

    def __call__(self, x, y):
        return self.interp(x, y)

    def interp(self, x, y):
        if self.type == 'cubic':
            return self.interpolant(x, y)
        elif self.type == 'linear':
            if np.isscalar(x) and np.isscalar(y):
                points = np.array([[x, y]])
                result = self.interpolant(points)
                return result[0]
            else:
                X, Y = np.meshgrid(x, y, indexing='ij')
                points = np.stack([X.flatten(), Y.flatten()], axis=-1)
                result = self.interpolant(points)
                result = result.reshape(len(x), len(y))  # define results
                # control min value
                result = np.maximum(result, np.min(self.z) * 0.1)
                return result

def process_world(in_filename, m, out_filename):
    """
    Processes the file **in_filename** according to parameters **m**, and stores results in **out_filename**.

    The first step is to analyse the sound file to extract its f0, spectral envelope and
    aperiodicity map. The results of this operation are cached in a pickle file.

    The parameters for this module are:

    :param f0: Either an absolute f0 value in Hertz ``{### Hz}``, a change in semitones ``{### st}`` or a ratio ``{\*###}``.
    :param vtl: Same for vocal-tract length (only semitones and ratio).
    :param duration: Either an absolute duration in seconds ``{~###s}``, an offset in seconds ``{+/-###s}``, or a ratio ``{\*###}``.
    """

    # Analysis
    dat_folder = os.path.join(vsc.CONFIG['cachefolder'], m['module'])
    if not os.path.exists(dat_folder):
        os.makedirs(dat_folder)

    dat_filename = os.path.join(dat_folder, "dat_"+vsct.signature((os.path.abspath(in_filename), 'world v'+pyworld.__version__))+'.pickle')
    try:
        # The file already exists so we just load it
        t1 = time.time()
        tp1 = time.process_time()

        dat = pickle.load(open(dat_filename, "rb"))
        f0, sp, ap, fs, rms_x = dat['f0'], dat['sp'], dat['ap'], dat['fs'], dat['rms']

        if 'frame_period' in dat and pyworld.default_frame_period != dat['frame_period']:
            raise Exception("The frame period in the pickled file does not match that of the version of pyworld. We regenerate it.")

        t2 = time.time()
        tp2 = time.process_time()
        vsl.LOG.info("[world (v%s)] Loaded f0, sp and ap from '%s' in %.2f ms (%.2f ms of processing time)" % (pyworld.__version__, dat_filename, (t2-t1)*1e3, (tp2-tp1)*1e3))

    except:
        t1 = time.time()
        tp1 = time.process_time()
        x, fs = sf.read(in_filename)
        rms_x = vsct.rms(x)
        f0, sp, ap = pyworld.wav2world(x, fs)

        pickle.dump({'f0': f0, 'sp': sp, 'ap': ap, 'fs': fs, 'rms': rms_x, 'file': in_filename, 'world_version': pyworld.__version__, 'frame_period': pyworld.default_frame_period}, open(dat_filename, 'wb'))
        vsct.job_file(dat_filename, [in_filename], None)

        t2 = time.time()
        tp2 = time.process_time()
        vsl.LOG.info("[world (v%s)] Extracted f0, sp and ap from '%s' in %.2f ms (%.2f ms of processing time)" % (pyworld.__version__, in_filename, (t2-t1)*1e3, (tp2-tp1)*1e3))

    # Modification of decomposition
    m = parse_arguments(m)

    nfft = (sp.shape[1]-1)*2
    f = np.arange(sp.shape[1]) / nfft * fs
    t = np.arange(sp.shape[0]) * pyworld.default_frame_period / 1e3

    # F0
    if (m['f0'] is None) or (m['f0']['u'] is None and m['f0']['v']==1) or (m['f0']['u'] is not None and m['f0']['v']==0 and not m['f0']['~']):
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
            vsl.LOG.info("[world] VTL modification - st: %.2f, ratio: %.3f" % (m['vtl']['v'], vtl_ratio))  
        new_f = f * vtl_ratio

        if np.any(new_f > fs/2):
            vsl.LOG.warning("[world] Some frequencies exceed Nyquist frequency, capping at %.1f Hz" % (fs/2))
            new_f = np.minimum(new_f, fs/2)


    # Duration
    if (m['duration'] is None) or (m['duration']['u'] is None and m['duration']['v']==1) or (m['duration']['u'] is not None and m['duration']['v']==0 and not m['duration']['~']):
        new_t = None
    else:
        if m['duration']['u'] is None:
            new_t = np.linspace(t[0], t[-1], int(m['duration']['v']*len(t)))
        elif m['duration']['u']=='s':
            if m['duration']['~']:
                new_t = np.linspace(t[0], t[-1], int(m['duration']['v']/pyworld.default_frame_period*1e3))
            else:
                new_duration = m['duration']['v'] + t[-1]
                if new_duration<=0:
                    raise ValueError("[world] This is not good, the new duration is negative or null (%.3f s)... This is what we parsed: %s." % (new_duration, repr(m['duration'])))
                new_t = np.linspace(t[0], t[-1], int(new_duration/pyworld.default_frame_period*1e3))

    # Now we rescale f0, sp and ap if necessary
    if new_f is None and new_t is None:
        new_sp = sp
        new_ap = ap
    else:
        if new_t is None:
            new_t = t
        else:
            uv = new_f0==0
            new_f0_tmp = new_f0[np.logical_not(uv)]
            new_f0 = spi.interp1d(t[np.logical_not(uv)], new_f0_tmp, kind='cubic', fill_value=(new_f0_tmp[0], new_f0_tmp[-1]), bounds_error=False, assume_sorted=True)(new_t)
            new_uv = spi.interp1d(t, uv*1.0, assume_sorted=True)(new_t)>.5
            new_f0[new_uv] = 0

        if new_f is None:
            new_f = f

        # Interp of spectral envelope and aperiodicity map
        new_sp = Fast2DInterp(t, f, sp)(new_t, new_f)
        new_ap = Fast2DInterp(t, f, ap)(new_t, new_f)
        
        # control for spectral envelope
        if np.any(np.isnan(new_sp)) or np.any(new_sp <= 0):
            vsl.LOG.warning("[world] Invalid spectral envelope values detected, applying fixes...")
            new_sp = np.nan_to_num(new_sp, nan=np.min(sp[sp > 0]))
            new_sp = np.maximum(new_sp, np.min(sp[sp > 0]))

        # control for aperiodicity
        if np.any(np.isnan(new_ap)) or np.any(new_ap < 0) or np.any(new_ap > 1):
            vsl.LOG.warning("[world] Invalid aperiodicity values detected, applying fixes...")
            new_ap = np.clip(np.nan_to_num(new_ap, nan=0), 0, 1)


    new_f0, new_sp, new_ap = regularize_arrays(new_f0, new_sp, new_ap)
    y = pyworld.synthesize(new_f0, new_sp, new_ap, fs)

    y = y / vsct.rms(y) * rms_x

    y, s = vsct.clipping_prevention(y)
    if s!=1:
        vsl.LOG.info("[world (v%s)] Clipping was avoided during processing of '%s' to '%s' by rescaling with a factor of %.3f (%.1f dB)." % (pyworld.__version__, in_filename, out_filename, s, 20*np.log10(s)))

    sf.write(out_filename, y, fs)

    return out_filename

def regularize_arrays(*args):
    """
    Making sure the arrays passed as arguments are in the right format for pyworld.
    """
    out = list()
    for x in args:
        out.append(np.require(x, requirements='C'))
    return tuple(out)

if __name__=="__main__":
    # test parse_arguments

    vsc.CONFIG['cachefolder'] = '../test/cache'
    vsc.CONFIG['logfile'] = '../test/vt_server.log'

    if not os.path.exists(vsc.CONFIG['cachefolder']):
        os.makedirs(vsc.CONFIG['cachefolder'])

    vsl.LOG.addHandler(vsl.get_FileHandler(vsc.CONFIG['logfile']))

    m = {'module': 'world', 'duration': '~.2s'}
    in_file  = "../test/Man480.wav"
    out_file = "../test/Man480_test.wav"
    print("Starting to process files...")
    vsl.LOG.debug("Starting to process files...")

    t0 = time.time()

    f = process_world(in_file, m, out_file)

    print("Well, it took %.2f ms" % ((time.time()-t0)*1e3))

    print(f)