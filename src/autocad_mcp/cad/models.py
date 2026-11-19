"""Version-one CAD Bridge job envelope; independent of the MCP transport."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

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

class DrawingUnits(BaseModel):
    code: int = Field(ge=0)
    name: str

class SavedArtifactInfo(BaseModel):
    artifact_id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    saved_revision: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(gt=0)
    saved_at: str
    units_code: int = Field(ge=0)
    state: Literal["saved"]

class WorkingDocumentInfo(BaseModel):
    document_id: str = Field(min_length=1)
    name: str
    revision: int = Field(ge=0)
    units: DrawingUnits
    managed: bool
    read_only: bool
    output_directory: str | None = None
    source_artifact_id: str | None = None
    artifact: SavedArtifactInfo | None = None
    model_space_count: int | None = Field(default=None,ge=0)
    layer_names: list[str] | None = None
    text_style_names: list[str] | None = None
    catalogs_truncated: bool = False
    @model_validator(mode="after")
    def consistent_permissions(self):
        if self.managed == self.read_only:
            raise ValueError("Bridge read_only must be the inverse of managed")
        return self

class WorkingDocumentJob(BridgeJob):
    result: WorkingDocumentInfo
    @model_validator(mode="after")
    def consistent_document(self):
        if self.status != "succeeded" or self.document_id != self.result.document_id or self.revision != self.result.revision:
            raise ValueError("Working document identity/revision must match the job")
        return self

class SavedArtifactJob(BridgeJob):
    result: SavedArtifactInfo
    @model_validator(mode="after")
    def consistent_source(self):
        if self.status != "succeeded" or self.document_id != self.result.source_document_id:
            raise ValueError("Saved artifact must belong to the job document")
        return self
