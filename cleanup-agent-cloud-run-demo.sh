#!/bin/bash
# cleanup-agent-cloud-run-demo.sh - Tear down Cloud Run target demo infrastructure and services
set -e

# Configuration
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
  echo "Error: No active gcloud project found."
  exit 1
fi

AUTHZ_SERVICE_NAME="custom-authz-cloud-run"
BACKEND_SERVICE_NAME="custom-authz-demo-agent"
TF_DIR="custom-authz-agent-cloud-run/terraform"

echo "========================================="
echo "Cleaning up Cloud Run Ingress Demo..."
echo "Project: $PROJECT_ID"
echo "========================================="

# 1. Run Terraform Destroy
if [ -d "$TF_DIR" ]; then
  echo "Running Terraform Destroy..."
  cd "$TF_DIR"
  terraform destroy -auto-approve \
    -var="project_id=$PROJECT_ID" \
    -var="region=$REGION" \
    -var="authz_service_name=$AUTHZ_SERVICE_NAME" \
    -var="authz_container_image=us-central1-docker.pkg.dev/$PROJECT_ID/gateway-docker/$AUTHZ_SERVICE_NAME:latest" \
    -var="backend_service_name=$BACKEND_SERVICE_NAME" \
    -var="backend_container_image=us-central1-docker.pkg.dev/$PROJECT_ID/gateway-docker/$BACKEND_SERVICE_NAME:latest" || true
  cd ../..
fi

# 2. Delete Cloud Run Services directly to ensure complete cleanup
echo "Checking for remaining Cloud Run services..."
if gcloud run services describe "$BACKEND_SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "Deleting Backend Agent Cloud Run Service ($BACKEND_SERVICE_NAME)..."
  gcloud run services delete "$BACKEND_SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --quiet
fi

if gcloud run services describe "$AUTHZ_SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "Deleting Authz Extension Cloud Run Service ($AUTHZ_SERVICE_NAME)..."
  gcloud run services delete "$AUTHZ_SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --quiet
fi

# Clean up local deployment metadata
if [ -f "agents/custom-authz-demo-agent/deployment_metadata.json" ]; then
  # Check if deployment target was cloud_run
  TARGET=$(python3 -c "import json; d=json.load(open('agents/custom-authz-demo-agent/deployment_metadata.json')); print(d.get('deployment_target', ''))" 2>/dev/null || echo "")
  if [ "$TARGET" = "cloud_run" ]; then
    echo "Removing local deployment metadata..."
    rm "agents/custom-authz-demo-agent/deployment_metadata.json"
  fi
fi

echo "========================================="
echo "Cloud Run Demo Cleanup Complete!"
echo "========================================="
