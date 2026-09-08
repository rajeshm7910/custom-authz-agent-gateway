#!/bin/bash
# test-agent.sh - Test the deployed agent through the gateway using curl

# Default values
PROMPT=${1:-"What is the weather in Fremont?"}
TARGET=${2:-"cloud-run"}

echo "========================================="
echo "Testing Agent Ingress Gateway via gcloud"
echo "Target Platform : $TARGET"
echo "Test Prompt     : \"$PROMPT\""
echo "========================================="

# Fetch a valid token based on the target platform
if [ "$TARGET" = "runtime" ]; then
  TOKEN=$(gcloud auth print-access-token 2>/dev/null || echo "access-token-fallback")
else
  TOKEN=$(gcloud auth print-identity-token 2>/dev/null || echo "user-token-alice")
fi

if [ "$TARGET" = "cloud-run" ]; then
  echo "Fetching Load Balancer IP from gcloud..."
  LB_IP=$(gcloud compute forwarding-rules describe custom-authz-demo-agent-https-fwd-rule --global --format='value(IPAddress)' 2>/dev/null || echo "")
  
  if [ -z "$LB_IP" ]; then
    echo "Warning: forwarding rule custom-authz-demo-agent-https-fwd-rule not found. Listing active forwarding rules..."
    LB_IP=$(gcloud compute forwarding-rules list --limit=1 --format='value(IP_ADDRESS)' 2>/dev/null || echo "")
  fi

  if [ -z "$LB_IP" ]; then
    echo "Error: Could not retrieve global forwarding rule IP from gcloud. Falling back to active gRPC anycast IP: 107.178.242.66"
    LB_IP="107.178.242.66"
  fi
  
  echo "Target Global Anycast IP: $LB_IP"
  
  echo "1. Creating new session on agent backend..."
  SESSION_RESP=$(curl -k -s -X POST "https://$LB_IP/apps/app/users/user-123/sessions" \
    -H "Host: agent.example.com" \
    -H "Authorization: Bearer $TOKEN" \
    -H "x-agent-id: custom-authz-demo-agent" \
    -H "x-agent-tenant-id: finance-dept")
    
  SESSION_ID=$(python3 -c "import json, sys; s=sys.stdin.read().strip(); s=s[5:].strip() if s.startswith('echo:') else s; d=json.loads(s); print(d.get('id', ''))" <<< "$SESSION_RESP")
  
  if [ -z "$SESSION_ID" ]; then
    echo "Error: Failed to create session. Response: $SESSION_RESP"
    exit 1
  fi
  echo "Created Session ID: $SESSION_ID"
  
  echo -e "\n2. Sending test prompt to agent..."
  curl -k -X POST "https://$LB_IP/run" \
    -H "Host: agent.example.com" \
    -H "Authorization: Bearer $TOKEN" \
    -H "x-agent-id: custom-authz-demo-agent" \
    -H "x-agent-tenant-id: finance-dept" \
    -H "Content-Type: application/json" \
    -d "{\"appName\": \"app\", \"userId\": \"user-123\", \"sessionId\": \"$SESSION_ID\", \"newMessage\": {\"role\": \"user\", \"parts\": [{\"text\": \"$PROMPT\"}]}}"
    
elif [ "$TARGET" = "runtime" ]; then
  echo "Fetching Load Balancer IP from gcloud..."
  LB_IP=$(gcloud compute forwarding-rules list --filter="name:agw-ingress*" --format='value(IP_ADDRESS)' --limit=1 2>/dev/null || echo "")
  
  if [ -z "$LB_IP" ]; then
    echo "Warning: agw-ingress forwarding rule not found. Listing active forwarding rules..."
    LB_IP=$(gcloud compute forwarding-rules list --limit=1 --format='value(IP_ADDRESS)' 2>/dev/null || echo "")
  fi

  if [ -z "$LB_IP" ]; then
    echo "Error: Could not retrieve forwarding rule IP from gcloud. Falling back to active gRPC anycast IP: 107.178.242.66"
    LB_IP="107.178.242.66"
  fi
  
  echo "Target Global Anycast IP: $LB_IP"
  echo "Sending HTTPS Request to Ingress Gateway REST proxy..."
  
  # Perform request to HTTP REST Proxy route on the gateway
  curl -k -X POST "https://$LB_IP/streamQuery" \
    -H "Host: agw-ingress.agentgateway" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"class_method\": \"streaming_agent_run_with_events\", \"input\": {\"request_json\": \"{\\\"user_id\\\": \\\"user-123\\\", \\\"session_id\\\": \\\"session-123\\\", \\\"message\\\": {\\\"role\\\": \\\"user\\\", \\\"parts\\\": [{\\\"text\\\": \\\"$PROMPT\\\"}]}}\"}}"

else
  echo "Error: Unknown target '$TARGET'. Use 'cloud-run' or 'runtime'."
  exit 1
fi

echo -e "\n========================================="
echo "Test Request Sent."
echo "========================================="
