"""Expose the shared, typed logging interface."""

from atexit import register

from ._configuration import (
    Configuration,
    ConfigurationError,
    FileDestination,
    load_configuration,
)
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
register(LOG._close_at_exit)


def initialize_worker(owner: _Logger) -> None:
    """Connect this process's shared logger to an owner's queue.

    Parameters
    ----------
    owner : Logger
        The parent process logger passed through a process initializer.

    Raises
    ------
    ValueError
        If the owner has no initialized queue.
    RuntimeError
        If this process's logger is already initialized.
    """
    LOG._use_worker_backend(owner)
