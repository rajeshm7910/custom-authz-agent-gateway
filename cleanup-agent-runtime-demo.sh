#!/bin/bash
# cleanup-agent-runtime-demo.sh - Tear down Agent Runtime target demo infrastructure and services
set -e

# Configuration
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
  echo "Error: No active gcloud project found."
  exit 1
fi

AUTHZ_SERVICE_NAME="custom-authz-agent-gateway"
TF_DIR="custom-authz-agent-runtime/terraform"

echo "========================================="
echo "Cleaning up Agent Runtime Ingress Demo..."
echo "Project: $PROJECT_ID"
echo "========================================="

# 1. Run Terraform Destroy
if [ -d "$TF_DIR" ]; then
  echo "Running Terraform Destroy..."
  cd "$TF_DIR"
  terraform destroy -auto-approve \
    -var="project_id=$PROJECT_ID" \
    -var="region=$REGION" \
    -var="service_name=$AUTHZ_SERVICE_NAME" \
    -var="container_image=us-central1-docker.pkg.dev/$PROJECT_ID/gateway-docker/$AUTHZ_SERVICE_NAME:latest" \
    -var="agents={\"custom-authz-demo-agent\": {host=\"agw-ingress.agentgateway\", reasoning_engine_id=\"dummy-id\", agent_project_id=\"$PROJECT_ID\", region=\"$REGION\"}}" || true
  cd ../..
fi

# 2. Programmatically Delete the Deployed Reasoning Engine on Vertex AI
echo "Deleting Reasoning Engine from Vertex AI..."
python3 -c "
try:
    from google.cloud import aiplatform
    aiplatform.init(project='$PROJECT_ID', location='$REGION')
    engines = aiplatform.ReasoningEngine.list()
    found = False
    for engine in engines:
        if engine.display_name == 'custom-authz-demo-agent':
            print(f'Found Reasoning Engine {engine.resource_name} ({engine.display_name}). Deleting...')
            engine.delete()
            found = True
    if not found:
        print('No reasoning engine named custom-authz-demo-agent found.')
except Exception as e:
    print(f'Warning: Could not clean up reasoning engine via Python SDK: {e}')
"

# 3. Delete Cloud Run Service directly to ensure complete cleanup
if gcloud run services describe "$AUTHZ_SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "Deleting Authz Gateway Cloud Run Service ($AUTHZ_SERVICE_NAME)..."
  gcloud run services delete "$AUTHZ_SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --quiet
fi

# Clean up local deployment metadata
if [ -f "agents/custom-authz-demo-agent/deployment_metadata.json" ]; then
  # Check if deployment target was agent_runtime
  TARGET=$(python3 -c "import json; d=json.load(open('agents/custom-authz-demo-agent/deployment_metadata.json')); print(d.get('deployment_target', ''))" 2>/dev/null || echo "")
  if [ "$TARGET" = "agent_runtime" ]; then
    echo "Removing local deployment metadata..."
    rm "agents/custom-authz-demo-agent/deployment_metadata.json"
  fi
fi

echo "========================================="
echo "Agent Runtime Demo Cleanup Complete!"
echo "========================================="
