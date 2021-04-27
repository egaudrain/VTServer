# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
sys.path.insert(0, os.path.abspath('../src'))
sys.path.insert(0, os.path.dirname(__file__))

import vt_server as vt

# -- Project information -----------------------------------------------------

project = 'VT Server'
copyright = '2021, Etienne Gaudrain'
author = 'Etienne Gaudrain'
version = vt.__version__


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    # 'sphinx.ext.linkcode'
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []

show_authors = False

# -- Options for linkcode -- -------------------------------------------------

# def linkcode_resolve(domain, info):
#     if domain!='py':
#         return None
#
#     return 'https://github.com/{project}/{view}/{branch}/{path}'.format(
#                 project='egaudrain/VTServer',
#                 view='blob',
#                 branch='master',
#                 path="src/"+info['module']+'.py')

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
# html_theme = 'nature'
html_theme = 'sphinx_rtd_theme'

html_theme_options = {
    'collapse_navigation': True,
    #'navigation_depth': 2
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']
html_css_files = [
    'css/custom.css',
]

import extract_vt_module_doc
