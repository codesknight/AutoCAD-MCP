"""Backend lifecycle errors; existing CAD operation exceptions remain unchanged."""

class BackendError(RuntimeError):
    code = "BACKEND_ERROR"

class UnsupportedBackendError(BackendError):
    code = "UNSUPPORTED_BACKEND"

class UnsupportedOperationError(BackendError):
    code = "UNSUPPORTED_OPERATION"

class BackendClosedError(BackendError):
    code = "BACKEND_CLOSED"

class BackendQueueFullError(BackendError):
    code = "QUEUE_FULL"

class BackendWorkerError(BackendError):
    code = "BACKEND_UNAVAILABLE"
