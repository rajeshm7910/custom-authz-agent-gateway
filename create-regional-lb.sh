#!/bin/bash
# ==============================================================================
# create-regional-lb.sh
#
# Creates a GCP Regional External Application Load Balancer (EXTERNAL_MANAGED)
# frontending an Agent deployed on Cloud Run, and attaches a gRPC Echo Service
# as a Service Extension (LB Traffic Extension) using ONLY gcloud commands.
#
# Usage:
#   ./create-regional-lb.sh [LB_NAME] [REGION] [NETWORK]
#
# Examples:
#   ./create-regional-lb.sh
#   ./create-regional-lb.sh my-agent-lb
#   ./create-regional-lb.sh my-agent-lb us-central1 default
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# 1. Inputs & Default Configurations
# ------------------------------------------------------------------------------
LB_NAME="${1:-custom-agent-regional-lb}"
REGION="${2:-us-central1}"
NETWORK="${3:-default}"

PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")
if [ -z "$PROJECT_ID" ]; then
  echo "Error: No active GCP project configured. Run 'gcloud config set project <PROJECT_ID>'."
  exit 1
fi

AGENT_SERVICE_NAME="custom-authz-demo-agent"
AGENT_IMAGE_URI="us-central1-docker.pkg.dev/${PROJECT_ID}/gateway-docker/${AGENT_SERVICE_NAME}:latest"

ECHO_SERVICE_NAME="grpc-echo-service"
ECHO_IMAGE_URI="us-central1-docker.pkg.dev/${PROJECT_ID}/gateway-docker/${ECHO_SERVICE_NAME}:latest"

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "=============================================================================="
echo " Starting Regional Load Balancer Setup via gcloud"
echo "=============================================================================="
echo " Project ID           : $PROJECT_ID"
echo " Region               : $REGION"
echo " Network              : $NETWORK"
echo " Load Balancer Name   : $LB_NAME"
echo " Agent Service Name   : $AGENT_SERVICE_NAME"
echo " Echo Service Name    : $ECHO_SERVICE_NAME"
echo "=============================================================================="

# ------------------------------------------------------------------------------
# 2. Verify / Deploy Agent on Cloud Run
# ------------------------------------------------------------------------------
echo -e "\n[Step 1/8] Verifying Agent Service in Cloud Run ($AGENT_SERVICE_NAME)..."
if ! gcloud run services describe "$AGENT_SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Agent service '$AGENT_SERVICE_NAME' not found in $REGION. Deploying to Cloud Run..."
  
  if [ -d "agents/custom-authz-demo-agent" ]; then
    echo "--> Building Agent container image via Cloud Build..."
    gcloud builds submit --tag "$AGENT_IMAGE_URI" agents/custom-authz-demo-agent/ --project "$PROJECT_ID"
  else
    echo "Error: Directory 'agents/custom-authz-demo-agent' not found to build image."
    exit 1
  fi

  echo "--> Deploying '$AGENT_SERVICE_NAME' to Cloud Run..."
  gcloud run deploy "$AGENT_SERVICE_NAME" \
    --image "$AGENT_IMAGE_URI" \
    --platform managed \
    --region "$REGION" \
    --no-allow-unauthenticated \
    --port 8080 \
    --project "$PROJECT_ID"
else
  echo "--> Agent service '$AGENT_SERVICE_NAME' is already deployed."
fi

# ------------------------------------------------------------------------------
# 3. Verify / Deploy Echo Service on Cloud Run
# ------------------------------------------------------------------------------
echo -e "\n[Step 2/8] Verifying gRPC Echo Service in Cloud Run ($ECHO_SERVICE_NAME)..."
if ! gcloud run services describe "$ECHO_SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Echo service '$ECHO_SERVICE_NAME' not found in $REGION. Deploying to Cloud Run..."
  
  if [ -d "grpc-echo-service" ]; then
    echo "--> Building Echo container image via Cloud Build..."
    gcloud builds submit --tag "$ECHO_IMAGE_URI" grpc-echo-service/ --project "$PROJECT_ID"
  else
    echo "Error: Directory 'grpc-echo-service' not found to build image."
    exit 1
  fi

  echo "--> Deploying '$ECHO_SERVICE_NAME' to Cloud Run (with HTTP/2 enabled)..."
  gcloud run deploy "$ECHO_SERVICE_NAME" \
    --image "$ECHO_IMAGE_URI" \
    --platform managed \
    --region "$REGION" \
    --use-http2 \
    --allow-unauthenticated \
    --port 8080 \
    --project "$PROJECT_ID"
else
  echo "--> Echo service '$ECHO_SERVICE_NAME' is already deployed."
fi

ECHO_URL=$(gcloud run services describe "$ECHO_SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')
ECHO_HOST=$(echo "$ECHO_URL" | sed -e 's|^https://||' -e 's|/$||')
echo "--> Echo Service Authority/Host: $ECHO_HOST"

# ------------------------------------------------------------------------------
# 4. Configure Regional Proxy-Only Subnet (Required for Regional Envoy ALB)
# ------------------------------------------------------------------------------
echo -e "\n[Step 3/8] Checking for Regional Proxy-Only Subnet in region '$REGION'..."
EXISTING_PROXY_SUBNET=$(gcloud compute networks subnets list \
  --filter="region:($REGION) AND purpose:(REGIONAL_MANAGED_PROXY) AND network:($NETWORK)" \
  --format='value(name)' --project "$PROJECT_ID" 2>/dev/null || echo "")

if [ -z "$EXISTING_PROXY_SUBNET" ]; then
  PROXY_SUBNET_NAME="${LB_NAME}-proxy-subnet"
  echo "--> Creating Regional Proxy-Only Subnet '$PROXY_SUBNET_NAME'..."

  # In auto-mode VPC networks, custom subnets must be outside 10.128.0.0/9.
  # We try common non-overlapping ranges (10.0.0.0/23, 10.1.0.0/23, 172.16.0.0/23)
  SUBNET_CREATED=false
  for CIDR_CANDIDATE in "10.0.0.0/23" "10.1.0.0/23" "172.16.0.0/23" "192.168.100.0/23"; do
    if gcloud compute networks subnets create "$PROXY_SUBNET_NAME" \
        --purpose=REGIONAL_MANAGED_PROXY \
        --role=ACTIVE \
        --region="$REGION" \
        --network="$NETWORK" \
        --range="$CIDR_CANDIDATE" \
        --project="$PROJECT_ID" 2>/dev/null; then
      echo "--> Successfully created Regional Proxy-Only Subnet with CIDR $CIDR_CANDIDATE"
      SUBNET_CREATED=true
      break
    fi
  done

  if [ "$SUBNET_CREATED" = false ]; then
    echo "Error: Failed to create Regional Proxy-Only Subnet with standard non-overlapping CIDR blocks."
    exit 1
  fi
else
  echo "--> Found existing Regional Proxy-Only Subnet: $EXISTING_PROXY_SUBNET"
fi

# ------------------------------------------------------------------------------
# 5. Create Serverless NEGs
# ------------------------------------------------------------------------------
echo -e "\n[Step 4/8] Configuring Serverless Network Endpoint Groups (NEGs)..."
AGENT_NEG_NAME="${LB_NAME}-agent-neg"
if ! gcloud compute network-endpoint-groups describe "$AGENT_NEG_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Creating Serverless NEG for Agent: $AGENT_NEG_NAME"
  gcloud compute network-endpoint-groups create "$AGENT_NEG_NAME" \
    --region="$REGION" \
    --network-endpoint-type=serverless \
    --cloud-run-service="$AGENT_SERVICE_NAME" \
    --project="$PROJECT_ID"
else
  echo "--> Serverless NEG '$AGENT_NEG_NAME' already exists."
fi

ECHO_NEG_NAME="${LB_NAME}-echo-neg"
if ! gcloud compute network-endpoint-groups describe "$ECHO_NEG_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Creating Serverless NEG for Echo Service: $ECHO_NEG_NAME"
  gcloud compute network-endpoint-groups create "$ECHO_NEG_NAME" \
    --region="$REGION" \
    --network-endpoint-type=serverless \
    --cloud-run-service="$ECHO_SERVICE_NAME" \
    --project="$PROJECT_ID"
else
  echo "--> Serverless NEG '$ECHO_NEG_NAME' already exists."
fi

# ------------------------------------------------------------------------------
# 6. Create Regional Backend Services
# ------------------------------------------------------------------------------
echo -e "\n[Step 5/8] Configuring Regional Backend Services..."
AGENT_BACKEND_NAME="${LB_NAME}-agent-backend"
if ! gcloud compute backend-services describe "$AGENT_BACKEND_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Creating Agent Regional Backend Service: $AGENT_BACKEND_NAME"
  gcloud compute backend-services create "$AGENT_BACKEND_NAME" \
    --region="$REGION" \
    --load-balancing-scheme=EXTERNAL_MANAGED \
    --protocol=HTTPS \
    --project="$PROJECT_ID"

  echo "--> Attaching Agent NEG to Backend Service..."
  gcloud compute backend-services add-backend "$AGENT_BACKEND_NAME" \
    --region="$REGION" \
    --network-endpoint-group="$AGENT_NEG_NAME" \
    --network-endpoint-group-region="$REGION" \
    --project="$PROJECT_ID"
else
  echo "--> Agent Regional Backend Service '$AGENT_BACKEND_NAME' already exists."
fi

ECHO_BACKEND_NAME="${LB_NAME}-echo-backend"
if ! gcloud compute backend-services describe "$ECHO_BACKEND_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Creating Echo Service Regional Backend Service (HTTP2/gRPC): $ECHO_BACKEND_NAME"
  gcloud compute backend-services create "$ECHO_BACKEND_NAME" \
    --region="$REGION" \
    --load-balancing-scheme=EXTERNAL_MANAGED \
    --protocol=HTTP2 \
    --project="$PROJECT_ID"

  echo "--> Attaching Echo NEG to Backend Service..."
  gcloud compute backend-services add-backend "$ECHO_BACKEND_NAME" \
    --region="$REGION" \
    --network-endpoint-group="$ECHO_NEG_NAME" \
    --network-endpoint-group-region="$REGION" \
    --project="$PROJECT_ID"
else
  echo "--> Echo Service Regional Backend Service '$ECHO_BACKEND_NAME' already exists."
fi

# ------------------------------------------------------------------------------
# 7. Create Regional Static IP, SSL Certificate, URL Map, Proxy & Forwarding Rule
# ------------------------------------------------------------------------------
echo -e "\n[Step 6/8] Creating Regional Load Balancer Frontend components..."

# Static IP
IP_NAME="${LB_NAME}-ip"
if ! gcloud compute addresses describe "$IP_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Reserving Regional Static IP Address: $IP_NAME"
  gcloud compute addresses create "$IP_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID"
else
  echo "--> Regional Static IP '$IP_NAME' already exists."
fi
LB_IP=$(gcloud compute addresses describe "$IP_NAME" --region "$REGION" --project "$PROJECT_ID" --format='value(address)')

# Regional SSL Certificate
SSL_CERT_NAME="${LB_NAME}-ssl-cert"
if ! gcloud compute ssl-certificates describe "$SSL_CERT_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Generating self-signed SSL Certificate for $LB_NAME..."
  CERT_KEY="$TEMP_DIR/key.pem"
  CERT_FILE="$TEMP_DIR/cert.pem"
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$CERT_KEY" \
    -out "$CERT_FILE" \
    -subj "/CN=${LB_NAME}.example.com"

  echo "--> Uploading Regional SSL Certificate resource '$SSL_CERT_NAME'..."
  gcloud compute ssl-certificates create "$SSL_CERT_NAME" \
    --certificate="$CERT_FILE" \
    --private-key="$CERT_KEY" \
    --region="$REGION" \
    --project="$PROJECT_ID"
else
  echo "--> Regional SSL Certificate '$SSL_CERT_NAME' already exists."
fi

# Regional URL Map
URL_MAP_NAME="${LB_NAME}-url-map"
if ! gcloud compute url-maps describe "$URL_MAP_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Creating Regional URL Map: $URL_MAP_NAME"
  gcloud compute url-maps create "$URL_MAP_NAME" \
    --region="$REGION" \
    --default-service="$AGENT_BACKEND_NAME" \
    --project="$PROJECT_ID"
else
  echo "--> Regional URL Map '$URL_MAP_NAME' already exists."
fi

# Regional Target HTTPS Proxy
TARGET_PROXY_NAME="${LB_NAME}-https-proxy"
if ! gcloud compute target-https-proxies describe "$TARGET_PROXY_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Creating Regional Target HTTPS Proxy: $TARGET_PROXY_NAME"
  gcloud compute target-https-proxies create "$TARGET_PROXY_NAME" \
    --region="$REGION" \
    --url-map="$URL_MAP_NAME" \
    --ssl-certificates="$SSL_CERT_NAME" \
    --project="$PROJECT_ID"
else
  echo "--> Regional Target HTTPS Proxy '$TARGET_PROXY_NAME' already exists."
fi

# Regional Forwarding Rule
FWD_RULE_NAME="${LB_NAME}-fwd-rule"
if ! gcloud compute forwarding-rules describe "$FWD_RULE_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Creating Regional Forwarding Rule: $FWD_RULE_NAME"
  gcloud compute forwarding-rules create "$FWD_RULE_NAME" \
    --region="$REGION" \
    --load-balancing-scheme=EXTERNAL_MANAGED \
    --network="$NETWORK" \
    --address="$IP_NAME" \
    --ports=443 \
    --target-https-proxy="$TARGET_PROXY_NAME" \
    --target-https-proxy-region="$REGION" \
    --project="$PROJECT_ID"
else
  echo "--> Regional Forwarding Rule '$FWD_RULE_NAME' already exists."
fi

# ------------------------------------------------------------------------------
# 8. Attach Echo Service Extension (LB Traffic Extension)
# ------------------------------------------------------------------------------
echo -e "\n[Step 7/8] Configuring and Attaching Service Extension (LB Traffic Extension)..."
EXTENSION_NAME="${LB_NAME}-echo-extension"
EXTENSION_MANIFEST="$TEMP_DIR/traffic-ext.yaml"

cat <<EOF > "$EXTENSION_MANIFEST"
name: projects/${PROJECT_ID}/locations/${REGION}/lbTrafficExtensions/${EXTENSION_NAME}
loadBalancingScheme: EXTERNAL_MANAGED
forwardingRules:
  - https://www.googleapis.com/compute/v1/projects/${PROJECT_ID}/regions/${REGION}/forwardingRules/${FWD_RULE_NAME}
extensionChains:
  - name: "grpc-echo-chain"
    matchCondition:
      celExpression: "true"
    extensions:
      - name: "grpc-echo-proc"
        authority: "${ECHO_HOST}"
        service: "https://www.googleapis.com/compute/v1/projects/${PROJECT_ID}/regions/${REGION}/backendServices/${ECHO_BACKEND_NAME}"
        timeout: 2.0s
        failOpen: false
        supportedEvents:
          - REQUEST_HEADERS
          - REQUEST_BODY
          - RESPONSE_HEADERS
          - RESPONSE_BODY
EOF

echo "--> Importing Service Extension '$EXTENSION_NAME' into location '$REGION'..."
gcloud service-extensions lb-traffic-extensions import "$EXTENSION_NAME" \
  --source="$EXTENSION_MANIFEST" \
  --location="$REGION" \
  --project="$PROJECT_ID"

# ------------------------------------------------------------------------------
# 9. Completion & Instructions
# ------------------------------------------------------------------------------
echo -e "\n[Step 8/8] Deployment Complete!"
echo "=============================================================================="
echo " Regional Load Balancer Configuration Summary"
echo "=============================================================================="
echo " Project ID            : $PROJECT_ID"
echo " Region                : $REGION"
echo " Load Balancer Name    : $LB_NAME"
echo " Assigned Static IP    : $LB_IP"
echo " Forwarding Rule       : $FWD_RULE_NAME"
echo " Agent Backend Service : $AGENT_BACKEND_NAME"
echo " Echo Traffic Ext      : $EXTENSION_NAME"
echo "=============================================================================="
echo ""
echo "To test your Regional Load Balancer with curl:"
echo ""
echo "  TOKEN=\$(gcloud auth print-identity-token)"
echo ""
echo "  # 1. Create a session on the Agent:"
echo "  SESSION_RESP=\$(curl -k -s -X POST \"https://${LB_IP}/apps/app/users/user-123/sessions\" \\"
echo "    -H \"Host: ${LB_NAME}.example.com\" \\"
echo "    -H \"Authorization: Bearer \$TOKEN\" \\"
echo "    -H \"x-agent-id: custom-authz-demo-agent\" \\"
echo "    -H \"x-agent-tenant-id: finance-dept\")"
echo "  echo \"Session Response: \$SESSION_RESP\""
echo ""
echo "  # 2. Run agent prompt:"
echo "  curl -k -X POST \"https://${LB_IP}/run\" \\"
echo "    -H \"Host: ${LB_NAME}.example.com\" \\"
echo "    -H \"Authorization: Bearer \$TOKEN\" \\"
echo "    -H \"Content-Type: application/json\" \\"
echo "    -d '{\"appName\":\"app\",\"userId\":\"user-123\",\"sessionId\":\"session-123\",\"newMessage\":{\"role\":\"user\",\"parts\":[{\"text\":\"Hello Agent\"}]}}'"
echo ""
echo "=============================================================================="
