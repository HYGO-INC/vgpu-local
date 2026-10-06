class OutcomeUnknown(RuntimeError):
    """A side effect may have succeeded. Reconcile; never blindly repeat create."""


class KeyConflict(ValueError):
    """A durable operation identity was reused for a different request."""


class UnsupportedCapability(ValueError):
    pass
