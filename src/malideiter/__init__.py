"""Expose the shared, typed logging interface."""

from atexit import register

from beartype import beartype

from ._logger import ConfigurationError, environment_names
from ._logger import Logger as _Logger

__all__ = ["LOG", "ConfigurationError", "environment_names", "initialize_worker"]

LOG = _Logger()
register(LOG.shutdown)


@beartype
def initialize_worker(owner: _Logger) -> None:
    """Connect this process's shared logger to an owner's queue.

    Parameters
    ----------
    owner : Logger
        The parent process logger passed through a process initializer.
    """
    if LOG is not owner:
        LOG._use_worker_backend(owner)
