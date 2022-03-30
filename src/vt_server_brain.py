#!/usr/bin/env python3
# coding: utf-8

"""
vt_server_brain
===============

Dispatches the processing to the right underlings. The brain also manages the
various processes and the main cache. Each request is dispatched to its own
process as a **job**.

Jobs have a signature that is based on the task at hand:

    * the **file** it applies to,

    * and the process instruction stack list.

These are serialized (using pickle) and then hashed (in md5) to create the job
signature. The job signature is also used for the name of the cache file.

Everytime a job is submitted, the brain first checks if the file already exists.
If the file exists, it is returned right away. If the file does not exist, then
we check if the job is in the :py:data:`JOBS` list (a managed dictionary). If it is in
the list, then we just reply `'wait'` to the client. If not, then the brain
creates the job and starts the process.

In `'sync'` mode, the dispatcher waits for the process to be completed.

In `'async'` mode (default) it returns right away and sends a `'wait'` message. The client can
send the same request a bit later. If the job is still being processed, the server
sends the same `'wait'` response. If the job is completed, then the job target file
exists and is returned right away.

Individual tasks listed in the task list can have their own cache system, but
they need to manage it themselves.

A :py:class:`Janitor` is scouring the :py:data:`JOBS` list to check on jobs that may be finished,
and remove them from the list.

.. Created on 2020-03-20.
"""

import vt_server_config as vsc
import vt_server_logging as vsl
import vt_server_common_tools as vsct
import vt_server_modules as vsm

import os, datetime, pickle, copy, traceback
from multiprocessing import Process, Manager, active_children
from threading import Event, Thread
import subprocess
from enum import IntEnum

import soundfile as sf
import numpy as np

manager = Manager()
#: This is the list of current jobs (actually a managed dict).
JOBS = manager.dict()
N_REQUESTS = 0 # This is just for information purposes.

SUPPORTED_SOUND_EXTENSIONS = [x.lower() for x in sf.available_formats().keys()]

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
        Checks periodically on the :py:data:`JOBS` list to see if there are any
        process that is finished and needs removing.
        """

        Ps = dict()
        for p in active_children():
            Ps[p.pid] = p

        vsl.LOG.debug("Janitor: Hi! this is the janitor, I will inspect %d jobs and %d process(es)." % (len(JOBS), len(Ps)))

        live_processes = 0
        removed_processes = 0

        for k in list(JOBS.keys()):
            if JOBS[k]['started_at'] + datetime.timedelta(minutes=10) > datetime.datetime.now():
                # Job is less than 10 min old, we skip
                live_processes += 1
                continue
            elif JOBS[k]['finished']:
                del JOBS[k]
                removed_processes += 1
            elif (JOBS[k]['pid'] is not None) and (JOBS[k]['pid'] not in Ps):
                # None is for queries with sub-queries before the main stack is processed
                vsl.LOG.info("Janitor: Job %s terminated without setting its `finished` status to True and is being deleted." % k)
                del JOBS[k]
                removed_processes += 1
            else:
                live_processes += 1

        vsl.LOG.debug("Janitor: I found %d live or valid processes and removed %d from the list." % (live_processes, removed_processes))

# Instanciating the janitor for periodic 30s check
#JOB_JANITOR = Janitor(30)
JOB_JANITOR = None # now instantiated manually

def job_signature(req):

    if isinstance(req, dict):
        if 'stack' not in req:
            req['stack'] = list()

        if isinstance(req['file'], list):
            return 'M'+vsct.signature(([job_signature(x) for x in req['file']], req['stack']))
        elif isinstance(req['file'], dict):
            return 'S'+vsct.signature((job_signature(req['file']), req['stack']))
        else:
            return vsct.signature((os.path.abspath(req['file']), req['stack']))
    else:
        # req is a filename
        return vsct.signature((os.path.abspath(req), []))

# def _job_signature_multi(files, stack):
#     signs = list()
#     for x in files:
#         if isinstance(x, dict):
#             signs.append(job_signature(x))
#         else:
#             signs.append(os.path.abspath(x))
#     return 'M'+vsct.signature((" >> ".join(signs), stack))

class QueryInType(IntEnum):
    FILE = 0
    QUERY = 1
    GENERATOR = 2
    LIST = 3

def process(req, force_sync=False):
    """
    Creates jobs (populating the :py:data:`JOBS` list), checks on cache and dispatches processing threads.

    :param req: The query received by the server.
    :type req: dict
    """

    global N_REQUESTS
    N_REQUESTS += 1

    if 'mode' not in req:
        req['mode'] = 'async'
    if req['mode'] not in ['sync', 'async', 'hash']:
        return {'out': 'error', 'details': "'mode' has to be 'sync' or 'async' ('%s' provided)" % (req['mode'])}

    if 'file' not in req:
        return {'out': 'error', 'details':  "The 'file' field is missing"}

    if 'stack' not in req:
        req['stack'] = list()

    if 'format' not in req:
        req['format'] = vsc.CONFIG['cacheformat']

    if 'format_options' not in req:
        req['format_options'] = vsc.CONFIG['cacheformatoptions']

    if 'cache' not in req:
        req['cache'] = 730

    if req['cache'] is False:
        req['cache'] = (datetime.datetime.now() + datetime.timedelta(hours=1), 1)
    elif isinstance(req['cache'], (int, float)) and req['cache']>=0:
        req['cache'] = (datetime.datetime.now() + datetime.timedelta(hours=req['cache']), req['cache'])
    elif isinstance(req['cache'], tuple) and isinstance(req['cache'][1], (int, float)):
        req['cache'] = (datetime.datetime.now() + datetime.timedelta(hours=req['cache'][1]), req['cache'][1])
    else:
        return {'out': 'error', 'details':  "The 'cache' field could not be interpreted: %s." % repr(req['cache'])}

    if isinstance(req['file'], list): # or (' >> ' in req['file']):
        req['in_type'] = QueryInType.LIST
    elif isinstance(req['file'], dict):
        req['in_type'] = QueryInType.QUERY
    else:
        if req['file'].startswith('@') and req['file'].endswith(')'):
            req['in_type'] = QueryInType.GENERATOR
            return {'out': 'error', 'details': "Generators are not supported yet (%s)." % req['file']}
        else:
            req['in_type'] = QueryInType.FILE

    # TODO: Handle generators for file
    if req['in_type'] == QueryInType.FILE:
        if req['file'].endswith(os.path.sep):
            req['file'] = os.path.abspath(req['file']) + os.path.sep
        else:
            req['file'] = os.path.abspath(req['file'])

        if not os.access(req['file'], os.R_OK):
            vsl.LOG.debug("File '%s' was requested but cannot be accessed." % req['file'])
            return {'out': 'error', 'details': "File '%s' cannot be accessed" % req['file']}

        if (not os.path.isdir(req['file'])) and (os.path.splitext(req['file'])[1].strip('.').lower() not in SUPPORTED_SOUND_EXTENSIONS):
            vsl.LOG.debug("Sound format not supported for '%s'." % (req['file']))
            return {'out': 'error', 'details': "Format of '%s' is not supported." % req['file']}

    #----------------------------
    # From here on, we are ready to call job_signature

    h = job_signature(req)

    vsl.LOG.info("[%s] Processing request: %s" % (h, req))

    if req['mode'] == 'hash':
        return {'out': 'ok', 'details': h}

    out_path = os.path.join(os.path.abspath(vsc.CONFIG['cachefolder']), h[0])
    out_filename = os.path.join(out_path, h+"."+req['format'])

    vsl.LOG.debug("[%s] Checking if job exists or if cache file `%s` is accessible" % (h, out_filename))

    # First we check if we have this job in the job-list
    if h in JOBS:
        # The job is already being processed
        if JOBS[h]['finished']:
            if JOBS[h]['out']!='ok':
                return {"out": JOBS[h]['out'], "details": JOBS[h]['details']}
            elif os.access(out_filename, os.R_OK):
                # Job is marked finished and ok, but cache couldn't be accessed, we need to regenerate it
                vsl.LOG.debug("[%s] Found %s in cache. Done." % (h, out_filename))
                try:
                    vsct.update_job_file(out_filename)
                except:
                    vsl.LOG.warning("[%s] Something went wrong while updating the job-file associated with %s" % (h,out_filename))
                return {"out": "ok", "details": out_filename}
            else:
                vsl.LOG.info("[%s] Found job in JOBS, started at %s, marked finished and ok, but cache (%s) couldn't be accessed, we need to regenerate it" % (h, JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S"), out_filename))
                JOBS.pop(h)
        else:
            vsl.LOG.debug('[%s] Found job in JOBS, started at %s, not finished yet' % (h ,JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S")));
            return {"out": "wait", "details": "Job started at %s" % JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S")}

    # If the job was finished, it could be that it's been removed from the job list already, we then check if the file was created already
    elif os.access(out_filename, os.R_OK):
        # The file already exists and is accessible, we return it
        vsl.LOG.debug("[%s] Found %s in cache. Done." % (h, out_filename))
        try:
            vsct.update_job_file(out_filename)
        except:
            vsl.LOG.warning("[%s] Something went wrong while updating the job-file associated with %s" % (h,out_filename))
        return {"out": "ok", "details": out_filename}


    if not os.path.exists(out_path):
        os.makedirs(out_path)

    vsl.LOG.debug("[%s] Adding job to the JOBS list." % h)

    JOBS[h] = {'finished': False, 'started_at': datetime.datetime.now(), 'pid': None}

    # if req['in_type'] == QueryInType.QUERY:
    #     vsl.LOG.debug("[%s] Starting sub-query process." % (h))
    #     p = Process(target=subquery_process_async, args=(req, h, out_filename))
    # else:
    if req['in_type'] == QueryInType.LIST:
        proc_target = multi_process_async
    else:
        proc_target = process_async

    p = Process(target=proc_target, args=(req, h, out_filename))

    p.start()

    j = JOBS[h]
    j['pid'] = p.pid
    JOBS[h] = j

    vsl.LOG.debug("[%s] Job is running in process %d." % (h, p.pid))

    if req['mode']=='async' and not force_sync:
        return {"out": "wait", "details": "Job started at %s" % JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S")}
    elif req['mode']=='sync' or force_sync:
        p.join()
        j = JOBS[h]
        if 'out' in j:
            output = {"out": j['out'], "details": j['details']}
            JOBS.pop(h)
            return output
        else:
            return {'out': 'error', 'details': "Not sure what happened here... JOB=%s" % repr(j)}

def cast_outfile(f, out_filename, req, h):

    vsl.LOG.debug("[%s] Casting `%s` into `%s`" % (h, f, out_filename))

    if os.path.splitext(f)[1] == os.path.splitext(out_filename)[1]:
        os.symlink(f, out_filename)
        vsct.job_file(out_filename, [f], req['cache'], req['stack'])
    else:
        if req['format'] == 'mp3':
            try:
                encode_to_format(f, out_filename, req['format'], req['format_options'])
                vsct.job_file(out_filename, [f], req['cache'], req['stack'])
            except Exception as err:
                err_msg = "Encoding of '%s' to format '%s' failed with error: %s, %s" % (f, req['format'], err, err.output.decode('utf-8'))
                j = JOB[h]
                j['out'] = 'error'
                j['details'] = err_msg
                j['finished'] = True
                JOBS[h] = j
                vsl.LOG.critical(err_msg)
                return False
        else:
            x, fs = sf.read(f)
            sf.write(out_filename, x, fs)
            vsct.job_file(out_filename, [f], req['cache'], req['stack'])

    vsl.LOG.debug("[%s] Casting `%s` into `%s` was successful." % (h, f, out_filename))

    return True

def process_async(req, h, out_filename):
    """
    This is the function that is threaded to run the core of the module. It dispatches
    calls to the appropriate modules, and deals with their cache.

    It also updates the :py:data:`JOB` list when a job is finished, and create a job file
    with some information about the job (useful for cache cleaning).

    If a module takes a `'file'` as argument, the file can be a query. It will be executed in sync mode from the
    current :py:func:`process_async` process.

    Job files are pickled `dict` objects that contain the following fields:

        original_file `[string]`
            The original sound file that the job was based on.

        created_files `[list]`
            The list of files that were created in the process. This includes the final
            sound file, but also intermediate files that may have been necessary to the
            process.

        used_files `[list]`
            If an intermediate file was used, but not created by the current job, it is listed here.

        stack `[dict]`
            The stack that defines the job.

        cache_expiration `[tuple(datetime, float)]` `optional`
            If `None` or missing, the cache does not expire by itself. Otherwise, the field contains
            a date after which the `created_files` can be removed, and a time-delta in hours. Everytime the
            file is accessed, the cache expiration is updated with the time-delta.

    """

    vsl.LOG.debug("[%s] Processing request %s." % (h, repr(req)))

    j = JOBS[h]

    # TODO: handle generators for file
    if req['in_type'] == QueryInType.FILE:
        f = req['file']
    elif req['in_type'] == QueryInType.QUERY:
        r = req['file']
        r['format'] = vsc.CONFIG['cacheformat']
        r['format_options'] = vsc.CONFIG['cacheformatoptions']
        o = process(r, force_sync=True)
        if o['out']=='error':
            j = JOBS[h]
            j['out'] = 'error'
            j['details'] = o['details']
            j['finished'] = True
            JOBS[h] = j
            vsl.LOG.debug("[%s] There was an error while processing the subquery: %s" % (h, j['details']))
            return
        else:
            f = o['details']
    elif req['in_type'] == QueryInType.GENERATOR:
        j = JOBS[h]
        j['out'] = 'error'
        j['details'] = "Generators are not supported yet (%s)." % req['file']
        j['finished'] = True
        JOBS[h] = j
        vsl.LOG.debug("[%s] %s" % (h, j['details']))
        return


    # job_info = dict()
    # job_info['source_files'] = [f] # If source file does not exist anymore, the job is deleted
    # job_info['support_files'] = list() # Additional files that need deleting if source file is missing, but not if there is simple cache expiration
    # job_info['stack'] = req['stack']
    # job_info['cache_expiration'] = req['cache']
    # job_filename = os.path.splitext(out_filename)[0]+".job"

    vsl.LOG.debug("[%s] Going through modules of '%s'" % (h, repr(req['stack'])))

    for i, m in enumerate(req['stack']):

        if 'module' not in m:
            err_msg = "Item %d of the stack does not have a 'module' defined: %s" % (i, repr(m))
            j = JOBS[h]
            j['out'] = 'error'
            j['details'] = err_msg
            j['finished'] = True
            JOBS[h] = j
            vsl.LOG.critical(err_msg)
            return

        vsl.LOG.debug("[%s] Doing module '%s'" % (h, m['module']))
        if m['module'] in vsm.MODULES:
            try:
                f = process_module(f, m, req['format'], req['cache'])
                vsl.LOG.debug("[%s] Done with module '%s'" % (h, m['module']))

            except Exception as err:
                #err_msg = "Something went wrong while running module '%s' on file '%s': %s" % (m['module'], f, repr(err))
                err_msg = "Something went wrong while running module '%s' on file '%s': %s" % (m['module'], f, traceback.format_exc())
                j = JOBS[h]
                j['out'] = 'error'
                j['details'] = err_msg
                j['finished'] = True
                JOBS[h] = j
                vsl.LOG.critical(err_msg)
                return
        else:
            err_msg = "Calling unknown module '%s' while processing '%s'." % (m['module'], f)
            j = JOBS[h]
            j['out'] = 'error'
            j['details'] = err_msg
            j['finished'] = True
            JOBS[h] = j
            vsl.LOG.critical(err_msg)
            return

    if cast_outfile(f, out_filename, req, h):
        j = JOBS[h]
        j['out'] = 'ok'
        j['details'] = out_filename
        j['finished'] = True
        JOBS[h] = j

        vsl.LOG.debug("[%s] Finished with processing the stack." % (h))
    else:
        vsl.LOG.debug("[%s] Could not cast the file." % (h))

# def subquery_process_async(req, h, out_filename):
#
#
#     j = JOBS[h]
#
#     o = process(req['file'], force_sync=True)
#
#     if o['out']=='error':
#         j['out'] = 'error'
#         j['details'] = o['details']
#         j['finished'] = True
#         JOBS[h] = j
#         vsl.LOG.debug("[%s] There was an error while processing the subquery: %s" % (h, j['details']))
#         return
#
#     # elif o['out']=='wait':
#     #     j['out'] = 'wait'
#     #     j['details'] = o['details']
#     #     JOBS[h] = j
#     #     vsl.LOG.debug("[%s] Subquery is not done yet" % (h))
#
#     elif o['out']=='ok':
#         vsl.LOG.debug("[%s] Subquery is done" % (h))
#         req['file'] = o['details']
#
#         o = process(req, force_sync=True)
#
#     if o['out']!='ok':
#         j = JOBS[h]
#         j['out'] = 'error'
#         j['details'] = o['details']
#         j['finished'] = True
#         JOBS[h] = j
#         vsl.LOG.debug("[%s] There was an error while processing the main query: %s" % (h, j['details']))
#         return
#
#     vsl.LOG.debug("[%s] Main query is completed in `%s`" % (h, o['details']))
#
#     if cast_outfile(o['details'], out_filename, req, h):
#         j = JOBS[h]
#         j['out'] = 'ok'
#         j['details'] = o['details']
#         j['finished'] = True
#         JOBS[h] = j

# def multi_process(req, force_sync=False):
#     """
#     This is called from :py:func:`process` if multiple files have been provided as input.
#     """
#
#     if isinstance(req['file'], list):
#         files = req['file']
#     # else:
#     #     files = req['file'].split(' >> ')
#     #     # TODO: if files are separated with "<" they are concatenated prior to being passed in the stack
#     #     # Note that as much as possible, this is not desirable for caching reasons, but that could be useful.
#
#     # if len(req['stack'])!=0:
#     #     if type(req['stack'][0])==type({}):
#     #         # We are dealing with a single stack applied to all elements: we duplicate it
#     #         req['stack'] = [req['stack']]
#     #     if len(req['stack'])==1 and len(files)>1:
#     #         # We are dealing with a list of stacks, but of length 1
#     #         req['stack'] = [ copy.deepcopy(req['stack'][0]) for f in files ]
#     #     if len(req['stack'])!=len(files):
#     #         return {'out': 'error', 'details': 'If a stack list is used, it must be of length 1 or of length equal to the number of files.'}
#     # else:
#     #     req['stack'] = [[]]*len(files)
#     #
#
#     h = job_signature(files, req['stack'])
#
#     vsl.LOG.info("[%s] Multi-file processing request: %s" % (h, req))
#
#     if req['mode'] == 'hash':
#         return {'out': 'ok', 'details': h}
#
#     out_filename = os.path.join(vsc.CONFIG['cachefolder'], h+"."+req['format'])
#
#     if os.access(out_filename, os.R_OK):
#         # The file already exists and is accessible, we return it
#         vsl.LOG.debug("[%s] Found %s in cache. Done." % (h, out_filename))
#
#         try:
#             vsct.update_job_file(out_filename)
#         except:
#             vsl.LOG.warning("Something went wrong while updating the job-file associated with %s" % out_filename)
#
#         return {"out": "ok", "details": out_filename}
#
#     elif h in JOBS:
#         if JOBS[h]['finished']:
#             if JOBS[h]['out']!='ok':
#                 return {"out": JOBS[h]['out'], "details": JOBS[h]['details']}
#             else:
#                 # Job is marked finished and ok, but cache couldn't be accessed, we need to regenerate it
#                 vsl.LOG.info("[%s] Found job in JOBS, started at %s, marked finished and ok, but cache (%s) couldn't be accessed, we need to regenerate it" % (h, JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S"), out_filename))
#                 JOBS.pop(h)
#         else:
#             vsl.LOG.debug('[%s] Found job in JOBS, started at %s, not finished yet' % (h ,JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S")));
#             return {"out": "wait", "details": "Job started at %s" % JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S")}
#
#     vsl.LOG.debug("[%s] Adding multi job to the job list." % (h))
#
#     p = Process(target=multi_process_async, args=(files, req, h, out_filename))
#     p.start()
#     JOBS[h] = {'finished': False, 'started_at': datetime.datetime.now(), 'pid': p.pid}
#
#     vsl.LOG.debug("[%s] Job is running in process %d." % (h, p.pid))
#
#     if req['mode']=='async' and not force_sync:
#         return {"out": "wait", "details": "Multi-job started at %s" % JOBS[h]['started_at'].strftime("%m/%d/%Y, %H:%M:%S")}
#     elif req['mode']=='sync' or force_sync:
#         p.join()
#         j = JOBS[h]
#         if 'out' in j:
#             output = {"out": j['out'], "details": j['details']}
#             JOBS.pop(h)
#             return output
#         else:
#             return {'out': 'error', 'details': "Not sure what happened here... JOB=%s" % repr(j)}

def multi_process_async(req, h, out_filename):

    vsl.LOG.debug("[%s] Starting multi_process_async..." % (h))

    r = req.copy()
    r['stack'] = []
    hc = job_signature(r)
    concatenated_path = os.path.join(os.path.abspath(vsc.CONFIG['cachefolder']), '_multi_', hc[0])
    concatenated_filename = os.path.join(concatenated_path, hc+"."+vsc.CONFIG['cacheformat'])

    if not os.path.exists(concatenated_path):
        os.makedirs(concatenated_path)

    j = JOBS[h]

    if os.access(concatenated_filename, os.R_OK):
        # The file already exists and is accessible, we skip creation
        vsl.LOG.debug("[%s] Found concatenated file '%s' in cache." % (h, concatenated_filename))

    else:

        o = list()
        for i,f in enumerate(req['file']):
            if isinstance(f, dict):
                r = f
                r['format'] = vsc.CONFIG['cacheformat']
                r['format_options'] = vsc.CONFIG['cacheformatoptions']
                o.append(process(r, True))
            elif isinstance(f, str): # This is a file
                o.append( {'out': 'ok', 'details': f} )
            else:
                j = JOBS[h]
                j['out'] = 'error'
                j['details'] = "Element %d of multi-query is of unhandled type (%s)." % (i, type(f))
                j['finished'] = True
                JOBS[h] = j
                vsl.LOG.debug("[%s] Element %d of multi-query is of unhandled type (%s)." % (h, i, type(f)))
                return

        # if any([x['out']=='error' for x in o]):
        #     j['out'] = 'error'
        #     j['details'] = "\n".join([x['details'] for x in o])
        #     j['finished'] = True
        #     JOBS[h] = j
        #     vsl.LOG.debug("[%s] There was an error while processing one the files:\n%s" % (h, j['details']))
        #     return
        #     #return {'out': 'error', 'details': j['details']}

        # if any([x['out']=='wait' for x in o]):
        #     j['out'] = 'wait'
        #     j['details'] = "\n".join([x['details'] for x in o])
        #     JOBS[h] = j
        #     vsl.LOG.debug("[%s] One of the file's processing is not done yet" % (h))
        #     continue

        if all([x['out']=='ok' for x in o]):

            vsl.LOG.debug("[%s] All files are ready, now concatenating..." % (h))

            y    = None
            fs_y = None
            for oj in o:
                #job_info['used_files'].append(j['details'])
                # OJ DETAILS IS A DICT!
                # if os.path.splitext(oj['details'])[1].strip('.').lower() not in SUPPORTED_SOUND_EXTENSIONS:
                #     vsl.LOG.debug("[%s] Sound format not supported for '%s'." % (h, oj['details']))
                #     j['out'] = 'error'
                #     j['details'] = "Sound format not supported for '%s'." % (oj['details'])
                #     j['finished'] = True
                #     JOBS[h] = j
                #     vsl.LOG.debug("[%s] Job is done!" % (h))
                #     return

                try:
                    x, fs = sf.read(oj['details'])
                except Exception as e:
                    err = "Error while reading %s...\n%s" % (oj['details'],e)
                    vsl.LOG.debug("[%s] %s" % (h, err))
                    j = JOBS[h]
                    j['out'] = 'error'
                    j['details'] = err
                    j['finished'] = True
                    JOBS[h] = j
                    vsl.LOG.debug("[%s] Job is done!" % (h))
                    return

                if y is None:
                    y = x
                    fs_y = fs
                else:
                    if fs!=fs_y:
                        j = JOBS[h]
                        j['out'] = 'error'
                        j['details'] = 'Mismatching sampling frequencies between ['+oj['details']+'] and ['+(", ".join([x['details'] for x in o if x['details']!=oj['details']]))+'])'
                        j['finished'] = True
                        JOBS[h] = j
                        vsl.LOG.debug("[%s] File `%s` has a mismatching sampling frequency (%d instead of %d)..." % (h, oj['details'], fs, fs_y))
                        return

                    y = np.concatenate((y, x), axis=0)

            vsl.LOG.debug("[%s] Writing out concatenated sounds to `%s`..." % (h, concatenated_filename))
            sf.write(concatenated_filename, y, fs_y)

        else:
            j = JOBS[h]
            j['out'] = 'error'
            j['details'] = "There was an error when processing one of the subqueries."
            j['finished'] = True
            JOBS[h] = j
            vsl.LOG.debug("[%s] There was an error when processing one of the subqueries." % (h))
            return


    r = req.copy()
    r['file'] = concatenated_filename
    o = process(r, True)

    if o['out']!='ok':
        j = JOBS[h]
        j['out'] = o['out']
        j['details'] = o['details']
        j['finished'] = True
        JOBS[h] = j
        vsl.LOG.debug("[%s] Multi-job failed on concatenated file!" % (h))
        return

    if cast_outfile(o['details'], out_filename, req, h):
        j = JOBS[h]
        j['out'] = 'ok'
        j['details'] = out_filename
        j['finished'] = True
        JOBS[h] = j

        vsl.LOG.debug("[%s] Multi-job is done!" % (h))
    else:
        vsl.LOG.debug("[%s] Casting failed." % (h))


def process_module(f, m, format, cache=None):
    """
    Applying a single module and managing the job-file.

    :param f: The source file (string) or sub-query (dict).

    :param m: The module parameters.

    :param format: The file format the sound needs to be generated into.

    :param cache: The cache expiration policy (either None, by default, or a tuple with a
        date and a number of hours).

    """
    # Do we have this already in cache?
    hm = vsct.signature((os.path.abspath(f), m))
    hm_job = m['module']+'/'+hm

    if hm in JOBS:
        j = JOBS[hm_job]
        if not j['finished']:
            j['lock'].wait(5)
    else:
        j = {'finished': False, 'started_at': datetime.datetime.now(), 'lock': manager.Event()}
        JOBS[hm_job] = j

    module_cache_path = os.path.join(os.path.abspath(vsc.CONFIG['cachefolder']), m['module'])
    if format=='mp3':
        # We save in wav first, and will convert to mp3 at the end
        cache_filename = os.path.join(module_cache_path, hm+".wav")
    else:
        cache_filename = os.path.join(module_cache_path, hm+"."+vsc.CONFIG['cacheformat'])

    if not os.path.exists(module_cache_path):
        os.makedirs(module_cache_path)

    if os.access(cache_filename, os.R_OK):
        try:
            vsct.update_job_file(cache_filename)
        except Exception as err:
            vsl.LOG.warning("Something went wrong while updating the job-file associated with %s: %s" % (cache_filename, err))

        f = cache_filename
    else:
        if 'file' in m:
            if type(m['file'])==type(dict()):
                # This is a module that takes a file as argument, and the file is a query
                # We run the query first and substitute the file with the result
                q = copy.deepcopy(m['file'])
            elif type(m['file'])==type(list()):
                q = {'file': copy.deepcopy(m['file']), 'stack': list()}
            else:
                raise Exception("`file` is of type %s, which is not recognized (expecting list or dict)." % (type(m['file'])))

            res = process(q, True)

            if res['out']=='ok':
                m['file'] = res['details']
            else:
                raise Exception(res['details'])

        # Calling the right module
        source_files = list()

        if vsm.MODULES[m['module']].type == 'modifier':
            o = vsm.MODULES[m['module']](f, m, cache_filename)
            source_files = [f]

        elif vsm.MODULES[m['module']].type == 'generator':
            o, sources_files = vsm.MODULES[m['module']](f, m, cache_filename)
            if sources_files is None:
                sources_files = []

        if 'file' in m:
            source_files.append(m['file'])

        vsct.job_file(o, source_files, cache, m)

        f = o

    j = JOBS[hm_job]
    j['lock'].set()
    j['finished'] = True
    JOBS[hm_job] = j

    return f

def encode_to_format(in_filename, out_filename, fmt, fmt_options):
    """
    Encodes the file to the required format. This is for formats that are not supported by libsndfile (yet), like mp3.
    """
    if fmt=='mp3':
        if fmt_options is None:
            fmt_options = dict()
        if 'bitrate' not in fmt_options:
            fmt_options['bitrate'] = 160
        cmd = [vsc.CONFIG['lame'], '--noreplaygain', '--cbr', '-b '+str(int(fmt_options['bitrate'])), in_filename, out_filename]

        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


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
