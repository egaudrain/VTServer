# test_vt-client

import unittest

import socket, sys, json, time, subprocess, signal, shutil, os
import soundfile as sf
import numpy as np
from matplotlib import pyplot as plt


HOST, PORT = "127.0.0.1", 1996

def make_config_file():
    cfg = """
    {
        "host": "%s",
        "port": %d,
        "logfile": "./log/vt_server.log",
        "loglevel": "DEBUG",
        "cachefolder": "./cache",
        "cacheformat": "flac",
        "cacheformatoptions": {},
        "lame": "/usr/bin/lame"
    }
    """ % (HOST, PORT)
    with open("vt_server.conf.json", "w") as cfg_file:
        cfg_file.write(cfg)
    cfg = json.loads(cfg)
    os.makedirs(os.path.dirname(cfg['logfile']))
    os.makedirs(cfg['cachefolder'])

def cleanup():
    shutil.rmtree('./cache', ignore_errors=True)
    shutil.rmtree('./log', ignore_errors=True)

def start_server():
    p = subprocess.Popen(['python',  '../src/vt_server.py'])
    time.sleep(.6)
    return p

def stop_server(p):
    if p is not None:
        p.send_signal(signal.SIGINT)
        time.sleep(.5)
        p.wait(5)
    else:
        print("There is no server to stop.")

def send(data):

    if type(data)!=type(""):
        data_ = json.dumps(data)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Connect to server and send data
        sock.connect((HOST, PORT))
        sock.sendall(bytes(data_ + "\n", "utf-8"))
        #print("Sent:\n{}".format(json.dumps(data, indent=2)))
        # Receive data from the server and shut down
        received = str(sock.recv(1024), "utf-8")
        #print("Received: {}".format(received))

        try:
            res = json.loads(received)
            return res
        except:
            print("Something went wrong in decoding JSON:\n%s" % received)
            return False

class QueryTests(unittest.TestCase):

    p = None

    def setUp(self):
        cleanup()
        make_config_file()
        self.p = start_server()

    def tearDown(self):
        stop_server(self.p)
        cleanup()

    def _base_query(self):
        q = dict()
        q['action'] = 'process'
        q['file']   = './audio/Beer.wav' # >> /Users/egaudrain/Sources/VTServer/test/fa+_200ms.wav'
        q['stack']  = list()
        q['mode']   = 'sync'
        q['cache']  = 1
        return q

    def assertSoundFilesEqual(self, a, b):
        x_a, fs_a = sf.read(a)
        x_b, fs_b = sf.read(b)

        self.assertEqual(fs_a, fs_b)
        self.assertTrue(np.array_equal(x_a, x_b))

    def test_queries(self):

        with self.subTest("Server status"):
            """
            Testing if the server starts and we can poll status.
            """

            r = send({'action': 'status'})

            self.assertIsNot(r, False)
            self.assertEqual(r['out'], 'ok')


        with self.subTest("Simple modules"):
            q = self._base_query()

            q['stack'].append({
                'module':   "ramp",
                'duration': 51e-3,
                'shape':    "cosine"
            })
            q['stack'].append({
                'module': "pad",
                'before': 500e-3,
                'after':  500e-3
            })
            q['format'] = "flac"

            res = send(q)

            self.assertTrue(res['out']=='ok')

        # Nest

        with self.subTest("Empty stack"):
            q = self._base_query()
            res = send(q)
            self.assertTrue(res['out']=='ok')
            self.assertSoundFilesEqual(q['file'], res['details'])

        with self.subTest("Mixin"):
            q = self._base_query()
            q['stack'].append({
                "module": "mixin",
                "file": "./audio/tone1kHz.wav",
                "levels": [0, -6],
                "pad": [0, 0, 0, 0],
                "align": "right"
                })
            r = send(q)
            self.assertEqual(r['out'], 'ok')
            self.assertSoundFilesEqual(r['details'], './audio/test_mixin.flac')

        with self.subTest("World"):
            q = self._base_query()
            q['stack'].append({'module': 'world', 'f0': "-12st", 'vtl': "*1"})
            r = send(q)
            self.assertEqual(r['out'], 'ok')
            self.assertSoundFilesEqual(r['details'], './audio/test_world.flac')

        with self.subTest("Mixin with subquery"):
            q = self._base_query()
            q['stack'].append({
                "module": "mixin",
                "file": {"action": "process", "file": 'audio/Beer.wav', "stack": [{"module": "world", "f0": "+12st", "vtl": "-5st"}]},
                "levels": [0, -6],
                "pad": [0, 0, 1, 0],
                "align": "left"
                })
            r = send(q)
            self.assertEqual(r['out'], 'ok')
            self.assertSoundFilesEqual(r['details'], './audio/test_mixin-subq.flac')

        with self.subTest("Vocoder"):
            q = self._base_query()
            q['stack'].append({
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
                    "random_seed": 1,
                    "filter_before": False,
                    "filter_after": True
                    }
            })
            r = send(q)
            self.assertEqual(r['out'], 'ok')
            self.assertSoundFilesEqual(r['details'], './audio/test_vocoder.flac')

        with self.subTest("Subquery"):
            q = self._base_query()
            qq = {
                'file': ['audio/Beer.wav']*3,
                'stack': [
                    {
                        'module': 'pad',
                        'before': 100e-3,
                        'after':  100e-3
                    }
                ]
            }

            q['file' ] = qq
            q['stack'].append({'module': 'world', 'f0': "-12st", 'vtl': "+3st"})
            r = send(q)
            self.assertEqual(r['out'], 'ok')
            self.assertSoundFilesEqual(r['details'], './audio/test_subq.flac')

        with self.subTest("Concatenate subqueries"):
            q = self._base_query()
            q['file'] = list()
            f0s = np.cumsum(np.array([0, 2, 2, 1, 2, 2, 2, 1]))
            for f0 in f0s:
                q['file'].append({
                    'file': 'audio/Beer.wav',
                    'stack': [
                        {
                            'module': 'world',
                            'f0': "+%dst" % f0
                        }
                    ]
                })

            r = send(q)
            self.assertEqual(r['out'], 'ok')
            self.assertSoundFilesEqual(r['details'], './audio/test_concat-subq.flac')

        with self.subTest("Async"):
            q = self._base_query()
            q['stack'].append({'module': 'world', 'f0': "-18st", 'vtl': "+5st"})
            q['mode'] = 'async'

            r = {'out': 'wait'}
            while r['out']=='wait':
                r = send(q)
                time.sleep(.1)

            self.assertEqual(r['out'], 'ok')
            self.assertSoundFilesEqual(r['details'], './audio/test_async.flac')


if __name__ == '__main__':
    unittest.main(verbosity=2)
