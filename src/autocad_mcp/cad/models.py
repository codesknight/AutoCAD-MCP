"""Version-one CAD Bridge job envelope; independent of the MCP transport."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, model_validator

class BridgeError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    outcome: str = "not_executed"
    failed_operation_id: str | None = None

class BridgeJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str
    request_id: str
    status: Literal["queued", "running", "succeeded", "failed", "rolled_back", "cancelled", "outcome_unknown"]
    document_id: str | None = None
    revision: int | None = None
    result: Any = None
    error: BridgeError | None = None
    metrics: dict[str, float] | None = None

    @model_validator(mode="after")
    def valid_terminal(self):
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("Successful jobs cannot contain an error")
        if self.status in {"failed", "rolled_back", "outcome_unknown", "cancelled"} and self.error is None:
            raise ValueError("Unsuccessful jobs must explain the outcome")
        return self
