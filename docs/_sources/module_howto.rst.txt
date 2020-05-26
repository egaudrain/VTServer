How to make a module
====================

The VT Server functionality can be extended by creating new modules. This section
gives some pointers on how to do just that.

The basic principle is pretty straightforward. If we were writing a module called
`toto`, we would have to define a function with the following signature:

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

When writing a module, you don't need to worry about caching results of queries.
This is managed by the :mod:`vt_server_brain`. In other words, the job of the module
process function is just to read the input file, apply the modifications you need
to apply to the sound based on the parameters, and then save the result in **out_filename**.

The function also returns **out_filename**. However, if you need to generate any
intermediary files you will need to report that back as well. This is the case,
for instance, for the `world` module where the result of the analysis phase is saved
in a file so that only synthesis needs to be done for new voice parameters. We need
to report these files to the brain so that the cache clean-up routines can handle
these files properly. Similarly, if the generation relies other external files, they
need to be listed. When this is the case, the return signature is:

.. code-block::

    import soundfile as sf

    def process_toto(in_filename, parameters, out_filename):

        created_files = list()
        used_files    = list()

        x, fs = sf.read(in_filename)

        # Do you processing...
        # Everytime you generate a file, you need to append it to created_files
        # Everytime you load an external file, you need to append it to used_files

        sf.write(out_filename, y, fs)

        return out_filename, created_files, used_files

Sound files are read with :mod:`soundfile`.

Once your process function is ready, you need to add it to the :data:`PATCH` in
:mod:`vt_server_modules`:

.. code-block::
    
    from vt_module_toto import process_toto
    PATCH['toto'] = process_toto

Note that at the moment there is not automated way of inserting custom modules, so
you need to edit :file:`vt_server_modules.py`. Keep that in mind when you update
the VTServer.
