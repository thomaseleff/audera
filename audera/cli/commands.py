""" Audera commands """

from typing import Literal
from audera import server, client


# Define audera sub-command function(s)
def run(
    type_: Literal['server', 'client']
):
    """ Runs an `audera` service.

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
        return server.Service().run()

    if type_.strip().lower() == 'client':
        return client.Service().run()
