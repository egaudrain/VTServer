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

In `'async'` mode it returns right away and sends a `'wait'` message. The client can
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

import soundfile as sf
import numpy as np

manager = Manager()
#: This is the list of current jobs (actually a managed dict).
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
        Checks periodically on the :py:data:`JOBS` list to see if there are any
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
    if "|" in req['file']:
        files = req['file'].split("|")
        return _job_signature_multi(files, req['stack'])
    else:
        return vsct.signature((os.path.abspath(req['file']), req['stack']))

def _job_signature_multi(files, stack):
    return vsct.signature(("|".join([os.path.abspath(x) for x in files]), stack))

def process(req):
    """
    Creates jobs (populating the :py:data:`JOBS` list), checks on cache and dispatches processing threads.

    :param req: The query received by the server.
    :type req: dict
    """

    global N_REQUESTS
    N_REQUESTS += 1

    if 'mode' not in req:
        req['mode'] = 'sync'

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
    else:
        return {'out': 'error', 'details':  "The 'cache' field could not be interpreted."}

    if type(req['file'])==type([]) or (' >> ' in req['file']):
        # Send to multi-process if there are multiple input files
        return multi_process(req)

    # TODO: Handle generators for file
    req['file'] = os.path.abspath(req['file'])

    if not os.access(req['file'], os.R_OK):
        vsl.LOG.debug("File '%s' was requested but cannot be accessed." % req['file'])
        return {'out': 'error', 'details': "File '%s' cannot be accessed" % req['file']}

    # For compatibility with multi-file queries
    if len(req['stack'])!=0 and type(req['stack'][0])==type([]):
        if len(req['stack'])>1:
            # We have a list of stacks with more than one stack...
            return {'out': 'error', 'details': "Cannot have a list of stacks (with more than one stack) when passing in a single file."}
        req['stack'] = req['stack'][0]

    #----------------------------
    # From here on, we are ready to call job_signature

    h = job_signature(req)

    vsl.LOG.info("[%s] Processing request: %s" % (h, req))

    if req['mode'] == 'hash':
        return {'out': 'ok', 'details': h}

    out_filename = os.path.join(vsc.CONFIG['cachefolder'], h+"."+req['format'])

    if os.access(out_filename, os.R_OK):
        # The file already exists and is accessible, we return it
        vsl.LOG.debug("[%s] Found %s in cache. Done." % (h, out_filename))
        try:
            vsct.update_job_file(out_filename)
        except:
            vsl.LOG.warning("[%s] Something went wrong while updating the job-file associated with %s" % (h,out_filename))
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

def multi_process(req):
    """
    This is called from :py:func:`process` if multiple files have been provided as input.
    """

    if type(req['file'])==type([]):
        files = req['file']
    else:
        files = req['file'].split(' >> ')
        # TODO: if files are separated with "<" they are concatenated prior to being passed in the stack
        # Note that as much as possible, this is not desirable for caching reasons, but that could be useful.

    if len(req['stack'])!=0:
        if type(req['stack'][0])==type({}):
            # We are dealing with a single stack applied to all elements: we duplicate it
            req['stack'] = [req['stack']]
        if len(req['stack'])==1 and len(files)>1:
            # We are dealing with a list of stacks, but of length 1
            req['stack'] = [ copy.deepcopy(req['stack'][0]) for f in files ]
        if len(req['stack'])!=len(files):
            return {'out': 'error', 'details': 'If a stack list is used, it must be of length 1 or of length equal to the number of files.'}
    else:
        req['stack'] = [[]]*len(files)

    h = _job_signature_multi(files, req['stack'])

    vsl.LOG.info("[%s] Multi-file processing request: %s" % (h, req))

    if req['mode'] == 'hash':
        return {'out': 'ok', 'details': h}

    out_filename = os.path.join(vsc.CONFIG['cachefolder'], "M"+h+"."+req['format'])

    if os.access(out_filename, os.R_OK):
        # The file already exists and is accessible, we return it
        vsl.LOG.debug("[%s] Found %s in cache. Done." % (h, out_filename))

        try:
            vsct.update_job_file(out_filename)
        except:
            vsl.LOG.warning("Something went wrong while updating the job-file associated with %s" % out_filename)

        return {"out": "ok", "details": out_filename}

    else:
        #vsl.LOG.debug("Adding multi job %s to the job list." % h)

        # job_info = dict()
        # job_info['original_files'] = files
        # job_info['support_files'] = list()
        # job_info['stack'] = req['stack']
        # job_info['cache_expiration'] = req['cache']
        # job_filename = os.path.splitext(out_filename)[0]+".job"

        resp = dict()
        o = list()
        for i,f in enumerate(files):
            if len(req['stack'][i]) == 0:
                # If there is no stack, we bypass process altogether
                o.append( {'out': 'ok', 'details': f} )
            else:
                r = dict()
                r['action'] = req['action']
                r['file'] = f
                r['mode'] = req['mode']
                r['stack'] = req['stack'][i]
                r['format'] = vsc.CONFIG['cacheformat']
                r['format_options'] = vsc.CONFIG['cacheformatoptions']
                o.append(process(r))

        if any([x['out']=='error' for x in o]):
            return {'out': 'error', 'details': "\n".join([x['details'] for x in o])}

        elif any([x['out']=='wait' for x in o]):
            return {'out': 'wait', 'details': "\n".join([x['details'] for x in o])}

        elif all([x['out']=='ok' for x in o]):
            resp['out'] = 'ok'
            y    = None
            fs_y = None
            for j in o:
                #job_info['used_files'].append(j['details'])
                x, fs = sf.read(j['details'])
                if y is None:
                    y = x
                    fs_y = fs
                else:
                    if fs!=fs_y:
                        return {'out': 'error', 'details': 'Mismatching sampling frequencies in ['+(", ".join(files))+'] (actually from ['+(", ".join([x['details'] for x in o]))+'])'}
                    y = np.concatenate((y, x), axis=0)

            if req['format'] == 'mp3':
                tmp_filename = os.path.join(vsc.CONFIG['cachefolder'], "M"+h+".wav")
                sf.write(tmp_filename, y, fs)
                #job_info['created_files'].append(tmp_filename)
                try:
                    encode_to_format(tmp_filename, out_filename, req['format'], req['format_options'])
                    vsct.job_file(out_filename, files, req['cache'], req['stack'])
                except Exception as err:
                    err_msg = "Encoding of '%s' to format '%s' failed with error: %s, %s" % (tmp_filename, req['format'], err, err.output.decode('utf-8'))
                    vsl.LOG.critical(err_msg)
                    return {'out': 'error', 'details': err_msg}
            else:
                sf.write(out_filename, x, fs)
                vsct.job_file(out_filename, [x['details'] for x in o], req['cache'], req['stack'])

            # job_info['created_files'].append(out_filename)
            # pickle.dump(job_info, open(job_filename, "wb"))

            return {'out': 'ok', 'details': out_filename}

        else:
            return {'out': 'error', 'details': "Huuuu... we multiple times shouldn't find ourselves here... %s" % repr(req)}



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

    # TODO: handle generators for file
    f = req['file']

    j = JOBS[h]

    # job_info = dict()
    # job_info['source_files'] = [f] # If source file does not exist anymore, the job is deleted
    # job_info['support_files'] = list() # Additional files that need deleting if source file is missing, but not if there is simple cache expiration
    # job_info['stack'] = req['stack']
    # job_info['cache_expiration'] = req['cache']
    # job_filename = os.path.splitext(out_filename)[0]+".job"

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
                module_cache_path = os.path.join(os.path.abspath(vsc.CONFIG['cachefolder']), m['module'])
                if req['format']=='mp3':
                    # We save in wav first, and will convert to mp3 at the end
                    cache_filename = os.path.join(module_cache_path, hm+".wav")
                else:
                    cache_filename = os.path.join(module_cache_path, hm+"."+vsc.CONFIG['cacheformat'])

                if not os.path.exists(module_cache_path):
                    os.makedirs(module_cache_path)

                if os.access(cache_filename, os.R_OK):
                    try:
                        vsct.update_job_file(cache_filename)
                    except:
                        vsk.LOG.warning("Something went wrong while updating the job-file associated with %s" % cache_filename)

                    f = cache_filename
                else:
                    if 'file' in m and type(m['file'])==type(dict()):
                        # This is a module that takes a file as argument, and the file is a query
                        # We run the query first and substitute the file with the result
                        q = copy.deepcopy(m['file'])
                        q['mode'] = 'sync'
                        res = process(q)
                        if res['out']=='ok':
                            m['file'] = res['details']
                        else:
                            raise Exception(res['details'])

                    # Calling the right module
                    o = vsm.PATCH[m['module']](f, m, cache_filename)
                    source_files = [f]
                    if 'file' in m:
                        source_files.append(m['file'])
                    vsct.job_file(o, source_files, req['cache'], m)

                    f = o

                    vsl.LOG.debug("[%s] Done with module '%s'" % (h, m['module']))

            except Exception as err:
                #err_msg = "Something went wrong while running module '%s' on file '%s': %s" % (m['module'], f, repr(err))
                err_msg = "Something went wrong while running module '%s' on file '%s': %s" % (m['module'], f, traceback.format_exc())
                j['out'] = 'error'
                j['details'] = err_msg
                j['finished'] = True
                JOBS[h] = j
                vsl.LOG.critical(err_msg)
                return
        else:
            err_msg = "Calling unknown module '%s' while processing '%s'." % (m['module'], f)
            j['out'] = 'error'
            j['details'] = err_msg
            j['finished'] = True
            JOBS[h] = j
            vsl.LOG.critical(err_msg)
            return

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
                j['out'] = 'error'
                j['details'] = err_msg
                j['finished'] = True
                JOBS[h] = j
                vsl.LOG.critical(err_msg)
                return
        else:
            x, fs = sf.read(f)
            sf.write(out_filename, x, fs)
            vsct.job_file(out_filename, [f], req['cache'], req['stack'])

    # job_info['created_files'].append(out_filename)
    #
    # job_info['created_files'] = [os.path.abspath(f) for f in job_info['created_files']]
    # job_info['support_files'] = [os.path.abspath(f) for f in job_info['used_files']]
    # pickle.dump(job_info, open(job_filename, "wb"))

    j['out'] = 'ok'
    j['details'] = out_filename
    j['finished'] = True
    JOBS[h] = j

    vsl.LOG.debug("[%s] Finished with processing the stack." % (h))

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
