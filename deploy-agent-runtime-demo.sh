#!/bin/bash
set -e

# Configuration
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
  echo "Error: No active gcloud project found. Please run 'gcloud config set project <PROJECT_ID>'."
  exit 1
fi

AUTHZ_SERVICE_NAME="custom-authz-agent-gateway"
IMAGE_URI="us-central1-docker.pkg.dev/$PROJECT_ID/gateway-docker/$AUTHZ_SERVICE_NAME:latest"

echo "Using GCP Project: $PROJECT_ID"
echo "Using Region: $REGION"

# 1. Check if the gRPC extension is deployed in Cloud Run
if ! gcloud run services describe $AUTHZ_SERVICE_NAME --region $REGION --project $PROJECT_ID >/dev/null 2>&1; then
  echo "gRPC Extension Service ($AUTHZ_SERVICE_NAME) not found in Cloud Run. Building and deploying..."
  
  # Build the container image using Cloud Build
  gcloud builds submit --tag $IMAGE_URI custom-authz-service/ --project $PROJECT_ID
  
  # Deploy to Cloud Run
  gcloud run deploy $AUTHZ_SERVICE_NAME \
    --image $IMAGE_URI \
    --platform managed \
    --region $REGION \
    --no-allow-unauthenticated \
    --port 8080 \
    --project $PROJECT_ID
else
  echo "gRPC Extension Service ($AUTHZ_SERVICE_NAME) is already deployed in Cloud Run."
fi

# Get the deployed URL
AUTHZ_URL=$(gcloud run services describe $AUTHZ_SERVICE_NAME --region $REGION --project $PROJECT_ID --format='value(status.url)')
echo "gRPC Extension URL: $AUTHZ_URL"

# 2. Use agents-cli to deploy the agent in agent runtime
echo "Deploying custom-authz-demo-agent to Vertex AI Agent Runtime..."
cd agents/custom-authz-demo-agent

# Build virtual environment and sync dependencies
echo "Building virtual environment and syncing dependencies..."
uv venv
source .venv/bin/activate
uv sync
agents-cli install

# Ensure dependencies are installed and run deploy
agents-cli deploy --project $PROJECT_ID --region $REGION --no-confirm-project

# Extract reasoning engine ID
if [ -f "deployment_metadata.json" ]; then
  RE_ID=$(python3 -c "import json; d=json.load(open('deployment_metadata.json')); print(d['remote_agent_runtime_id'].split('/')[-1])")
  echo "Extracted Reasoning Engine ID: $RE_ID"
else
  echo "Error: deployment_metadata.json not found. Deploy may have failed."
  exit 1
fi

# 3. Wire up Terraform
echo "Wiring up Terraform for Ingress Gateway..."
cd ../../custom-authz-agent-runtime/terraform

# Initialize Terraform
terraform init

# Check if the Cloud Run resource is in the state; if not, import it
if ! terraform state show google_cloud_run_v2_service.agent_authz_gateway >/dev/null 2>&1; then
  echo "Importing Cloud Run service into Terraform state..."
  terraform import google_cloud_run_v2_service.agent_authz_gateway projects/$PROJECT_ID/locations/$REGION/services/$AUTHZ_SERVICE_NAME || true
fi

# Run terraform apply
terraform apply -auto-approve \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="service_name=$AUTHZ_SERVICE_NAME" \
  -var="container_image=$IMAGE_URI" \
  -var="agents={\"custom-authz-demo-agent\": {host=\"agw-ingress.agentgateway\", reasoning_engine_id=\"$RE_ID\", agent_project_id=\"$PROJECT_ID\", region=\"$REGION\"}}"

echo "Deployment complete for Agent Runtime demo!"
