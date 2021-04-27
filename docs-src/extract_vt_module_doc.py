# Extracting documentation from modules

import os
import sys
sys.path.insert(0, os.path.abspath('../src'))
import re
from importlib import import_module
from collections import OrderedDict

SECTION_ADORNMENTS = "=-^~*+`:.'\"_#"

reSection = re.compile(r"^(?P<ad>[%s]{2,}\n)?( ?\S.*?\n)((?P=ad)|[%s]{2,})" % ((SECTION_ADORNMENTS.replace('-', '\-'),)*2), re.M)

def adjust_module_doc(doc):
    levels = OrderedDict()
    #rep = list()
    i = 0
    while True:
        g = reSection.search(doc, i)
        if not g:
            break
        s = g.span()
        i = s[1]
        l = g[3][0]
        if l not in levels:
            levels[l] = SECTION_ADORNMENTS[len(levels)+1]
        if levels[l] == SECTION_ADORNMENTS[1]:
            # We remove the first level
            new_string = " "*len(g[0])
        else:
            new_string = ''
            if g[1] is not None:
                new_string += g[1].replace(l, levels[l])
            new_string += g[2]
            new_string += g[3].replace(l, levels[l])
            #rep.append([g.span(), new_string])


        doc = doc[:s[0]] + new_string + doc[s[1]:]

    return doc


import vt_server_modules as vsm
vsm.discover_modules()

rst = open("vt_modules.rst", "w")

rst.write("""
.. _available-modules:

=================
Available modules
=================

.. toctree::

""")

for vtmod_name in sorted(vsm.MODULES.keys()):

    print("Found "+vtmod_name)

    mod_name = vsm.MODULES[vtmod_name].process_function.__module__

    if mod_name == 'vt_server_modules':
        print("    That's a function")
        d = vsm.MODULES[vtmod_name].process_function.__doc__
        rst.write("\n\n"+"----------"+"\n\n``%s``\n"%vtmod_name+(SECTION_ADORNMENTS[1]*(len(vtmod_name)+4))+"\n\n"+d+"\n\n")
    else:
        print("    That's a module")
        mo = import_module(mod_name)
        d = getattr(mo, '__doc__')
        d = adjust_module_doc(d)

        #rst.write("\n\n.. function:: "+vtmod_name+"\n\n"+d)

        rst.write("\n\n"+"----------"+"\n\n``%s``\n"%vtmod_name+(SECTION_ADORNMENTS[1]*(len(vtmod_name)+4))+"\n\n"+d+"\n\n")
