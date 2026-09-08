#!/bin/bash
# ==============================================================================
# cleanup-regional-lb.sh
#
# Deletes the Regional External Application Load Balancer, Service Extension,
# and associated networking components created by create-regional-lb.sh.
#
# Usage:
#   ./cleanup-regional-lb.sh [LB_NAME] [REGION]
# ==============================================================================

set -euo pipefail

LB_NAME="${1:-custom-agent-regional-lb}"
REGION="${2:-us-central1}"

PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")
if [ -z "$PROJECT_ID" ]; then
  echo "Error: No active GCP project configured."
  exit 1
fi

echo "=============================================================================="
echo " Tearing down Regional Load Balancer & Service Extension via gcloud"
echo "=============================================================================="
echo " Project ID         : $PROJECT_ID"
echo " Region             : $REGION"
echo " Load Balancer Name : $LB_NAME"
echo "=============================================================================="

# 1. Delete Service Extension
EXTENSION_NAME="${LB_NAME}-echo-extension"
if gcloud service-extensions lb-traffic-extensions describe "$EXTENSION_NAME" --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting Service Extension '$EXTENSION_NAME'..."
  gcloud service-extensions lb-traffic-extensions delete "$EXTENSION_NAME" --location="$REGION" --project="$PROJECT_ID" --quiet
fi

# 2. Delete Forwarding Rule
FWD_RULE_NAME="${LB_NAME}-fwd-rule"
if gcloud compute forwarding-rules describe "$FWD_RULE_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting Forwarding Rule '$FWD_RULE_NAME'..."
  gcloud compute forwarding-rules delete "$FWD_RULE_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

# 3. Delete Target HTTPS Proxy
TARGET_PROXY_NAME="${LB_NAME}-https-proxy"
if gcloud compute target-https-proxies describe "$TARGET_PROXY_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting Target HTTPS Proxy '$TARGET_PROXY_NAME'..."
  gcloud compute target-https-proxies delete "$TARGET_PROXY_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

# 4. Delete URL Map
URL_MAP_NAME="${LB_NAME}-url-map"
if gcloud compute url-maps describe "$URL_MAP_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting URL Map '$URL_MAP_NAME'..."
  gcloud compute url-maps delete "$URL_MAP_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

# 5. Delete SSL Certificate
SSL_CERT_NAME="${LB_NAME}-ssl-cert"
if gcloud compute ssl-certificates describe "$SSL_CERT_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting SSL Certificate '$SSL_CERT_NAME'..."
  gcloud compute ssl-certificates delete "$SSL_CERT_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

# 6. Delete Static IP Address
IP_NAME="${LB_NAME}-ip"
if gcloud compute addresses describe "$IP_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting Static IP '$IP_NAME'..."
  gcloud compute addresses delete "$IP_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

# 7. Delete Backend Services
AGENT_BACKEND_NAME="${LB_NAME}-agent-backend"
if gcloud compute backend-services describe "$AGENT_BACKEND_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting Agent Backend Service '$AGENT_BACKEND_NAME'..."
  gcloud compute backend-services delete "$AGENT_BACKEND_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

ECHO_BACKEND_NAME="${LB_NAME}-echo-backend"
if gcloud compute backend-services describe "$ECHO_BACKEND_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting Echo Backend Service '$ECHO_BACKEND_NAME'..."
  gcloud compute backend-services delete "$ECHO_BACKEND_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

# 8. Delete Serverless NEGs
AGENT_NEG_NAME="${LB_NAME}-agent-neg"
if gcloud compute network-endpoint-groups describe "$AGENT_NEG_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting Agent Serverless NEG '$AGENT_NEG_NAME'..."
  gcloud compute network-endpoint-groups delete "$AGENT_NEG_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

ECHO_NEG_NAME="${LB_NAME}-echo-neg"
if gcloud compute network-endpoint-groups describe "$ECHO_NEG_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting Echo Serverless NEG '$ECHO_NEG_NAME'..."
  gcloud compute network-endpoint-groups delete "$ECHO_NEG_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

# 9. Delete Proxy-Only Subnet if created specifically for this LB
PROXY_SUBNET_NAME="${LB_NAME}-proxy-subnet"
if gcloud compute networks subnets describe "$PROXY_SUBNET_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "--> Deleting Regional Proxy-Only Subnet '$PROXY_SUBNET_NAME'..."
  gcloud compute networks subnets delete "$PROXY_SUBNET_NAME" --region="$REGION" --project="$PROJECT_ID" --quiet
fi

echo "=============================================================================="
echo " Cleanup completed for Regional Load Balancer: $LB_NAME"
echo "=============================================================================="
