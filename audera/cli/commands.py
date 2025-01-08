""" Audera commands """

from typing import Literal
import asyncio
from audera import client, streamer


# Define audera sub-command function(s)
def run(
    type_: Literal['streamer', 'player']
):
    """ Runs an `audera` async service.

    Parameters
    ----------
    type_ : `Literal['streamer', 'player']`
        The type of `audera` service.

    Help
    ----
    usage: audera run [-h] {streamer,player}

    positional arguments:
    {streamer,player}  The type of `audera` service.

    options:
    -h, --help       show this help message and exit

    Execute `audera run --help` for help.

    Examples
    --------
    ``` console
    audera run streamer
    ```

    """
    if type_.strip().lower() not in ['streamer', 'player']:
        raise NotImplementedError

    if type_.strip().lower() == 'streamer':

        # Initialize the streamer service
        service = streamer.Service()

    if type_.strip().lower() == 'player':

        # Initialize the remote audio output player service
        service = client.Service()

    # Run services
    try:
        asyncio.run(service.run())

    except KeyboardInterrupt:

        # Logging
        service.logger.info("Shutting down the services.")

    finally:

        # Logging
        service.logger.info('The services exited successfully.')
