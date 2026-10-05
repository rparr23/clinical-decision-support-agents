"""Runtime settings, all overridable with environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # offline: deterministic local agents, no AWS calls (default, used by tests and the classroom demo)
    # bedrock: Strands agents calling Claude on Amazon Bedrock from this process
    # agentcore: forward every question to a deployed AgentCore Runtime
    mode: str = field(default_factory=lambda: _env("CDS_MODE", "offline"))
    region: str = field(default_factory=lambda: _env("AWS_REGION", _env("AWS_DEFAULT_REGION", "us-east-1")))
    # One model version per release (PRD NFR-16)
    model_id: str = field(default_factory=lambda: _env("CDS_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"))
    embed_model_id: str = field(default_factory=lambda: _env("CDS_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0"))
    agentcore_arn: str = field(default_factory=lambda: _env("CDS_AGENTCORE_ARN", ""))
    # local: in-process TF-IDF index; s3vectors: Amazon S3 Vectors indexes built by infra/s3vectors_setup.py
    vector_backend: str = field(default_factory=lambda: _env("CDS_VECTOR_BACKEND", "local"))
    vector_bucket: str = field(default_factory=lambda: _env("CDS_VECTOR_BUCKET", "clearpath-cds-vectors"))
    # Answers below this retrieval score are refused (PRD FR-10)
    retrieval_threshold: float = field(default_factory=lambda: float(_env("CDS_RETRIEVAL_THRESHOLD", "0.12")))
    brand_name: str = field(default_factory=lambda: _env("CDS_BRAND_NAME", "ClearPath CDS"))
    feedback_path: Path = field(default_factory=lambda: Path(_env("CDS_FEEDBACK_PATH", "var/feedback.jsonl")))


def get_settings() -> Settings:
    return Settings()


DISCLAIMER = (
    "Decision support only, not medical advice. All patient records are synthetic and most fees are demo values. "
    "A licensed clinician must review every suggestion before acting on it."
)
