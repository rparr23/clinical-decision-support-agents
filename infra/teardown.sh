#!/usr/bin/env bash
# Stop all charges at the end of a term: runtime, vector indexes, bucket and IAM stack.
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-1}"
BUCKET="${CDS_VECTOR_BUCKET:-clearpath-cds-vectors}"
STACK="${CDS_STACK:-ClearPathCdsInfra}"

agentcore destroy --force || echo "No AgentCore runtime to remove"
for INDEX in acr-guidelines-index respiratory-billing-index fhir-data-index; do
  aws s3vectors delete-index --vector-bucket-name "$BUCKET" --index-name "$INDEX" --region "$REGION" || true
done
aws s3vectors delete-vector-bucket --vector-bucket-name "$BUCKET" --region "$REGION" || true
aws cloudformation delete-stack --stack-name "$STACK" --region "$REGION"
aws cloudformation wait stack-delete-complete --stack-name "$STACK" --region "$REGION"
echo "Teardown complete."
