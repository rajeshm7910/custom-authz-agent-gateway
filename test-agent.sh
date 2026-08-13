#!/bin/bash
# test-agent.sh - Test the deployed agent through the gateway using curl

# Default values
PROMPT=${1:-"What is the weather in Fremont?"}
TARGET=${2:-"cloud-run"}

echo "========================================="
echo "Testing Agent Ingress Gateway"
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
  TF_DIR="custom-authz-agent-cloud-run/terraform"
  if [ ! -d "$TF_DIR" ]; then
    echo "Error: Directory $TF_DIR not found."
    exit 1
  fi
  
  echo "Fetching Load Balancer IP from Terraform..."
  LB_IP=$(cd "$TF_DIR" && terraform output -raw global_anycast_ip 2>/dev/null || echo "")
  
  if [ -z "$LB_IP" ]; then
    echo "Error: Could not retrieve global_anycast_ip from Terraform state. Is it deployed?"
    exit 1
  fi
  
  echo "Target Global Anycast IP: $LB_IP"
  
  echo "1. Creating new session on agent backend..."
  SESSION_RESP=$(curl -k -s -X POST "https://$LB_IP/apps/app/users/user-123/sessions" \
    -H "Host: agent.example.com" \
    -H "Authorization: Bearer $TOKEN" \
    -H "x-agent-id: custom-authz-demo-agent" \
    -H "x-agent-tenant-id: finance-dept")
    
  SESSION_ID=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(d.get('id', ''))" <<< "$SESSION_RESP")
  
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
  TF_DIR="custom-authz-agent-runtime/terraform"
  if [ ! -d "$TF_DIR" ]; then
    echo "Error: Directory $TF_DIR not found."
    exit 1
  fi
  
  echo "Fetching Load Balancer IP from Terraform..."
  LB_IP=$(cd "$TF_DIR" && terraform output -raw tier1_anycast_ip 2>/dev/null || echo "")
  
  if [ -z "$LB_IP" ]; then
    echo "Error: Could not retrieve tier1_anycast_ip from Terraform state. Is it deployed?"
    exit 1
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
