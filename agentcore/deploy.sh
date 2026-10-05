#!/usr/bin/env bash
# Deploy the supervisor to Amazon Bedrock AgentCore Runtime.
# Prerequisites: AWS credentials, Bedrock model access to Claude Sonnet 4.5 and Titan Text Embeddings v2,
# and `pip install -r requirements-aws.txt` (provides the agentcore CLI).
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-us-east-1}"
STACK="${CDS_STACK:-ClearPathCdsInfra}"
NAME="${CDS_RUNTIME_NAME:-clearpath_cds}"

echo "1/3 Deploying IAM role and S3 Vectors bucket (CloudFormation stack $STACK)..."
aws cloudformation deploy --stack-name "$STACK" --template-file infra/infrastructure.yaml \
  --capabilities CAPABILITY_NAMED_IAM --region "$REGION"
ROLE_ARN=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='AgentCoreRoleArn'].OutputValue" --output text)

echo "2/3 Building S3 Vectors indexes from the bundled data..."
python infra/s3vectors_setup.py --region "$REGION"

echo "3/3 Launching the AgentCore Runtime..."
rm -f .bedrock_agentcore.yaml
agentcore configure --entrypoint agentcore/agentcore_entry.py --name "$NAME" \
  --execution-role "$ROLE_ARN" --requirements-file agentcore/requirements.txt --region "$REGION" --non-interactive
agentcore launch --auto-update-on-conflict \
  --env CDS_MODE=bedrock --env CDS_VECTOR_BACKEND=s3vectors --env AWS_REGION="$REGION"

echo
echo "Done. Test it:"
echo "  agentcore invoke '{\"prompt\": \"Is a chest x-ray appropriate on hospital admission with no cardiopulmonary symptoms?\"}'"
echo "Point the web app at it:  CDS_MODE=agentcore CDS_AGENTCORE_ARN=<runtime arn> uvicorn app.server:app"
