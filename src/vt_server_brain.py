#!/usr/bin/env python3
# coding: utf-8

"""
``vt_server_brain``
===================

Dispatches the processing to the right underlings. The brain also manages the
various processes and the main cache. Each request is dispatched to its own
process as a *job*.

Jobs have a signature that is based on the task at hand:

    * the ``file`` it applies to,

    * and the process instruction stack list.

These are serialized (using pickle) and then hashed (in md5) to create the job
signature. The job signature is also used for the name of the cache file.

Everytime a job is submitted, the brain first checks if the file already exists.
If the file exists, it is returned right away. If the file does not exist, then
we check if the job is in the `JOBS` list (a managed dictionary). If it is in
the list, then we just reply ``wait`` to the client. If not, then the brain
creates the job and starts the process.

In ``sync`` mode, the dispatcher waits for the process to be completed.

In ``async`` mode it returns right away and sends a ``wait`` message. The client can
send the same request a bit later. If the job is still being processed, the server
sends the same ``wait`` response. If the job is completed, then the job target file
exists and is returned right away.

Individual tasks listed in the task list can have their own cache system, but
they need to manage it themselves.

A ``job_janitor`` is scouring the ``JOBS`` list to check on jobs that may be finished,
and remove them from the list.

.. Created on 2020-03-20.
"""

import vt_server_config as vsc
import vt_server_logging as vsl
import vt_server_common_tools as vsct
import vt_server_modules as vsm

import os, datetime
from multiprocessing import Process, Manager, active_children
from threading import Event, Thread

import soundfile as sf

manager = Manager()
JOBS = manager.dict()
N_REQUESTS = 0 # This is just for information purposes.

class Janitor():
    """
    The janitor periodically checks the job list to see if there are any finished jobs, and then gets rid of them.
    """

    def __init__(self, interval):
        self.interval = interval
        self.cancel_future_calls = None
        self.call_repeatedly(self.interval)

    def call_repeatedly(self, interval):
        stopped = Event()

        def loop():
            while not stopped.wait(interval): # the first call is in `interval` secs
                self.janitor_job()

        vsl.LOG.debug("Starting a janitor...")
        self.thread = Thread(target=loop).start()

        self.cancel_future_calls = stopped.set

    def kill(self):
        vsl.LOG.debug("Let's terminate this janitor...")

        if self.cancel_future_calls is not None:
            self.cancel_future_calls()
        if self.thread is not None and self.thread.is_alive():
            try:
                vsc.LOG.info("Janitor: Thread #%d is not finished. We'll wait %.1f s for it to finish... and then destroy it!" % (self.thread.ident, self.interval))
                self.thread.join(self.interval)
                del self.thread
            except Exception as err:
                vsc.LOG.info("Janitor: Something went wrong while shutting down Thread #%d: %s" % (self.thread.ident, repr(err)))

    @staticmethod
    def janitor_job():
        """
        The jobs_janitor function checks periodically on the `JOBS` list to see if there are any
        process that is finished and needs removing.
        """


        Ps = dict()
        for p in active_children():
            Ps[p.pid] = p

        vsl.LOG.debug("Janitor: Hi! this is the janitor, I will inspect %d jobs and %d process(es)." % (len(JOBS), len(Ps)))

        for k in list(JOBS.keys()):
            if JOBS[k]['finished']:
                del JOBS[k]
            else:
                if JOBS[k]['pid'] not in Ps:
                    vsl.LOG.info("Janitor: Job %s terminated without setting its `finished` status to True and is being deleted." % k)
                    del JOBS[k]

# Instanciating the janitor for periodic 30s check
#JOB_JANITOR = Janitor(30)
JOB_JANITOR = None # now instantiated manually

def job_signature(req):
    return vsct.signature((os.path.abspath(req['file']), req['stack']))

def process(req):
    global N_REQUESTS
    N_REQUESTS += 1

    if 'mode' not in req:
        req['mode'] = 'sync'

    if 'file' not in req:
        return {'out': 'error', 'details':  "The 'file' field is missing"}

    req['file'] = os.path.abspath(req['file'])

    if not os.access(req['file'], os.R_OK):
        vsl.LOG.debug("File '%s' was requested but cannot be accessed." % req['file'])
        return {'out': 'error', 'details': "File '%s' cannot be accessed" % req['file']}

    if 'stack' not in req:
        req['stack'] = list()

    #----------------------------
    # From here on, we are ready to call job_signature

    h = job_signature(req)

    if req['mode'] == 'hash':
        return {'out': 'ok', 'details': h}

    out_filename = os.path.join(vsc.CONFIG['cachefolder'], h+"."+vsc.CONFIG['cacheformat'])

    if os.access(out_filename, os.R_OK):
        # The file already exists and is accessible, we return it
        return {"out": "ok", "details": out_filename}
    else:
        if h in JOBS:
            # The job is already being processed
            return {"out": "wait", "details": "Job started at %s" % JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S")}
        else:
            vsl.LOG.debug("Adding job %s to the job list." % h)
            p = Process(target=process_async, args=(req, h, out_filename))
            p.start()
            JOBS[h] = {'finished': False, 'started_at': datetime.datetime.now(), 'pid': p.pid}

            vsl.LOG.debug("Job %s is running in process %d." % (h, p.pid))

            if req['mode']=='async':
                return {"out": "wait", "details": "Job started at %s" % JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S")}
            elif req['mode']=='sync':
                p.join()
                j = JOBS[h]
                if 'out' in j:
                    output = {"out": j['out'], "details": j['details']}
                    JOBS.pop(h)
                    return output
                else:
                    return {'out': 'error', 'details': "Not sure what happened here... JOB=%s" % repr(j)}


    return {'out': 'error', 'details': "Huuuu... we shouldn't find ourselves here... %s" % repr(req)}

def process_async(req, h, out_filename):

    vsl.LOG.debug("[%s] Processing request %s." % (h, repr(req)))

    f = req['file']

    j = JOBS[h]

    for i, m in enumerate(req['stack']):

        if 'module' not in m:
            err_msg = "Item %d of the stack does not have a 'module' defined: %s" % (i, repr(m))
            j['out'] = 'error'
            j['details'] = err_msg
            j['finished'] = True
            JOBS[h] = j
            vsl.LOG.critical(err_msg)
            return

        vsl.LOG.debug("[%s] Doing module '%s'" % (h, m['module']))
        if m['module'] in vsm.PATCH:
            try:
                # Do we have this already in cache?
                hm = vsct.signature((os.path.abspath(f), m))
                module_cache_path = os.path.join(vsc.CONFIG['cachefolder'], m['module'])
                cache_filename = os.path.join(module_cache_path, hm+"."+vsc.CONFIG['cacheformat'])

                if not os.path.exists(module_cache_path):
                    os.makedirs(module_cache_path)

                if os.access(cache_filename, os.R_OK):
                    f = cache_filename
                else:
                    f = vsm.PATCH[m['module']](f, m, cache_filename)
                    vsl.LOG.debug("[%s] Done with module '%s'" % (h, m['module']))

            except Exception as err:
                err_msg = "Something went wrong while running module '%s' on file '%s': %s" % (m['module'], f, repr(err))
                j['out'] = 'error'
                j['details'] = err_msg
                j['finished'] = True
                JOBS[h] = j
                vsl.LOG.critical(err_msg)
                return
        else:
            err_msg = "Calling unknown module '%' while processing '%s'." % (m['module'], f)
            j['out'] = 'error'
            j['details'] = err_msg
            j['finished'] = True
            JOBS[h] = j
            vsl.LOG.critical(err_msg)
            return

    if os.path.splitext(f)[1] == os.path.splitext(out_filename)[1]:
        os.symlink(f, out_filename)
    else:
        x, fs = sf.read(f)
        sf.write(out_filename, x, fs)

    j['out'] = 'ok'
    j['details'] = out_filename
    j['finished'] = True
    JOBS[h] = j

    vsl.LOG.debug("[%s] Finished with processing the stack." % (h))


if __name__=="__main__":

    vsc.CONFIG['cachefolder'] = 'test/cache'
    vsc.CONFIG['logfile'] = 'test/vt_server.log'

    if not os.path.exists(vsc.CONFIG['cachefolder']):
        os.makedirs(vsc.CONFIG['cachefolder'])

    vsl.LOG.addHandler(vsl.get_FileHandler(vsc.CONFIG['logfile']))

    # Instanciating the janitor for periodic 30s check
    JOB_JANITOR = Janitor(30)

    # Testing some stuff
    r1 = {'file': "test/Man480.wav", 'stack': [{'module': 'P1', 'params': [1, 123.321321, 65461, 12.0]}, {'module': 'P2'}], 'mode': 'hash'}


    print(process(r1))

    JOB_JANITOR.kill()

    #print(job_signature(r3))
