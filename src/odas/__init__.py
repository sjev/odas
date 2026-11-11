"""ODAS - configurable case management for NGOs, jurists and civil-society organisations."""

from __future__ import annotations

try:
    from setuptools_scm import get_version

    __version__ = get_version(root="../..", relative_to=__file__, local_scheme="no-local-version")
except Exception:
    from importlib.metadata import version

    __version__ = version("odas")
