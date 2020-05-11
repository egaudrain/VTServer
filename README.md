VTServer: Voice Transformation Server
=====================================

The Voice Transformation Server is a Python TCP/IP server that receives commands to process a
(local) sound file with a stack of transformations. The modified file is then cached to be
served again upon identical request.

The server receives instructions as JSON encoded objects and returns a JSON encoded object
that, upon success, points to a file. The VTServer does not serve the file itself. This
is up to a web-server, for instance, to do so.

You can run the VTServer directly from the command-line, or it can be deployed as a `systemd` service (on Linux) using the provided install script (see below).

A basic PHP client is also provided in `/php-client`. It can be used as a relay to pass a JSON request
sent through a web-server.

Full documentation can be found in the [`/docs`](https://egaudrain.github.io/VTServer/) folder. Here's an
example of processing instruction you can send:

```json
{
    "action": "process",
    "file": "/home/egaudrain/vt_server/test/sound.wav",
    "stack":
        [
            {"module": "world", "f0": "-12st", "vtl": "*1"},
            {
                "module": "vocoder",
                "fs": 44100,
                "analysis_filters": {
                    "f": { "fmin": 100, "fmax": 8000, "n": 16, "scale": "greenwood" },
                    "method": { "family": "butterworth", "order": 6, "zero-phase": true }
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
                    "filter_before": false,
                    "filter_after": true
                    }
            }
        ]
}

```

To get some information about the server, send:

```json
{ "action": "status" }
```

Installation
------------

The server is written for Python 3.5+.

For `pysoundfile` you will need to install `libsndfile1` directly:

```
$ sudo apt install libsndfile1 python3-pip
```

The Numpy and Scipy packages of the current Ubuntu 18.04 LTS are not new enough, so just get the latest
with `pip`.

Before running the server you will need to install external dependencies:

```
$ sudo -H pip3 install numpy scipy pysoundfile pyworld systemd
```

I wrote an install script for Linux Debian-based systems like Ubuntu. Just run `install.ubuntu.sh` and it should
do everything that's needed. Note that this is a very rudimentary script. It will install everything necessary in
`/usr/local/lib/vt_server`. Once installed, the server runs as user ``vt_server``.

The configuration for the server can be found in `/usr/local/etc/vt_server/vt_server.conf.json`. Watchout
if you modify the cache folder, make sure that the folder exists and that the user `vt_serve` has read/write
access to it.

To use 'mp3' as an output format, you need to install [LAME](https://lame.sourceforge.io/):

```
$ sudo apt install lame
```

There is a line in the `vt_server.conf.json` that indicates where the executable is located.

Usage
-----

Check the document in the [`/docs`](https://egaudrain.github.io/VTServer/) folder to see how instructions can be sent to the server. Each module has its own set of instructions.
