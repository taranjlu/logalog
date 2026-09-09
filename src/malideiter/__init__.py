"""Expose the shared, typed logging interface."""

from atexit import register

from beartype import beartype

from ._backend import FileDestination
from ._configuration import Configuration, ConfigurationError, load_configuration
from ._logger import Logger as _Logger
from ._logger import environment_names

__all__ = [
    "LOG",
    "Configuration",
    "ConfigurationError",
    "FileDestination",
    "environment_names",
    "initialize_worker",
    "load_configuration",
]

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
