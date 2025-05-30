""" Logging """

import logging

# ANSI escape sequences for colors
COLORS = {
    'black': '\033[30m',
    'red': '\033[31m',
    'green': '\033[32m',
    'yellow': '\033[33m',
    'blue': '\033[34m',
    'magenta': '\033[35m',
    'cyan': '\033[36m',
    'white': '\033[37m',
    'bold_red': '\033[1;31m',
}

# Default color to reset formatting
RESET = '\033[0m'


# Alias logging.Logger for type hinting
class Logger(logging.Logger):
    def __init__(self, args, kwargs):
        super().__init__(*args, **kwargs)


class logger():
    """ A `class` that represents a generic logging handler. """

    def __init__(
        self,
        name: str = __name__,
        level: int = logging.DEBUG,
        text_color: str = RESET
    ):
        """ Creates an instance of the generic logger.

        Parameters
        ----------
        name: `str`
            The name of the logger.
        level: `int`
            The severity of the log messages.
        text_color: `str`
            The text-color of the console log messages.
        """
        self.logger = logging.getLogger(name=name)
        self.logger.setLevel(level=level)

        # Create and format a console handler
        if not self.logger.handlers:
            debugger = logging.StreamHandler()
            debugger.setLevel(level=level)
            debugger.setFormatter(
                fmt=logging.Formatter(
                    f'{text_color}[{name}] %(message)s{RESET}'
                )
            )
            self.logger.addHandler(hdlr=debugger)

    def get(self):
        """ Returns the logger instance. """
        return self.logger

    def message(self, message: str):
        """ Logs message with an un-set severity.

        Parameters
        ----------
        message: `str`
            The log-message content.
        """
        self.logger.info(f"{message}")

    def debug(self, message: str):
        """ Logs message with severity `DEBUG`.

        Parameters
        ----------
        message: `str`
            The log-message content.
        """
        self.logger.debug(
            f"{COLORS['blue']}    DEBUG: {message}{RESET}"
        )

    def info(self, message: str):
        """ Logs message with severity `INFO`.

        Parameters
        ----------
        message: `str`
            The log-message content.
        """
        self.logger.info(
            f"    INFO: {message}"
        )

    def warning(self, message: str):
        """ Logs message with severity `WARNING`.

        Parameters
        ----------
        message: `str`
            The log-message content.
        """
        self.logger.warning(
            f"{COLORS['yellow']}  * WARNING: {message}{RESET}"
        )

    def error(self, message: str):
        """ Logs message with severity `ERROR`.

        Parameters
        ----------
        message: `str`
            The log-message content.
        """
        self.logger.error(
            f"{COLORS['red']} ** ERROR: {message}{RESET}"
        )

    def critical(self, message: str):
        """ Logs message with severity `CRITICAL`.

        Parameters
        ----------
        message: `str`
            The log-message content.
        """
        self.logger.critical(
            f"{COLORS['bold_red']}*** CRITICAL: {message}{RESET}"
        )


# Create application-loggers
def get_streamer_logger() -> logger:
    """ Get the `audera` streamer console logger. """
    return logger(name='streamer')


def get_player_logger() -> logger:
    """ Get the `audera` player console logger. """
    return logger(name=' player ')
