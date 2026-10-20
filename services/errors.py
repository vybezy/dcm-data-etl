"""errors raised by services. controllers turn them into http status codes."""


class InvalidSettingsError(Exception):
    """settings that pass the type checks but break a rule (e.g. max < min)."""
