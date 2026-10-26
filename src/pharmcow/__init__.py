"""PharmCOW - personal PGx report generator."""

import os
import tempfile

# pypgx -> fuc -> matplotlib: keep its cache out of the (possibly read-only) home.
os.environ.setdefault(
    "MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "pharmcow-matplotlib")
)

__version__ = "0.1.0"
