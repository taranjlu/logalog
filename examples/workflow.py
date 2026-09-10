"""Show configuration, concurrent sections, Rich output, and safe command display."""

import asyncio
from os import environ
from pathlib import Path

from rich.table import Table

from malideiter import LOG, load_configuration


@LOG(elapsed=True)
async def worker(number: int) -> None:
    """Log one task without sharing mutable section state."""
    with LOG.section(f"Worker {number}"):
        await asyncio.sleep(0)
        LOG.info("Worker completed", worker_number=number)


async def run_workers() -> None:
    """Run two tasks within the current section context."""
    await asyncio.gather(worker(1), worker(2))


def main() -> None:
    """Run the example and close its logging destinations."""
    directory = Path(__file__).resolve().parent
    settings = load_configuration(directory / "workflow.toml", directory / "workflow.json")
    LOG.configure(configuration=settings)
    debug_name = "MALIDEITER_EXAMPLE_DEBUG"
    previous_debug = environ.get(debug_name)
    try:
        with LOG.section("Workflow", elapsed=True):
            LOG.verbose("Configuration merge enabled verbose")
            environ[debug_name] = "0"
            LOG.debug("Hidden debug event")
            environ[debug_name] = "1"
            LOG.debug("Live debug event")
            asyncio.run(run_workers())

            table = Table("Stage", "Status", title="Workflow results")
            table.add_row("Workers", "Complete")
            LOG.info(table)
            LOG.command(
                ["example-tool", "--token", "demonstration-token"],
                cwd=directory,
                redact_indices=(2,),
            )
            try:
                with LOG.section("Handled failure"):
                    raise ValueError("Demonstration failure")
            except ValueError:
                LOG.info("Recovered from demonstration failure")
        LOG.info("Workflow complete")
    finally:
        if previous_debug is None:
            environ.pop(debug_name, None)
        else:
            environ[debug_name] = previous_debug
        LOG.shutdown()


if __name__ == "__main__":
    main()
