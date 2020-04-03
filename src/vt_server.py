#!/usr/bin/env python3
# coding: utf-8

"""
``vt_server``
=============

This is a Voice Transformation server. It receives command stacks as JSON arrays
to process sound files that are local on the server, and returns a pointer to the processed file.

.. Created on 2020-03-20.
"""

import socketserver
import json
import os
import vt_server_logging as vsl
import vt_server_brain
# optional
import threading

class VTHandler(socketserver.StreamRequestHandler):
    """
    The handler for the server requests.

    Requests are JSON encoded. It is required that they contain the following field
    `action` which can receive one of two values: `"status"` or `"process"`.

    If ``action`` is  ``"status"``, then no other field is required.

    If ``action`` is  ``"process"``, then the following fields are required:

        * ``file``: the sound file that will be processed

        * ``stack``: the list of processes that will be run on the file. Each item
          in the stack is an object that is specific to the type of processing.
          Each object must have a `module` attribute that is used to dispatch the
          processing.

    The following field is optional:

        * ``mode``: ``"sync"`` [default], ``"async"`` or ``"hash"``. In ``sync`` mode, the server will only
          send a response when the file processed. In `async` mode, the server
          will respond immediately with a `"wait"`` response. The client can probe
          periodically with the same request until the file is returned. ``"hash"`` only
          returns the hash of the request that is used as identifier.

    The response is also JSON and has the following form:

        * ``out``: ``"ok"`` or ``"error"``

        * ``details``: In case of success, this contains the outcome of the processing
          (or ``"wait"`` for the ``"async"`` mode). In case of error, this has some
          details about the error.
    """
    def handle(self):
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
            vsl.LOG.debug("This request is not valid JSON: {}".format(repr(err)))
            msg['out'] = 'error'
            msg['details'] = repr(err)

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

        vsl.LOG.info("Running VTServer on {}:{}.".format(self.server_address[0], self.server_address[1]))

    def server_close(self):
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

    if os.access(config['logfile'], os.W_OK):
        vsl.LOG.addHandler(vsl.get_FileHandler(config['logfile']))
    else:
        vsl.LOG.error("The logfile '%s' couldn't be accessed. Check that there is proper permission to write there." % config['logfile'])

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
