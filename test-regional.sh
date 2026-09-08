#!/bin/bash
# ==============================================================================
# test-regional.sh - Test the Regional Load Balancer and Agent Backend
#
# Usage:
#   ./test-regional.sh [PROMPT] [LB_NAME] [REGION]
#
# Examples:
#   ./test-regional.sh
#   ./test-regional.sh "What is the weather in Fremont?" my-agent-lb us-central1
#   ./test-regional.sh "Calculate 45 * 12" custom-agent-regional-lb us-central1
# ==============================================================================

set -euo pipefail

# Parameters
PROMPT=${1:-"What is the weather in Fremont?"}
LB_NAME=${2:-"my-agent-lb"}
REGION=${3:-"us-central1"}

PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")
if [ -z "$PROJECT_ID" ]; then
  echo "Error: No active GCP project configured. Run 'gcloud config set project <PROJECT_ID>'."
  exit 1
fi

echo "=============================================================================="
echo " Testing Regional Agent Ingress Gateway via gcloud"
echo "=============================================================================="
echo " Project ID       : $PROJECT_ID"
echo " Region           : $REGION"
echo " Load Balancer    : $LB_NAME"
echo " Host Header      : ${LB_NAME}.example.com"
echo " Test Prompt      : \"$PROMPT\""
echo "=============================================================================="

# 1. Fetch Identity Token
echo "Fetching Google Identity Token..."
TOKEN=$(gcloud auth print-identity-token 2>/dev/null || echo "user-token-alice")

# 2. Fetch Regional Load Balancer IP
echo "Fetching Regional Load Balancer IP..."
LB_IP=$(gcloud compute addresses describe "${LB_NAME}-ip" --region "$REGION" --project "$PROJECT_ID" --format='value(address)' 2>/dev/null || echo "")

if [ -z "$LB_IP" ]; then
  LB_IP=$(gcloud compute forwarding-rules describe "${LB_NAME}-fwd-rule" --region "$REGION" --project "$PROJECT_ID" --format='value(IPAddress)' 2>/dev/null || echo "")
fi

if [ -z "$LB_IP" ]; then
  echo "Warning: Forwarding rule or address for '${LB_NAME}' not found in region '${REGION}'."
  echo "Listing active regional forwarding rules in ${REGION}..."
  LB_IP=$(gcloud compute forwarding-rules list --filter="region:($REGION)" --format='value(IP_ADDRESS)' --limit=1 2>/dev/null || echo "")
fi

if [ -z "$LB_IP" ]; then
  echo "Error: Could not retrieve Regional Load Balancer IP from gcloud."
  exit 1
fi

echo "Target Regional IP: $LB_IP"
echo "------------------------------------------------------------------------------"

# 3. Create a session on the Agent backend
echo "1. Creating new session on agent backend..."
SESSION_RESP=$(curl -k -s -X POST "https://${LB_IP}/apps/app/users/user-123/sessions" \
  -H "Host: ${LB_NAME}.example.com" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-agent-id: custom-authz-demo-agent" \
  -H "x-agent-tenant-id: finance-dept")

echo "Raw Session Response: $SESSION_RESP"

# Parse session ID (handling potential 'echo:' prefix added by the Service Extension)
SESSION_ID=$(python3 -c "
import json, sys
s = sys.stdin.read().strip()
if s.startswith('echo:'):
    s = s[5:].strip()
try:
    d = json.loads(s)
    print(d.get('id', ''))
except Exception:
    print('')
" <<< "$SESSION_RESP")

if [ -z "$SESSION_ID" ]; then
  echo "Error: Failed to parse session ID from response: $SESSION_RESP"
  exit 1
fi
echo "Created Session ID: $SESSION_ID"
echo "------------------------------------------------------------------------------"

# 4. Send test prompt to the Agent
echo "2. Sending test prompt to agent..."
PROMPT_JSON=$(python3 -c "
import json, sys
prompt = sys.argv[1]
session_id = sys.argv[2]
payload = {
    'appName': 'app',
    'userId': 'user-123',
    'sessionId': session_id,
    'newMessage': {
        'role': 'user',
        'parts': [{'text': prompt}]
    }
}
print(json.dumps(payload))
" "$PROMPT" "$SESSION_ID")

curl -k -X POST "https://${LB_IP}/run" \
  -H "Host: ${LB_NAME}.example.com" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-agent-id: custom-authz-demo-agent" \
  -H "x-agent-tenant-id: finance-dept" \
  -H "Content-Type: application/json" \
  -d "$PROMPT_JSON"

echo -e "\n=============================================================================="
echo " Test Request Completed successfully!"
echo "=============================================================================="
