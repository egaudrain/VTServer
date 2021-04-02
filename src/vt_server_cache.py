#!/usr/bin/env python3
# coding: utf-8

"""
Cache clean-up
==============

The cache can become big and obsolete, so it is a good idea to clean it up regularly.
In particular, if the original file does not exist anymore, all the processed files
should be removed.

For that, we use the job file that is created by the :py:mod:`vt_server_brain`.
The job file lists all the files that were created (or used) during a specific job.
If no job file exist for a specific cache file, we erase it. Note, that we may be
missing cache files from individual modules with this approach.

The :py:mod:`vt_server_cache` module has a command line interface so you can easily
put it in your crontab.

.. code-block:: text

    usage: vt_server_cache.py [-h] [-l LEVEL] [-s] [folder]

    positional arguments:
      folder                The cache folder to cleanse. If none is provided, we
                            will try to read from the default option file.

    optional arguments:
      -h, --help            show this help message and exit
      -l LEVEL, --level LEVEL
                            Level of cleansing [default 0]. 0 will remove all
                            files created by jobs that are related to files that
                            do not exist anymore. 1996 will remove *ALL* files
                            from the cache.
      -s, --simulate        Will not do anything, but will show what it would do.

The cache cleaning procedure is described below.

.. image:: img/cache.png
  :alt: Cache cleanup overview

"""

import vt_server_config as vsc
#import vt_server_logging as vsl

import os, pickle, time, datetime

def delete_file(f, simulate, cache_folder=None, silent=False, indent=0):

    if cache_folder is not None:
        fn = f.replace(cache_folder, '{cache}', 1)
    else:
        fn = f

    print("   "+("   "*indent)+"[Deleting] "+fn)
    if not simulate:
        try:
            os.remove(f)
            return True
        except Exception as err:
            if not silent:
                print(err)
            return False

def spooky_cleanup_cache(fold, simulate, indent=0, cache_folder=None):

    if cache_folder is None:
        cache_folder = fold

    try:
        lst = os.scandir(fold)
        print(("   "*indent)+fold+"/")
        for f in lst:
            if f.is_dir():
                spooky_cleanup_cache(f.path, simulate, indent+1, cache_folder)
            else:
                delete_file(f.path, simulate, cache_folder, False, indent)
        return 0
    except Exception as err:
        print(err)
        return 1



def cleanup_cache(fold=None, level=0, simulate=False):
    """
    The function that cleans up the cache. The **level** argument is used to specify
    how spooky clean you want your cache:

    * 0 is the standard (and default) level, it will scoure the cache folder for
      generated files. If a file does not have an eponym .job file, it will be deleted.
      Otherwise, the job file is opened, and, if the original sound file does not exist
      any more, all files listed as "created" are deleted. The final sound file
      (or symlinks) created are deleted as well as the job file.

    * 1996 will make your cache spooky clean by eliminating all files (but preserving
      the directory structure).

    """

    if simulate:
        print("\n!! We are simulating !!\n")

    if fold is None:
        fold = vsc.CONFIG['cachefolder']

    fold = os.path.abspath(fold)

    print("Scanning cache folder [%s]...\n" % fold)

    if level>=1996:
        print("We are running in SPOOKY CLEAN mode!\n")
        return spooky_cleanup_cache(fold, simulate)

    # lst = os.scandir(fold)

    found_job_files = list()
    scanned_job_files = list()

    for root, dirs, files in os.walk(fold):

        for fn in files:

            f = os.path.join(root, fn)
            fe, ext = os.path.splitext(f)

            if ext == ".job":
                found_job_files.append(f)
                continue
            else:

                print("%s:" % f.replace(fold, '{cache}', 1))

                job_file = fe+".job"

                try:
                    scanned_job_files.append(job_file)
                    job = pickle.load(open(job_file, "rb"))
                    print("   [Job] Loaded job file "+(job_file.replace(fold, '{cache}', 1)))

                except Exception as err:

                    st = os.stat(f)
                    if st.st_mtime < time.time() - 120:
                        print("   [No-job] Cannot open job file, and target older than 2 min. The error was:\n       %s" % str(err))
                        delete_file(f, simulate, fold)
                    else:
                        print("   [No-job] Cannot open job file, but target is younger than 2 min. The error was:\n      %s" % str(err))
                        print("   [Keeping] File is too young to be killed.")

                    if os.path.isfile(job_file):
                        delete_file(job_file, simulate, fold, True)

                else:
                    if'cache_expiration' not in job or job['cache_expiration'] is None or datetime.datetime.now() <= job['cache_expiration'][0]:

                        if job['cache_expiration'] is None:
                            cache_date = 'never expires'
                        else:
                            cache_date = str(job['cache_expiration'][0])

                        print("   Cache is not expired ("+cache_date+").")

                        all_there = True
                        source_file_list = ""

                        for fs in job['source_files']:
                            e = os.path.exists(fs)
                            source_file_list += "\n      "
                            if e:
                                source_file_list += "[X] "
                            else:
                                source_file_list += "[ ] "
                            source_file_list += fs.replace(fold, "{cache}", 1)
                            all_there &= e

                        if all_there:
                            print("   All source files still exist:" + source_file_list)
                            print("   [Keeping]")
                            continue
                        else:
                            print("   Some source files are missing:" + source_file_list)

                    else:
                        print("   Cache expired on %s." % job['cache_expiration'][0])

                    # Some files are missing
                    delete_file(f, simulate)
                    delete_file(job_file, simulate)


    for f in found_job_files:
        if f in scanned_job_files:
            continue

        print("Deleting orphan job file: "+f)
        delete_file(f, simulate)

    return 0


if __name__=="__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--level", help="Level of cleansing [default 0]. 0 will remove all files created by jobs that are related to files that do not exist anymore. 1996 will remove *ALL* files from the cache.", type=int, default=0)
    parser.add_argument("-s", "--simulate", help="Will not do anything, but will show what it would do.", action="store_true")
    parser.add_argument("folder", help="The cache folder to cleanse. If none is provided, we will try to read from the default option file.", default=None, nargs='?')

    args = parser.parse_args()

    ret = cleanup_cache(args.folder, args.level, args.simulate)

    exit(ret)
