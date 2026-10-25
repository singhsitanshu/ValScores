"""Errors services raise for the API layer to translate into HTTP responses."""


class ServiceError(Exception):
    """Base class; ``str(error)`` is the client-facing message."""


class MatchNotFoundError(ServiceError):
    pass


class GameNotFoundError(ServiceError):
    pass


class AmbiguousRosterError(ServiceError):
    pass
