"""Backend choice is centralized; unsupported choices never fall back."""
from autocad_mcp.config import Config
from autocad_mcp.cad.backends.base import CadBackend
from autocad_mcp.cad.errors import UnsupportedBackendError

def create_backend(config: Config) -> CadBackend:
    if config.backend == "com":
        from autocad_mcp.cad.backends.com_backend import COMBackend
        return COMBackend(config)
    raise UnsupportedBackendError(
        f"Backend {config.backend!r} is not implemented; use 'com'. "
        "No CAD request was sent and no fallback was attempted."
    )
