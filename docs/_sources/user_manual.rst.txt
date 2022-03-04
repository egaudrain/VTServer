***********
User manual
***********

Installation
============

Download the server from https://github.com/egaudrain/VTServer/archive/master.zip.

Note that the server hasn't been tested on Windows, only on macOS and Linux. In principle
it should also work, but so far nobody tried.

Dependencies
------------

The server is written for Python 3.5+, so you'll need to make sure you have this installed. On all platforms
you can use `Conda <https://www.anaconda.com/products/individual#Downloads>`_, or install your own Python if
it is not already there.

Once Python installed, you'll need to get `pip <https://pip.pypa.io/en/stable/installing/>`_ to be able to install
the external dependencies. If you used Conda as you package manager, you can also do these through it. On (Debian/Ubuntu) Linux
you can get pip through:

.. code-block:: text

    $ sudo apt install python3-pip

VTServer uses **pysoundfile** to read sound files. On Linux you will need to install `libsndfile1 <http://www.mega-nerd.com/libsndfile>`_ directly:

.. code-block:: text

    $ sudo apt install libsndfile1

It is also recommended to install **samplerate** for precise and efficient resampling. On Linux, that means you need to install `libsamplerate <http://www.mega-nerd.com/libsamplerate/>`_:

.. code-block:: text

    $ sudo apt install libsamplerate0

The Numpy and Scipy packages of the current Ubuntu 18.04 LTS are not new enough, so just get the latest with pip.
On macOS, it is also recommended to use pip to install these dependencies.

This can be done as follows:

.. code-block:: text

    $ sudo -H pip3 install numpy scipy pysoundfile pyworld samplerate

To use 'mp3' as an output format, you need to install `LAME <https://lame.sourceforge.io/>`__.

On Linux:

.. code-block:: text

    $ sudo apt install lame

On macOS with macport:

.. code-block:: text

    $ sudo port install lame

There is a line in the :file:`vt_server.conf.json` that indicates where the executable is located.


Running the server
------------------

For testing purposes, you can run the server from the command line. You can make
your own launching script to modify the default configuration that may not be suitable
for casual testing. Do something like this:

.. code-block:: python

    import sys

    sys.path.append('PATH TO THE VTSERVER SRC FOLDER')

    import vt_server
    import vt_server_config as vsc

    vsc.CONFIG["lame"] = '/opt/local/bin/lame'
    vsc.CONFIG["logfile"] = './vt_server.log'
    vsc.CONFIG["cachefolder"] = './cache'

    vt_server.main()

Here modify the config to point to the correct location for the LAME executable, and we keep the log and the
cache in the local folder.

Once the server is running in a terminal, you'll see some information if there's an error.
To see more, check the log file (in a new terminal):

.. code-block:: text

    $ tail -f vt_server.log


Running as a daemon
-------------------

For production, you'll want to run the server as a daemon. That's relatively easy to do on most platforms.
Here are provided facilities for Linux systems that support `systemd <https://www.freedesktop.org/wiki/Software/systemd/>`_ (Debian, Ubuntu).

You'll need to first install the Python systemd module:

.. code-block:: text

    $ sudo -H pip3 install systemd

Then just run :file:`install.ubuntu.sh` and it should do everything that's needed. Note that this is a very rudimentary script.
It will install everything necessary in :file:`/usr/local/lib/vt_server`. Once installed, the server runs as user `vt_server`.

The configuration for the server can be found in :file:`/usr/local/etc/vt_server/vt_server.conf.json`.
Watchout if you modify the cache folder, make sure that the folder exists and that the user `vt_server` has read/write access to it.

From there on, you can start, stop the server through:

.. code-block:: text

    $ sudo systemctl [start|stop] vt_server





Sending queries from a client
=============================

The VT Server package does not include a Python client, but it's very easy to build.
Assuming the server is running on its default address (127.0.0.1) and port (1996),
you can use the following function to send a command:

.. code-block:: python

    import socket
    import json

    HOST, PORT = "127.0.0.1", 1996

    def send(data):

        if type(data)!=type(""):
            data = json.dumps(data)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # Connect to server and send data
            sock.connect((HOST, PORT))
            sock.sendall(bytes(data + "\n", "utf-8"))
            print("Sent:     {}".format(data))
            # Receive data from the server and shut down
            received = str(sock.recv(1024), "utf-8")
            print("Received: {}".format(received))

            res = json.loads(received)

            if res['out']=='ok':
                return res
            else:
                print(res['details'])
                return None

In the examples below, we will be using this :func:`send` function to communicate
with the server.

General structure of a query
----------------------------

Queries are sent as JSON-encoded objects. From Python, you can construct your query
as a `dict`, and transform it to JSON with :func:`json.dumps` from the :mod:`json` module.

A query always start with an **action** key. The possible values are:

    "status"
        Returns a status message indicating that the server is running. It also
        indicates how many requests were processed since the last startup of the
        server, and how many jobs are in the :data:`JOBS` list.

    "process"
        This is what you need to apply modifications to a file.

For `"status"`, no other information needs to be provided.

For `"hash"` and `"process"`, the query also needs to contain a **file** field,
and a **stack** field.

    file
        The sound file(s) that will be processed. This can also be an array
        of files or of queries. The stack is applied to the concatenated result.
        The file path is relative to where the *server* is running from (not the client).
        *It is highly recommended to use absolute paths instead of relative paths.*
        Also note that the input sound files should be in a format understood by
        `linsndfile <http://www.mega-nerd.com/libsndfile/#Features>`__.

        Note: In version 2.2 it was possible to use " >> " to separate files. This
        has been removed in 2.3, but you can still use arrays. Support for subqueries
        as `file` of the main query has been added in 2.3.

    stack
        The list of processes that will be run on the file. Each item
        in the stack is an object that is specific to the type of processing.
        Each object must have a **module** attribute that is used to dispatch the
        processing. This can also be a list of stacks that apply to everyone of
        the files if **file** is an array (otherwise, the same stack is applied
        to all files before concatenation). See below for more details on stack
        definition.

In addition to these mandatory field, a number of optional fields can also be provided:

    mode
        `"async"` [default], `"sync"` or `"hash"`. In `sync` mode, the server will only
        send a response when the file is processed. In `async` mode, the server
        will respond immediately with a `"wait"` response. The client can probe
        periodically with the same request until the file is returned. `hash` only
        returns the hash of the request that is used as identifier (see below).

        Note: In 2.3, `"async"` became the default.

    format
        Specifies the output format of the sound files. Can be `"flac"`, `"wav"`
        (or anything else supported by `libsndfile <http://www.mega-nerd.com/libsndfile/>`_, or `"mp3"`
        (if `LAME <http://www.mega-nerd.com/libsndfile/>`_ is installed). If none is provided,
        then the default cache format is used (see :mod:`vt_server_config`). For sub-queries,
        this is automatically changed to the server's cache format.

    format_options
        Specifies options (as a dictionary) for the selected
        format. At the moment, only `bitrate` is specified (as an integer in kbps)
        for format `"mp3"` (see :py:func:`vt_server_brain.encode_to_format` for details).
        For sub-queries, this is automatically changed to the server's cache format
        options.

Query hash
^^^^^^^^^^

Each query is turned into a unique hash that represents its signature. This is
used by the caching system so that if a query is requested again, the cached result
can be sent immediately. The filename of the resulting sound file is also the hash
in question. It may be useful for the client to get access to this hash, either for
internal caching on the client side, or to check directly if a file exists.

Stack definition
^^^^^^^^^^^^^^^^

A stack is a list of module definitions. The **module** key contains the name of
the module. Each module is ran one after another. Note that the output of each each
module is also cached, even when the module doesn't do much (like adding silence).
We could make (intermediate) caching optional for future versions, but this is not
implemented at the moment.

Each module has its own parameters. See :ref:`available-modules` for more details.

Sub-queries
^^^^^^^^^^^

In the main query, or if a module has a **file** parameter
(for instance the :func:`mixin<vt_server_modules.process_mixin>` module),
another query can be used in place of a file name. **mixin** adds two sound files
on top of each other. If you want to process them both before mixing, you can use a
sub-query.

Examples
========

First example
-------------

A basic example adding a ramp to the sound file, and then padding silence before
and after. This is the full code, assuming we have a file :file:`Beer.wav` in
:file:`/home/toto/audio/`, and assuming the :func:`send` function described above has been
defined.

.. code-block:: python

    q = {
        'action': "process",
        'file':   "/home/toto/audio/Beer.wav",
        'stack': list()
    }

    q['stack'].append({
        'module':   "ramp",
        'duration': 50e-3,
        'shape':    "cosine"
    })

    q['stack'].append({
        'module': "pad",
        'before': 500e-3,
        'after':  500e-3
    })

    r = send(q)

The server will receive the following JSON query:

.. code-block:: json

    {
        "action": "process",
        "file": "/home/toto/audio/Beer.wav",
        "stack": [
            {
                "module": "ramp",
                "duration": 0.05,
                "shape": "cosine"
            },
            {
                "module": "pad",
                "before": 0.5,
                "after": 0.5
            }
        ]
    }

The server replies:

.. code-block:: json

    {
        "out": "ok",
        "details": "./cache/49a6947de5b3b8d113d491770977a743.flac"
    }

**details** contains the path to the result file. Because the default cache format is
`FLAC`, we get a .flac file. Note that the hash you would obtain for the same file will
be different because your file path will be different.


Output format
-------------

We can specify the output format using the **format** keyword. We can add it to the previous
query:

.. code-block:: python

    q['format'] = "mp3"

    r = send(q)

This time we get:

.. code-block:: json

    {
        "out": "ok",
        "details": "./cache/49a6947de5b3b8d113d491770977a743.mp3"
    }

The default compression for mp3 is 192 kbps. To change it, specify ``q['format_options'] = {'bitrate': 320}``.
Note that LAME may not support all combinations of bitrates and sampling frequencies.


Sub-query
---------

This example shows how to use sub-queries. Here we'll create a sound file that
has the word "beer" (that's bear in Dutch, by the way, not a beer to drink), starting
right away, and 1 s later, the same word, where the F0 has been shifted up 12 semitones,
and the VTL has been shifter -5 semitones, and attenuated by 6 dB:

.. code-block:: python

    q = {
        'action': "process",
        'file':   "Beer.wav",
        'stack': list()
    }

    q['stack'].append({
        'module': "mixin",
        'file': {
            'action': "process",
            'file': 'Beer.wav',
            'stack': [
                {
                    'module': "world",
                    'f0': "+12st",
                    'vtl': "-5st"
                }
            ]
        },
        'levels': [0, -6],
        'pad': [0, 0, 1, 0],
        'align': "left"
    })

This produces the following JSON query:

.. code-block:: json

    {
        "action": "process",
        "file": "Beer.wav",
        "stack": [
            {
                "module": "mixin",
                "file": {
                    "action": "process",
                    "file": "Beer.wav",
                    "stack": [
                        {
                            "module": "world",
                            "f0": "+12st",
                            "vtl": "-5st"
                        }
                    ]
                },
                "levels": [0, -6],
                "pad": [0, 0, 1, 0],
                "align": "left"
            }
        ]
    }

Similarly, subqueries can be used as the main input, even with an empty stack:

.. code-block:: json

    {
        "action": "process",
        "file": [
            {
                "file": "Beer.wav",
                "stack": [
                    {
                        "module": "world",
                        "f0": "+12st"
                    }
                ]
            },
            {
                "file": "Beer.wav",
                "stack": [
                    {
                        "module": "world",
                        "f0": "-12st"
                    }
                ]
            }
        ]
        "stack": []
    }

The example above will produce the word "Beer" shifted up 1-octave, followed by the same word
shifted down 1-octave.

Using `async`
-------------

When reaching to the server through the internet (more on this below), you probably
don't want to wait for the VT Server to be done. The main reason is that the connection
may be interrupted, or you may want to display a loader to the user, and check periodically
if the processing is ready.

To do that, we run the query in `async` mode. In this mode, the server will not reply
`"ok"`, but instead will reply `"wait"`. If you send the same query again later, the
server will reply `"wait"` until the processing of the query is completed, at which
point it will reply `"ok"` and give the link to the processed sound file.

On https://dbsplab.fun, this is implemented in Javascript this way:

.. code-block:: javascript

    /*
        Tools to send a vt query and wait for the file to be ready.
        Requires jQuery.
    */

    function buf2hex(buffer) { // buffer is an ArrayBuffer
        return Array.prototype.map.call(new Uint8Array(buffer), x => ('00' + x.toString(16)).slice(-2)).join('');
    }

    async function vt_hash(q, prefix='H') {
        var crypto_ = window.crypto || window.msCrypto; // for IE 11
        // Watchout, this is not the same hash as used by the vt-server, this is just for internal use.
        // Also watchout, in some Chrome version, this only works over HTTPS.
        return prefix+buf2hex(crypto_.subtle.digest('SHA-1', JSON.stringify(q)));
    }

    function createArray(len, itm) {
        var arr = [];
        while(len > 0) {
            arr.push(itm);
            len--;
        }
        return arr;
    }

    function vt(q, success_cb, error_cb) {
        // q
        //     Is the query as a javascript object
        // success_cb(url)
        //     A callback that will receive a string that is the URL
        //     of the processed sound file
        // error_cb(msg)
        //     Receives a string with details about the error

        // We keep a list of queries to make sure they're not taking for ever...
        if(typeof vt.qt==='undefined')
            vt.qt = {};
        var h = vt_hash(q);
        if(!(h in vt.qt))
            vt.qt[h] = Date.now()
        else if(Date.now-vt.qt[h]>20000) {
            error_cb("It is taking way too long for the server to respond... maybe it's offline?");
            return false;
        }

        $.post({
            url: '/ajax/vt.php',
            data: q,
            timeout: 5000,
            success: function(data) {
                try{
                    data = JSON.parse(data);
                } catch(err) {
                    error_cb("Couldn't understand the response of the server...: "+data);
                    return false;
                }

                if(data['success']) {
                    if(data['message']=='wait') {
                        setTimeout(function(){ vt(q, success_cb, error_cb); }, 1000);
                        return false;
                    } else {
                        delete vt.qt[h];
                        return success_cb(data['message']);
                    }
                } else {
                    return error_cb(data['message']);
                }
            },
            error: function(jqXHR, textStatus, errorThrown){
                if(textStatus=='timeout') {
                    setTimeout(function(){ vt(q, success_cb, error_cb); }, 1000);
                    return false;
                } else if(jqXHR.status == 403) {
                    // Looks like we didn't get permission...
                    error_cb("It seems you do not have permission to run this query.");
                }
                else
                    error_cb("An error occured while processing the sounds: "+errorThrown);
            }
        });
    }

    function vt_multi(qs, success_cb, error_cb) {
        // Same as `vt` but qs is an array of queries. The success callback is called
        // when all queries are completed and it receives an array of results.

        if(typeof vt_multi.qs==='undefined')
            vt_multi.qs = {};

        var h = vt_hash(qs, 'M');

        vt_multi.qs[h] = createArray(qs.length, null);

        qs.forEach(function(q, i){
            vt(
                q,
                function(msg){
                    vt_multi.qs[h][i] = msg;
                    for(var m of vt_multi.qs[h])
                    {
                        if(m===null)
                            return false;
                    }
                    success_cb(vt_multi.qs[h]);
                    delete vt_multi.qs[h];
                },
                error_cb
            )
        });

    }

Note that these Javascript functions do not interface directly with the server,
instead they interface with :file:`/ajax/vt.php`, which is a wrapper for the PHP client.
It is checking that the query is authorized before sending it to the VT Server.
