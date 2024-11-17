""" Audera commands """

from typing import Literal
import asyncio
from audera import server, client


# Define audera sub-command function(s)
def run(
    type_: Literal['server', 'client']
):
    """ Runs an `audera` async service.

    Parameters
    ----------
    type_ : `Literal['server', 'client']`
        The type of `audera` service.

    Help
    ----
    usage: audera run [-h] {server,client}

    positional arguments:
    {server,client}  The type of `audera` service.

    options:
    -h, --help       show this help message and exit

    Execute `audera run --help` for help.

    Examples
    --------
    ``` console
    audera run server
    ```

    """
    if type_.strip().lower() not in ['server', 'client']:
        raise NotImplementedError

    if type_.strip().lower() == 'server':

        # Initialize the server-service
        service = server.Service()

    if type_.strip().lower() == 'client':

        # Initialize the client-service
        service = client.Service()

    # Create an event-loop for handling all services
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run services
    try:
        loop.run_until_complete(service.run())

    except KeyboardInterrupt:

        # Logging
        service.logger.info(
            "INFO: Shutting down the services."
        )

        # Cancel any / all remaining running services
        tasks = asyncio.all_tasks(loop=loop)
        for task in tasks:
            task.cancel()
        loop.run_until_complete(
            asyncio.gather(
                *tasks,
                return_exceptions=True
            )
        )

    finally:

        # Close the event-loop
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

        # Logging
        service.logger.info(
            'INFO: The services exited successfully.'
        )

        # Close audio services
        service.stream.stop_stream()
        service.stream.close()
        service.audio.terminate()
