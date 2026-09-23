class SchemaError(ValueError):
    """A source returned data in a shape we don't recognise.

    Free endpoints change without notice; this is the loud failure that tells us.
    """


class SourceError(RuntimeError):
    """A source could not be fetched (network failure or non-200 response)."""
