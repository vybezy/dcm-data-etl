"""errors raised by services. the handlers in api/main.py turn them into http status codes."""


class InvalidSettingsError(Exception):
    """settings that pass the type checks but break a rule (e.g. max < min)."""


class NotFoundError(Exception):
    """the requested patient, study or series does not exist."""
