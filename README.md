VTServer: Voice Transformation Server
=====================================

The Voice Transformation Server is a Python TCP/IP server that receives commands to process a
(local) sound file with a stack of transformations. The modified file is then cached to be
served again upon identical request.

The server receives instructions as JSON encoded objects and returns a JSON encoded object
that, upon success, points to a file. The VTServer does not serve the file itself. This
is up to a web-server, for instance, to do so.

The VTServer can be deployed as a `systemd` service (on Linux) using the provided
install script (see below).

A basic PHP client is also provided in `/php-client`. It can be used as a relay to pass a JSON request
sent through a web-server.


Installation
------------

The server is written for Python 3.5+.

For `pysoundfile` you will need to install `libsndfile1` directly:

```
$sudo apt install libsndfile1 python3-pip
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

Usage
-----

Check the document in the `/doc` folder to see how instructions can be sent to the server.
Each module has its own set of instructions.
