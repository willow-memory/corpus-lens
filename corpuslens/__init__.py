"""corpuslens — a local-first lens for your own human+agent corpus.

Stdlib only. Reads process; the wall keeps the absolute anchor (calendar date,
timezone, clock hour, filenames) out of what an analyzer sees — see guard.py
for exactly what that does and does not guarantee, and GRADING.md in this
repository for the rubric this instruments.
"""
# Read from the INSTALLED distribution's metadata, which hatch-vcs derived from
# the git tag at build time. A literal here would be a second copy of the
# version and would drift from the tag the moment one was cut — this module
# reported 0.1.0 while the build produced 0.1.dev41, and a wrong version in a
# bug report costs more than the import does.
#
# Running from a clone that was never installed has no distribution metadata to
# read, so it says so rather than guessing a number.
from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("corpuslens")
except PackageNotFoundError:       # a source checkout, not an installed package
    __version__ = "0+unknown"

del _version, PackageNotFoundError
