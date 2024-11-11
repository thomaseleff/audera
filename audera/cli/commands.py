""" Audera commands """

from typing import Literal
from audera import server, client


# Define audera sub-command function(s)
def run(
    type_: Literal['server', 'client']
):
    """ Runs an `audera` application.

    Parameters
    ----------
    type_ : `Literal['server', 'client']`
        The type of `audera` application.

    Help
    ----
    usage: audera run [-h] {server,client}

    positional arguments:
    {server,client}  The type of `audera` application.

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
        return server.App().run()

    if type_.strip().lower() == 'client':
        raise client.App().run()
