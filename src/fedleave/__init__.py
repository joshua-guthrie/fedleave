"""Expose the FedLeave version and embedded source-build identity."""

from __future__ import annotations

import os

__base_version__ = "0.2.2"
__version__ = os.environ.get("FEDLEAVE_BUILD_VERSION", "").strip() or __base_version__
__build_commit__ = os.environ.get("FEDLEAVE_SOURCE_COMMIT", "").strip().lower()

__all__ = ["__base_version__", "__build_commit__", "__version__"]
