"""Exceptions raised by the Rain Bird RC2 integration."""


class RainBirdError(Exception):
    """Base RC2 error."""


class RainBirdAuthError(RainBirdError):
    """Authentication failed."""


class RainBirdConnectionError(RainBirdError):
    """The local RC2 could not be reached."""
