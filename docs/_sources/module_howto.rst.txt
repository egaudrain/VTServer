********************
How to make a module
********************

The VT Server functionality can be extended by creating new modules. This section
gives some pointers on how to do just that.

The basic principle is pretty straightforward. If we were writing a module called
"toto", we would have to define a function with the following signature:

.. code-block::

    def process_toto(in_filename, parameters, out_filename):
        ...
        return out_filename

in_filename
    The path to the input filename. It is either an original file,
    or an intermediary file passed on by the previous module in a stack of modules.

parameters
    The module's parameters definition. This is what a user pass to
    the module in a query.

out_filename
    Provided by the :mod:`vt_server_brain`. The module is responsible
    for writing the file down once the processing is finished.

The first step should be to write some code to parse the module's parameters. Keep in mind
that the query results are cached: if the same query is sent again, it will not even be sent to
your function, but will be picked-up by the :mod:`vt_server_brain` before that. If your processing
contains random elements that need to be regenerated everytime, you should add a random seed as
parameter in your queries, and make sure to set the `cache` directive to a short enough value.

Cache management
================

When writing a module, you don't need to worry about caching results of queries.
This is managed by the :mod:`vt_server_brain`. In other words, the job of the module
process function is just to read the input file, apply the modifications you need
to apply to the sound based on the parameters, and then save the result in **out_filename**.

The function also returns **out_filename**. However, if you need to generate any
intermediary files you will need handle caching of these files yourself. To that purpose,
you need to create a job-file for every file that you generate and that is meant
to remain on the server for some time. Use the :func:`vt_server_common_tools.job_file` function, in the
:py:mod:`vt_server_common_tools` module, for that purpose.

An example of this can be found in the `world` module where the result of the analysis
phase is saved in a file so that only synthesis needs to be done for new voice parameters.
We need to create a job file so that the cache clean-up routines can handle
these files properly.

Sound files are read with :mod:`soundfile`.

Naming convention
=================

The process function and you module file must follow a specific naming convention
to be automatically discovered by the server once placed in the server directory.

The module must be named `vt_server_module_`\ *name*\ `.py` and the process function to be called must be named
`process_`\ *name*.

For example, if your module is called "toto", the module file will be called
`vt_server_module_toto.py` and the process function will be called `process_toto`.

With this convention, the module can be called in a query with the name "toto":

.. code-block:: json

    {
        "action": "process",
        "file": "/home/toto/audio/Beer.wav",
        "stack": [
            {
                "module": "toto",
                "param1": "blahdiblah"
            }
        ]
    }
