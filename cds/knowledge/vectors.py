"""Search backends. Local TF-IDF by default; Amazon S3 Vectors when CDS_VECTOR_BACKEND=s3vectors.

Both return the same shape: a list of (text, metadata, score) tuples, so tools do not
care where the vectors live. Index names match infra/s3vectors_setup.py.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from cds.config import get_settings
from cds.knowledge import data

INDEXES = {"guidelines": "acr-guidelines-index", "billing": "respiratory-billing-index", "patients": "fhir-data-index"}


def _local(name: str):
    return {"guidelines": data.guideline_index, "billing": data.billing_index, "patients": data.patient_index}[name]()


@lru_cache
def _clients():
    import boto3  # imported lazily so offline mode needs no AWS SDK

    s = get_settings()
    return boto3.client("bedrock-runtime", region_name=s.region), boto3.client("s3vectors", region_name=s.region)


def embed(text: str) -> list[float]:
    bedrock, _ = _clients()
    body = json.dumps({"inputText": text, "dimensions": 1024, "normalize": True})
    resp = bedrock.invoke_model(modelId=get_settings().embed_model_id, body=body)
    return json.loads(resp["body"].read())["embedding"]


def search(name: str, query: str, k: int = 5) -> list[tuple[str, dict[str, Any], float]]:
    s = get_settings()
    if s.vector_backend != "s3vectors":
        return [(d.text, d.meta | {"id": d.id}, score) for d, score in _local(name).search(query, k)]
    _, s3v = _clients()
    resp = s3v.query_vectors(vectorBucketName=s.vector_bucket, indexName=INDEXES[name],
                             queryVector={"float32": embed(query)}, topK=k, returnMetadata=True, returnDistance=True)
    out = []
    for v in resp.get("vectors", []):
        meta = v.get("metadata", {})
        out.append((meta.get("text", ""), meta | {"id": v.get("key")}, 1 - float(v.get("distance", 1.0))))
    return out
