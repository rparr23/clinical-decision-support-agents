"""Create the S3 Vectors bucket and indexes and load the bundled data (guidelines, billing, patients).

All three stores live in S3 Vectors, including the ACR guidelines, so nothing bills while idle
(PRD cost section). Embeddings: Titan Text Embeddings v2, 1024 dimensions, cosine distance.

    python infra/s3vectors_setup.py --region us-east-1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cds.config import get_settings  # noqa: E402
from cds.knowledge import data  # noqa: E402
from cds.knowledge.vectors import INDEXES  # noqa: E402


def records():
    for d in data.guideline_docs():
        yield "guidelines", d.id, d.text, {"text": d.text, "snippet": d.meta["snippet"], "source": d.meta["source"],
                                          "locator": d.meta["locator"], "kind": d.meta["kind"],
                                          **({"variant": d.meta["variant"]} if "variant" in d.meta else {})}
    for d in data.billing_docs():
        yield "billing", d.id, d.text, {"text": d.text, "item_json": json.dumps(d.meta["item"])}
    for p in data.patients().values():
        yield "patients", p.id, p.text(), {"text": p.text(), "sex": p.sex}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default=get_settings().region)
    ap.add_argument("--bucket", default=get_settings().vector_bucket)
    args = ap.parse_args()

    import boto3

    s3v = boto3.client("s3vectors", region_name=args.region)
    bedrock = boto3.client("bedrock-runtime", region_name=args.region)

    try:
        s3v.create_vector_bucket(vectorBucketName=args.bucket)
        print(f"Created vector bucket {args.bucket}")
    except s3v.exceptions.ConflictException:
        print(f"Vector bucket {args.bucket} exists")
    for index in INDEXES.values():
        try:
            s3v.create_index(vectorBucketName=args.bucket, indexName=index, dataType="float32", dimension=1024,
                             distanceMetric="cosine",
                             metadataConfiguration={"nonFilterableMetadataKeys": ["text", "snippet", "item_json"]})
            print(f"Created index {index}")
        except s3v.exceptions.ConflictException:
            print(f"Index {index} exists")

    batches: dict[str, list] = {k: [] for k in INDEXES}
    for name, key, text, meta in records():
        body = json.dumps({"inputText": text, "dimensions": 1024, "normalize": True})
        emb = json.loads(bedrock.invoke_model(modelId=get_settings().embed_model_id, body=body)["body"].read())
        batches[name].append({"key": key, "data": {"float32": emb["embedding"]}, "metadata": meta})
    for name, vecs in batches.items():
        for i in range(0, len(vecs), 100):
            s3v.put_vectors(vectorBucketName=args.bucket, indexName=INDEXES[name], vectors=vecs[i:i + 100])
        print(f"Loaded {len(vecs)} vectors into {INDEXES[name]}")
    print("Set CDS_VECTOR_BACKEND=s3vectors to use these indexes.")


if __name__ == "__main__":
    main()
