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

    # Run services
    try:
        asyncio.run(service.run())

    except KeyboardInterrupt:

        # Logging
        service.logger.info(
            "Shutting down the services."
        )

    finally:

        # Logging
        service.logger.info(
            'The services exited successfully.'
        )
