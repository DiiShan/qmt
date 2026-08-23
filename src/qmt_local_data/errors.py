class QmtLocalDataError(Exception):
    """Base error for the local database."""


class ConfigurationError(QmtLocalDataError):
    pass


class StorageLimitError(QmtLocalDataError):
    pass


class QualityGateError(QmtLocalDataError):
    pass


class LockError(QmtLocalDataError):
    pass


class CapabilityGateError(QmtLocalDataError):
    pass
