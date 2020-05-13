#!/usr/bin/env python3
# coding: utf-8

"""
``vt_server_module_vocoder``
============================

This module defines the *world* processor based on `vocoder <https://github.com/egaudrain/vocoder>`_,
a MATLAB vocoder designed to be highly programmable.

Here is and example of module instructions:

.. code-block:: json

    {
        "module": "vocoder",
        "fs": 44100,
        "analysis_filters": {
            "f": { "fmin": 100, "fmax": 8000, "n": 8, "scale": "greenwood" },
            "method": { "family": "butterworth", "order": 3, "zero-phase": true }
            },
        "synthesis_filters": "analysis_filters",
        "envelope": {
            "method": "low-pass",
            "rectify": "half-wave",
            "order": 2,
            "fc": 160
            },
        "synthesis": {
            "carrier": "sin",
            "filter_before": false,
            "filter_after": true
            }
    }

The ``fs`` attribute is optional but can be used to speed up processing. The filter
definitions that are generated depend on the sampling frequency, so the it has to
be known to generate the filters. If the argument is not passed, it will be read from
the file that needs processing. Passing the sampling frequency as an attribute will
speed things up as we don't need to open the sound file to check its sampling rate.
However, beware that if the ``fs`` does not match that of the file, you will get an
error.

The other attributes are as follows:

``analysis_filters``
--------------------

``analysis_filters`` is a dictionary defining the filterbank used to analyse the
input signal. It defines both the cutoff frequencies ``f`` and the filtering ``method``.

``f``: Filterbank frequencies
'''''''''''''''''''''''''''''

These can either be specified as an array of values, using a predefined setting, or
by using a regular method.

If ``f`` is a numerical array, the values are used as frequencies in Hertz.

If ``f`` is a string, it refers to a predefined setting. The predefined values are:
``ci24`` and ``hr90k`` refering to the default map of cochlear implant manufacturers
Cochlear and Advanced Bionics, respectively.

Otherwise ``f`` is a dictionary with the following items:

    ``fmin``
        The starting frequency of the filterbank.

    ``fmax``
        The end frequency of the filterbank.

    ``n``
        The number of channels.

    ``scale`` : [optional]
        The scale on which the frequencies are divided into channels. Default is
        ``log``. Possible values are ``greenwood``, ``log`` and ``linear``.

    ``shift`` : [optional]
        A shift in millimiters, towards the base. Note that the shift is applied
        after all other calculations so the ``fmin`` and ``fmax`` boundaries will
        not be respected anymore.

Filtering ``method``
''''''''''''''''''''

A dictionary with the following elements:

    ``family``
        The type of filter. At the moment only ``butterworth`` is implemented.

        For ``butterworth``, the following parameters have to be provided:

        ``order``
            The actual order of the filter. Watch out, that this is the order that
            is actually achieved. Choosing ``true`` for ``zero-phase`` means only
            even numbers can be provided.

        ``zero-phase``
            Whether a zero-phase filter is being used. If ``true``, then :func:`filtfilt`
            is used instead of :func:`filt`.

        Unlike in the MATLAB version, this is implemented with second-order section
        filters (:func:`sosfiltfilt` and :func:`sosfilt`).


``synthesis_filters``
---------------------

It can be string ``"analysis_filters"`` to make them identical to the analysis filters.
This is also what happens if the element is omitted or ``null``.

Otherwise it can be a dictionary similar to ``analysis_filter``. The number of channels
has to be the same. If it differs, an error will be returned.


``envelope``
------------

That specifies how the envelope is extracted.

    ``method``
        Can be ``low-pass`` or ``hilbert``.

        For ``low-pass``, the envelope is extracted with rectification and low-pass
        filtering. The following parameters are required:

            ``rectify``
                The wave rectification method: ``half-wave`` or ``full-wave``.

            ``order``
                The order of the filter used for envelope extraction. Again, this
                is the effective order, so only even numbered are accepted because
                the envelope is extracted with a zero-phase filter.

            ``fc``
                The cutoff of the envelope extraction in Hertz. Can be a single
                value or a value per channel.


``synthesis``
-------------

The ``synthesis`` field describes how the resynthesis should be performed.

    ``carrier``
        Can be ``noise`` or ``sin`` (``low-noise`` and ``pshc`` are not implemented).

    ``filter_before``
        If ``true``, the carrier is filtered before multiplication with the envelope (default is ``false``).

    ``filter_after``
        If true, the modulated carrier is refiltered in the band to suppress sidebands
        (default is ``true``). Keep in mind that if you filter broadband carriers both
        before and after modulation you may alter the spectral shape of your signal.

If the ``carrier`` is ``noise``, then a random seed can be provided in ``random_seed``
to have frozen noise. If not the random number generator will be initialized with the
current clock. Note that for multi-channel audio files, the seed is used for each
channel. If no seed is given, the various chennels will have different noises as
carriers. To have correlated noise across chennels, pass in a (random) seed.

If the ``carrier`` is ``sin``, the geometric mean of the band's cutoffs are used unless
attribute ``f`` is provided, in which case it defines the frequencies.

Content
-------

.. Created on 2020-03-27.

"""

import vt_server_config as vsc
import vt_server_logging as vsl
import vt_server_common_tools as vsct

import time, os, re, pickle, collections

import numpy as np
from scipy import signal

import soundfile as sf

FB_PRESETS = {
    'ci24':  [188,313,438,563,688,813,938,1063,1188,1313,1563,1813,2063,2313,2688,3063,3563,4063,4688,5313,6063,6938,7938],
    'hr90k': [250,416,494,587,697,828,983,1168,1387,1648,1958,2326,2762,3281,3898,4630,8700]
    }

def freq2mm(frq):
    """
    Converts frequency to millimeters from apex using Greenwood's formula.
    """
    a= .06 # appropriate for measuring basilar membrane length in mm
    k= 165.4 #

    return (1/a) * np.log10(frq/k + 1)

def mm2freq(mm):
    """
    Converts millimeters from apex to frequency using Greenwood's formula.
    """
    a= .06 # appropriate for measuring basilar membrane length in mm
    k= 165.4 #

    return 165.4 * (10**(a * mm)- 1)

def parse_frequency_array(fa):
    """
    Parses a frequency array definition as part of a filter bank definition.
    """

    if isinstance(fa, (str, bytes)) and fa in FB_PRESETS.keys():
        return np.array(FB_PRESETS[fa])

    elif isinstance(fa, list):
        if all(isinstance(x, (int, float)) for x in fa):
            return np.array(fa)
        else:
            raise ValueError("[vocoder] A frequency array definition is a list but not all elements are numeric: %s." % repr(fa))

    elif isinstance(fa, dict):
        for mk in ['fmin', 'fmax', 'n']:
            if (mk not in fa) or (not isinstance(fa[mk], (int, float))):
                raise ValueError("[vocoder] The frequency array definition must have a key '%s' that contains a numerical value: %s." % (mk, repr(fa)))

        if fa['n']<=0:
            raise ValueError("[vocoder] The number of channels must be >= 1: %d given." % fa['n'])

        if 'scale' not in fa:
            fa['scale'] = 'log'

        if fa['scale']=='log':
            frq = np.exp(np.linspace(np.log(fa['fmin']), np.log(fa['fmax']), fa['n']+1))
            if 'shift' in fa:
                frq = mm2freq( freq2mm(frq) + fa['shift'] )
        elif fa['scale']=='greenwood':
            mm = np.linspace(freq2mm(fa['fmin']), freq2mm(fa['fmax']), fa['n']+1)
            if 'shift' in fa:
                mm = mm + fa['shift']
            frq = mm2freq(mm)
        elif fa['scale']=='linear':
            frq = np.linspace(fa['fmin'], fa['fmax'], fa['n']+1)
            if 'shift' in fa:
                frq = mm2freq( freq2mm(frq) + fa['shift'] )
        else:
            raise ValueError("[vocoder] The type of scale '%s' is not known for the frequency array definition." % fa['scale'])

        return frq

    else:
        raise ValueError("[vocoder] Could not parse frequency array definition: %s" % repr(fa))

def parse_filterbank_method(method, freq, fs):
    """
    Parses the method part of the filterbank definition and creates the filters based on
    the ``freq`` array and the sampling frequency ``fs``.
    """
    if not isinstance(method, dict):
        raise ValueError("[vocoder] The filterbank method element is not a dictionary: %s." % repr(method))

    if 'family' not in method:
        raise ValueError("[vocoder] The filterbank method element defines no 'family': %s." % repr(method))

    if method['family']=='butterworth':

        for mk in ['order', 'zero-phase']:
            if (mk not in method):
                raise ValueError("[vocoder] The method definition for family 'butterworth' must have a key '%s': %s." % (mk, repr(method)))

        if method['zero-phase']:
            ord = method['order'] / 2
            filter_function = 'sosfiltfilt'
        else:
            ord = method['order']
            filter_function = 'sosfilt'

        if int(ord)!=ord:
            # The order is not integer anymore
            raise ValueError("[vocoder] The filter order has to be an integer after taking into account potential double filtering (if zero-phase is true).")

        # Because we use bandpass, the order is doubled, so we need to divide by two again
        ord = ord / 2

        filters = list()
        for i in range(len(freq)-1):
            if int(ord)!=ord:
                # We'll use a bandpass and a highpass and concatenate them
                sos_1 = signal.butter(ord*2, freq[i], 'highpass', analog=False, fs=fs, output='sos')
                sos_2 = signal.butter(ord*2, freq[i+1], 'lowpass', analog=False, fs=fs, output='sos')
                sos = np.concatenate((sos_1, sos_2), axis=0)
            else:
                sos = signal.butter(ord, (freq[i], freq[i+1]), 'bandpass', analog=False, fs=fs, output='sos')

            filters.append(sos)

    return filters, filter_function


def parse_filterbank_definition(fbd, fs):
    """
    Parses a filterbank definition, used for ``analysis_filters`` and ``synthesis_filters``.
    """

    if not isinstance(fbd, dict):
        raise ValueError("[vocoder] The filterbank definition has to a dicionary: %s." % repr(fbd))

    if 'f' not in fbd:
        raise ValueError("[vocoder] The filterbank definition has no frequency array 'f' attribute: %s." % repr(fbd))
    else:
        fbd['f'] = parse_frequency_array(fbd['f'])

    if 'method' not in fbd:
        raise ValueError("[vocoder] The filterbank definition has no 'method' attribute: %s." % repr(fbd))
    else:
        fbd['filters'], fbd['filter_function'] = parse_filterbank_method(fbd['method'], fbd['f'], fs)

    return fbd

def parse_envelope_definition(env_def, fs):
    if 'method' not in env_def:
        raise ValueError("[vocoder] Envelope definition needs a 'method' attribute: %s." % repr(env_def))

    if env_def['method'] == 'low-pass':
        for mk in ['order', 'fc', 'rectify']:
            if (mk not in env_def):
                raise ValueError("[vocoder] The envelope definition for method 'low-pass' must have a key '%s': %s." % (mk, repr(env_def)))

        ord = env_def['order']/2
        if int(ord)!=ord:
            raise ValueError("[vocoder] The envelope definition order must be even: %s." % (repr(env_def)))

        env_def['filter'] = signal.butter(ord, env_def['fc'], 'lowpass', analog=False, fs=fs, output='sos')
        env_def['filter_function'] = 'sosfiltfilt'

    elif enve_def['method'] == 'hilbert':
        pass

    else:
        raise ValueError("[vocoder] The envelope definition method is unknown: %s." % (repr(env_def)))

    return env_def

def parse_carrier_definition(carrier, synth_fbd):
    """
    Parses a carrier definition for the ``synthesis`` block.
    """

    if 'carrier' not in carrier:
        raise ValueError("[vocoder] The synthesis block must have a 'carrier' attribute: %s." % repr(carrier))

    if 'filter_before' not in carrier:
        carrier['filter_before'] = False

    if 'filter_after' not in carrier:
        carrier['filter_after'] = True

    if carrier['carrier'] == 'noise':
        carrier['initial_random_state'] = np.random.get_state() # We will return the random generator to its previous state
        if 'random_seed' not in carrier:
            carrier['random_seed'] = None

    elif carrier['carrier'] == 'sin':
        if 'f' not in carrier:
            carrier['f'] = np.sqrt( synth_fbd['f'][0:-1] * synth_fbd['f'][1:] )

    return carrier

def parse_arguments(m, in_filename):
    """
    Parses arguments for the vocoder module. Unlike some other modules, it is important to know the
    sampling frequency we will be operating at. The filename can be read from the ``in_filename`` or
    it can be provided to speed-up things. Watchout, though, if the passed ``fs`` does not match that
    of ``in_filename``, you'll get an error.
    """

    # Analysis filters
    if 'analysis_filters' not in m:
        raise ValueError("[vocoder] For module 'vocoder', the 'analysis_filters' key must be provided.")

    if 'fs' not in m:
        inf = sf.info(in_filename)
        m['fs'] = inf.samplerate

    m['analysis_filters'] = parse_filterbank_definition(m['analysis_filters'], m['fs'])

    # Synthesis filters
    if 'synthesis_filters' not in m or m['synthesis_filters']=='analysis_filters':
        m['synthesis_filters'] = m['analysis_filters']
    else:
        m['synthesis_filters'] = parse_filterbank_definition(m['synthesis_filters'], m['fs'])

    if len(m['synthesis_filters']['filters']) != len(m['analysis_filters']['filters']):
        raise ValueError("[vocoder] The analysis and synthesis filterbanks must have the same number of channels.")

    # Envelope
    if 'envelope' not in m or not isinstance(m['envelope'], dict):
        raise ValueError("[vocoder] For module 'vocoder', the 'envelope' key must be provided.")

    m['envelope'] = parse_envelope_definition(m['envelope'], m['fs'])

    # Carrier
    if 'synthesis' not in m or not isinstance(m['synthesis'], dict):
        raise ValueError("[vocoder] For module 'vocoder', the 'synthesis' key must be provided.")

    m['synthesis'] = parse_carrier_definition(m['synthesis'], m['synthesis_filters'])

    return m

FILTER_FUNCTION_PATCH = {'sosfilt': signal.sosfilt, 'sosfiltfilt': signal.sosfiltfilt}

def env_hilbert(x):
    return abs(signal.hilbert(x))

def env_lowpass(x, rectif, filter, filter_function):
    return np.fmax( filter_function(filter, rectif(x)), 0)

def process_vocoder(in_filename, m, out_filename):
    """
    The main processing function for the module.
    """

    m = parse_arguments(m, in_filename)

    created_files = list()
    used_files    = list()

    # When opening the sound file, check that m['fs'] matches that of in_filename
    x, fs = sf.read(in_filename, always_2d=True)

    if m['fs'] != fs:
        raise ValueError("[vocoder] The provided sampling frequency ({}) does not match the sound file's frequency ({}).".format(m['fs'], fs))

    y = np.zeros(x.shape)

    n_bands = len(m['analysis_filters']['filters'])
    a_filter = FILTER_FUNCTION_PATCH[m['analysis_filters']['filter_function']]
    s_filter = FILTER_FUNCTION_PATCH[m['synthesis_filters']['filter_function']]

    if m['envelope']['method'] == 'hilbert':
        env = env_hilbert
    elif m['envelope']['method'] == 'low-pass':
        env_filter = FILTER_FUNCTION_PATCH[m['envelope']['filter_function']]
        if m['envelope']['rectify'] == 'half-wave':
            rectif = lambda x: np.fmax(x, 0)
        elif m['envelope']['rectify'] == 'full-wave':
            rectif = abs
        env = lambda x: env_lowpass(x, rectif, m['envelope']['filter'], env_filter)

    # If the audio is multichannel, we apply the vocoder to each channel
    for i_channel in range(x.shape[1]):

        # Note: we keep this in the loop. For stereo file, if no seed is given, the two
        # ears will be different. To have correlated noise across ears, pass a (random) seed.
        if m['synthesis']['carrier']=='noise':
            np.random.seed( m['synthesis']['random_seed'] )
            carrier = np.random.uniform(-.98, .98, x.shape[0])
            sin_carrier = False
        elif m['synthesis']['carrier']=='sin':
            t = np.arange(x.shape[0])/fs
            sin_carrier = True

        for i_band in range(n_bands):

            # Bandpass each band
            x_band = a_filter(m['analysis_filters']['filters'][i_band], x[:, i_channel])
            x_band_rms = vsct.rms(x_band)

            # Extracting the envelope
            x_band = env(x_band)

            # Generating the carrier
            if sin_carrier:
                carrier = np.sin(2*np.pi*m['synthesis']['f'][i_band]*t)

            if m['synthesis']['filter_before']:
                carr = s_filter(m['synthesis_filters']['filters'][i_band], carrier)
            else:
                carr = carrier

            x_band = x_band * carr

            if m['synthesis']['filter_after']:
                x_band = s_filter(m['synthesis_filters']['filters'][i_band], x_band)

            # Restoring RMS:
            x_band = x_band / vsct.rms(x_band) * x_band_rms

            y[:,i_channel] += x_band

    if m['synthesis']['carrier'] == 'noise':
        np.random.set_state(m['synthesis']['initial_random_state'])

    y, s = vsct.clipping_prevention(y)
    if s!=1:
        vsl.LOG.info("[vocoder] Clipping was avoided during processing of '%s' to '%s' by rescaling with a factor of %.3f (%.1f dB)." % (in_filename, out_filename, s, 20*np.log10(s)))

    sf.write(out_filename, y, fs)

    created_files.append(out_filename)

    return out_filename, created_files, used_files

#-----------------------------------------
if __name__=="__main__":
    # test parse_arguments
    # fa = [100, 'a', 200]
    # print(parse_frequency_array(fa))

    # Checking if butterworth bandpass filters double the order like in Matlab
    # fs = 44100
    # x = np.random.randn(fs*10)
    # import matplotlib.pyplot as plt
    #
    # sos1a = signal.butter(1, 1000, 'highpass', analog=False, fs=fs, output='sos')
    # sos1b = signal.butter(1, 2000, 'lowpass', analog=False, fs=fs, output='sos')
    #
    # y1 = signal.sosfilt(sos1a, x)
    # y1 = signal.sosfilt(sos1b, y1)
    # y1b = signal.sosfilt(np.concatenate((sos1a, sos1b), axis=0), x)
    #
    # f1, _, Sxx1 = signal.spectrogram(y1, fs, nperseg=1024)
    # P1 = 10*np.log10(np.mean(abs(Sxx1)**2, axis=1))
    # f1b, _, Sxx1b = signal.spectrogram(y1b, fs, nperseg=1024)
    # P1b = 10*np.log10(np.mean(abs(Sxx1b)**2, axis=1))
    #
    # sos2 = signal.butter(2, [1000, 2000], 'bandpass', analog=False, fs=fs, output='sos')
    # y2 = signal.sosfilt(sos2, x)
    # f2, _, Sxx2 = signal.spectrogram(y2, fs, nperseg=1024)
    # P2 = 10*np.log10(np.mean(abs(Sxx2)**2, axis=1))
    #
    # fig = plt.figure()
    # ax  = fig.add_axes((.1, .1, .8, .8))
    #
    # ax.semilogx(f1, P1, label='highpass-seq')
    # ax.semilogx(f1b, P1b, label='highpass-concat')
    # ax.semilogx(f2, P2, label='bandpass')
    #
    # ax.set_xlim((500, 4000))
    # ax.set_ylim((-125, -75))
    #
    # ax.legend()
    #
    # fig.set_size_inches((10, 6))
    #
    # fig.savefig("vocoder_test_filter_order.png", dpi=300)

    vsc.CONFIG['cachefolder'] = 'test/cache'
    vsc.CONFIG['logfile'] = 'test/vt_server.log'

    if not os.path.exists(vsc.CONFIG['cachefolder']):
        os.makedirs(vsc.CONFIG['cachefolder'])

    vsl.LOG.addHandler(vsl.get_FileHandler(vsc.CONFIG['logfile']))

    m = {
        "module": "vocoder",
        "fs": 44100,
        "analysis_filters": {
            "f": { "fmin": 100, "fmax": 8000, "n": 16, "scale": "greenwood" },
            "method": { "family": "butterworth", "order": 6, "zero-phase": True }
            },
        "synthesis_filters": "analysis_filters",
        "envelope": {
            "method": "low-pass",
            "rectify": "half-wave",
            "order": 2,
            "fc": 160
            },
        "synthesis": {
            "carrier": "noise",
            "filter_before": False,
            "filter_after": True
            }
    }
    #in_file  = "test/Beer.wav"
    #out_file = "test/Beer_test_cubic.wav"
    in_file  = "../test/Man480.wav"
    out_file = "../test/Man480_vocoded.wav"
    print("Starting to process files...")
    vsl.LOG.debug("Starting to process files...")

    t0 = time.time()

    f = process_vocoder(in_file, m, out_file)

    print("Well, it took %.2f ms" % ((time.time()-t0)*1e3))

    print(f)
