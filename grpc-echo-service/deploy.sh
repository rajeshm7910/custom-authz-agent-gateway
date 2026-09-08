#!/bin/bash
set -e

# Configuration
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)

if [ -z "$PROJECT_ID" ]; then
  echo "Error: No active gcloud project found. Please run 'gcloud config set project <PROJECT_ID>'."
  exit 1
fi

SERVICE_NAME="grpc-echo-service"
IMAGE_URI="us-central1-docker.pkg.dev/$PROJECT_ID/gateway-docker/$SERVICE_NAME:latest"

echo "=================================================="
echo "Preparing to deploy gRPC Echo Service to Cloud Run:"
echo "GCP Project: $PROJECT_ID"
echo "Region:      $REGION"
echo "Service:     $SERVICE_NAME"
echo "Image URI:   $IMAGE_URI"
echo "=================================================="

# 1. Build and push container using Google Cloud Build
echo "Building and pushing container image via Cloud Build..."
gcloud builds submit --tag "$IMAGE_URI" . --project "$PROJECT_ID"

# 2. Deploy to Cloud Run with http2 and allow-unauthenticated
echo "Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE_URI" \
  --platform managed \
  --region "$REGION" \
  --use-http2 \
  --allow-unauthenticated \
  --port 8080 \
  --project "$PROJECT_ID"

# 3. Print access instructions
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')

echo "=================================================="
echo "Deployment successful!"
echo "Service URL: $SERVICE_URL"
echo "=================================================="
echo ""
echo "To test the deployed service, run:"
echo "python3 src/client.py 'Hello World' --server $SERVICE_URL"
echo "=================================================="
