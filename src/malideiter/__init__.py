"""Expose the shared, typed logging interface."""

from ._logger import Logger as _Logger

__all__ = ["LOG"]

LOG = _Logger()
