#!/bin/bash
set -e

# Configuration
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
  echo "Error: No active gcloud project found. Please run 'gcloud config set project <PROJECT_ID>'."
  exit 1
fi

AUTHZ_SERVICE_NAME="custom-authz-cloud-run"
BACKEND_SERVICE_NAME="custom-authz-demo-agent"
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

# 2. Deploy the agent to Cloud Run using agents-cli
echo "Deploying agent to Cloud Run..."
cd agents/custom-authz-demo-agent

# Deploy using agents-cli to Cloud Run
agents-cli deploy --deployment-target cloud_run --project $PROJECT_ID --region $REGION --service-name $BACKEND_SERVICE_NAME --no-confirm-project

# Get the backend container image URI
BACKEND_IMAGE_URI=$(gcloud run services describe $BACKEND_SERVICE_NAME --region $REGION --project $PROJECT_ID --format='value(spec.template.spec.containers[0].image)' 2>/dev/null || echo "us-central1-docker.pkg.dev/$PROJECT_ID/gateway-docker/$BACKEND_SERVICE_NAME:latest")

# 3. Wire up Terraform
echo "Wiring up Terraform for Cloud Run Ingress Gateway..."
cd ../../custom-authz-agent-cloud-run/terraform

# Initialize Terraform
terraform init

# Import existing Cloud Run services if not already in state
if ! terraform state show google_cloud_run_v2_service.agent_authz >/dev/null 2>&1; then
  echo "Importing Custom Authz Cloud Run service into Terraform state..."
  terraform import google_cloud_run_v2_service.agent_authz projects/$PROJECT_ID/locations/$REGION/services/$AUTHZ_SERVICE_NAME || true
fi

if ! terraform state show google_cloud_run_v2_service.adk_agent_backend >/dev/null 2>&1; then
  echo "Importing Backend Agent Cloud Run service into Terraform state..."
  terraform import google_cloud_run_v2_service.adk_agent_backend projects/$PROJECT_ID/locations/$REGION/services/$BACKEND_SERVICE_NAME || true
fi

# Run terraform apply
terraform apply -auto-approve \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="authz_service_name=$AUTHZ_SERVICE_NAME" \
  -var="authz_container_image=$IMAGE_URI" \
  -var="backend_service_name=$BACKEND_SERVICE_NAME" \
  -var="backend_container_image=$BACKEND_IMAGE_URI"

echo "Deployment complete for Cloud Run demo!"
