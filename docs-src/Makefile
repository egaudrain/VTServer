# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = ./
BUILDDIR      = ../docs

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
html:
	@$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
	touch "$(BUILDDIR)/.nojekyll"


.PHONY: html
