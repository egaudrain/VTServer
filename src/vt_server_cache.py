#!/usr/bin/env python3
# coding: utf-8

"""
``Cache clean-up``
==================

The cache can become big and obsolete, so it is a good idea to clean it up regularly.
In particular, if the original file does not exist anymore, all the processed files
should be removed.

For that, we use the job file that is created by the :py:mod:`vt_server_brain`.
The job file lists all the files that were created (or used) during a specific job.
If no job file exist for a specific cache file, we erase it. Note, that we may be
missing cache files from individual modules with this approach.

The :py:mod:`vt_server_cache` module has a command line interface so you can easily
put it in your crontab.

.. code-block::

    usage: vt_server_cache.py [-h] [-l LEVEL] [-s] [folder]

    positional arguments:
      folder                The cache folder to cleanse. If none is provided, we
                            will try to read from the default option file.

    optional arguments:
      -h, --help            show this help message and exit
      -l LEVEL, --level LEVEL
                            Level of cleansing [default 0]. 0 will remove all
                            files created by jobs that are related to files that
                            do not exist anymore. 1 will also remove files that
                            were used in the process. 1996 will remove *ALL* files
                            from the cache.
      -s, --simulate        Will not do anything, but will show what it would do.


"""

import vt_server_config as vsc
import vt_server_logging as vsl

import os, pickle

def delete_file(f, simulate):
    if not simulate:
        try:
            os.remove(f)
            return True
        except Exception as err:
            print(err)
            return False

def spooky_cleanup_cache(fold, simulate):
    try:
        lst = os.scandir(fold)
        for f in lst:
            if f.is_dir():
                spooky_cleanup_cache(f.path, simulate)
            else:
                print("Deleting "+f.path)
                delete_file(f.path, simulate)
        return 0
    except Exception as err:
        print(err)
        return 1



def cleanup_cache(fold=None, level=0, simulate=False):
    """
    The function that cleans up the cache. The ``level`` argument is used to specify
    how spooky clean you want your cache:

    * 0 is the standard (and default) level, it will scoure the cache folder for
      generated files. If a file does not have an eponym .job file, it will be deleted.
      Otherwise, the job file is opened, and, if the original sound file does not exist
      any more, all files listed as "created" are deleted. The final sound file
      (or symlinks) created are deleted as well as the job file.

    * 1 is slightly more aggressive, where all files that are "created" or "used"
      will be deleted.

    * 1996 will make your cache spooky clean by eliminating all files (but preserving
      the directory structure).

    """

    if fold is None:
        fold = vsc.CONFIG['cachefolder']

    if level>=1996:
        return spooky_cleanup_cache(fold, simulate)


    lst = os.scandir(fold)

    found_job_files = list()
    scanned_job_files = list()

    for f in lst:
        if f.is_dir():
            continue

        if f.name.endswith(".job"):
            found_job_files.append(f.path)
            continue

        if f.name.endswith(".flac") or f.name.endswith(".wav") or f.name.endswith(".aiff"):

            job_file = os.path.splitext(f.path)[0]+".job"

            try:
                scanned_job_files.append(job_file)
                job = pickle.load(open(job_file, "rb"))
                print("Loaded job file "+job_file)

            except Exception as err:
                print("%s: Job file not found or impossible to open. Deleting." % f.name)
                delete_file(f.path, simulate)
                print("   Deleting the job file (if it existed) "+job_file)
                delete_file(job_file, simulate)

            else:
                if type(job['original_file'])==type([]):
                    all_there = True
                    for f in job['original_file']:
                        all_there &= os.path.exists(f)
                    if all_there:
                        print("   Original files for job %s still exist. Skipping." % job['original_file'])
                        continue

                elif os.path.exists(job['original_file']):
                    # The original file still exists, we do nothing
                    print("   Original file for job %s still exist. Skipping." % job['original_file'])
                    continue

                # Some files are missing
                try:
                    for cf in job['created_files']:
                        print("   Deleting created file " + cf)
                        delete_file(cf, simulate)

                    if level>=1:
                        for uf in job['used_files']:
                            print("   Deleting used file " + uf)
                            delete_file(uf, simulate)

                except Exception as err:
                    print(err)

                finally:
                    print("   Deleting the job file "+job_file)
                    delete_file(job_file, simulate)

                    # If something went wrong, we try to delete the output file again
                    if os.path.exists(f.path):
                        print("   Deleting output file " + f.name)
                        delete_file(f.path, simulate)

        else:
            # The file doesn't really anything to do here
            pass

    for f in found_job_files:
        if f in scanned_job_files:
            continue

        print("Deleting orphan job file: "+f)
        delete_file(f, simulate)

    return 0


if __name__=="__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--level", help="Level of cleansing [default 0]. 0 will remove all files created by jobs that are related to files that do not exist anymore. 1 will also remove files that were used in the process. 1996 will remove *ALL* files from the cache.", type=int, default=0)
    parser.add_argument("-s", "--simulate", help="Will not do anything, but will show what it would do.", action="store_true")
    parser.add_argument("folder", help="The cache folder to cleanse. If none is provided, we will try to read from the default option file.", default=None, nargs='?')

    args = parser.parse_args()

    ret = cleanup_cache(args.folder, args.level, args.simulate)

    exit(ret)
