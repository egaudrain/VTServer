#!/usr/bin/env python3
# coding: utf-8

"""
vt_server
=========

This is a Voice Transformation server. It receives command stacks as JSON arrays
to process sound files that are local on the server, and returns a pointer to the processed file.

.. Created on 2020-03-20.
"""

import socketserver
import json
import os, traceback
import vt_server_logging as vsl
from vt_server_modules import discover_modules
import vt_server_brain
# optional
import threading


__version__ = "2.3"
__author__  = "Etienne Gaudrain"


class VTHandler(socketserver.StreamRequestHandler):
    """
    The handler for the server requests.

    Requests are JSON encoded. It is required that they contain the following field
    `action` which can receive one of two values: `"status"` or `"process"`.

    If **action** is  `"status"`, then no other field is required.

    If **action** is  `"process"`, then the following fields are required:

        file
          The sound file(s) that will be processed. This can also be an array
          of files or of queries. The stack is applied to the concatenated result.
          The file path is relative to where the *server* is running from (not the client).
          *It is highly recommended to use absolute paths instead of relative paths.*
          Also note that the input sound files should be in a format understood by
          `linsndfile <http://www.mega-nerd.com/libsndfile/#Features>`__.

          Note: In version 2.2 it was possible to use " >> " to separate files. This
          has been removed in 2.3. Support for subqueries as `file` has been added in 2.3.

        stack
          The list of processes that will be run on the file. Each item
          in the stack is an object that is specific to the type of processing.
          Each object must have a `module` attribute that is used to dispatch the
          processing. This can also be a list of stacks that apply to everyone of
          the files if **file** is an array (otherwise, the same stack is applied
          to all files before concatenation).

    The following fields are optional:

        mode
          `"sync"` [default], `"async"` or `"hash"`. In `sync` mode, the server will only
          send a response when the file is processed. In `async` mode, the server
          will respond immediately with a `"wait"` response. The client can probe
          periodically with the same request until the file is returned. `hash` only
          returns the hash of the request that is used as identifier.

        format
          Specifies the output format of the sound files. Can be `"flac"`, `"wav"`
          (or anything else supported by `libsndfile <http://www.mega-nerd.com/libsndfile/>`_, or `"mp3"`
          (if `LAME <http://www.mega-nerd.com/libsndfile/>`_ is installed). If none is provided,
          then the default cache format is used (see :mod:`vt_server_config`).

        format_options
          Specifies options (as a dictionary) for the selected
          format. At the moment, only `bitrate` is specified (as an integer in kbps)
          for format `"mp3"` (see :py:func:`vt_server_brain.encode_to_format` for details).

        cache
          This defines when the cache will expire. Cache files are deleted either when one of
          the source files is missing, or when the cache expires. The cache expiration date is
          updated everytime the file is requested. If `True` or `None` (`null` in JSON), no expiration is set for the cache file.
          If `False`, the cache is set to expire after 1h. Otherwise a duration before expiration can
          be provided in hours. Keep in mind that the generated sound file has to exist long
          enough for it to be downloaded by the client. Note that sub-queries do not inherit
          cache status from their parents. If not provided, the cache value is 730, which
          corresponds roughly to 1 month.

    The response is also JSON and has the following form:

        out
          `"ok"`, `"error"`, or `"wait"`

        details
          In case of success, this contains the outcome of the processing. In case of error,
          this has some details about the error.
    """
    def handle(self):
        """
        The handler function. It basically receives the query in JSON, tries to parse it and then
        dispatch to :py:func:`vt_server_brain.process` if it worked. Then sends the response back
        to the client.
        """
        self.data = self.rfile.readline().strip()
        vsl.LOG.debug("Received from {}: {}.".format(self.client_address[0], self.data))
        msg = dict()
        try:
            req = json.loads(self.data.decode('utf-8'))
            if req['action']=='status':
                msg['out'] = 'ok'
                msg['details'] = 'We have processed %d requests since startup and there are now %d jobs in the JOBS list.' % (vt_server_brain.N_REQUESTS, len(vt_server_brain.JOBS))
                vsl.LOG.debug("This is the status: {}.".format(msg['details']))
            elif req['action']=='process':
                msg = vt_server_brain.process(req)
            else:
                vsl.LOG.debug("Got a request with wrong 'action' field.")
                msg['out'] = 'error'
                msg['details'] = "The 'action' field of your request is not correct."
        except Exception as err:
            vsl.LOG.debug("There was a problem while handling the query: {}".format(traceback.format_exc()))
            msg['out'] = 'error'
            msg['details'] = traceback.format_exc()

        msg_b = json.dumps(msg).encode('utf-8')+b"\n"
        #vsl.LOG.debug("Sending: {}".format(repr(msg_b)))
        self.wfile.write(msg_b)
        #self.wfile.close()
        #vsl.LOG.debug("Sent.")

class VTServer(socketserver.ThreadingTCPServer):

    def server_activate(self):
        super().server_activate()

        # Instanciating the janitor for periodic 400s check
        vt_server_brain.JOB_JANITOR = vt_server_brain.Janitor(400)

        vsl.LOG.info("Running VTServer version {} on {}:{}.".format(__version__, self.server_address[0], self.server_address[1]))

    def server_close(self):
        print('\nTerminating.')
        super().server_close()
        if vt_server_brain.JOB_JANITOR is not None:
            vt_server_brain.JOB_JANITOR.kill()

def main():
    """
    Imports the configuration, instantiates a :class:`VTServer` and starts
    the :class:`vt_server_brain.Janitor` before starting the server itself.

    Runs forever until the server receives SIGINT.
    """

    import vt_server_config as vsc

    config = vsc.CONFIG

    #if os.access(config['logfile'], os.W_OK):
    try:
        vsl.LOG.addHandler(vsl.get_FileHandler(config['logfile']))
    except Exception as err:
        vsl.LOG.error("The logfile '%s' couldn't be accessed. Check that there is proper permission to write there: %s" % (os.path.abspath(config['logfile']), err))

    try:
        vsl.LOG.info("Setting logging level to '%s'." % config['loglevel'])
        vsl.LOG.setLevel(config['loglevel'])
    except:
        vsl.LOG.warning("Could not set log-level to '%s'" % config['loglevel'])

    discover_modules()

    server = VTServer((config['host'], config['port']), VTHandler)

    try:
        vsl.LOG.info("At your service...")
        server.serve_forever()
    except KeyboardInterrupt:
        vsl.LOG.info("Shutting down the server...")
        server.shutdown()
    finally:
        server.server_close()
        vsl.LOG.info("Bye!")


if __name__ == "__main__":
    main()
