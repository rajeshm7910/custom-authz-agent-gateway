# Regional External Application Load Balancer & Service Extension Guide

This guide documents the architecture, automated and manual deployment steps, testing methodology, and teardown procedures for frontending a **Cloud Run AI Agent** with a **GCP Regional External Application Load Balancer (EXTERNAL_MANAGED)** and attaching a **gRPC Service Extension (`ext_proc`)** using pure `gcloud` CLI commands.

---

## 1. Architecture Overview

```mermaid
graph TD
    Client["Client / Application"] -->|HTTPS (Port 443)| RegALB["Regional External ALB (EXTERNAL_MANAGED)"]
    
    subgraph "Regional Envoy Ingress (VPC)"
        RegALB --> ProxySubnet["Proxy-Only Subnet (REGIONAL_MANAGED_PROXY)"]
        RegALB --> RegUrlMap["Regional URL Map & Target HTTPS Proxy"]
    end

    subgraph "Service Extension Callout"
        RegALB -->|gRPC ext_proc (HTTP/2)| EchoNEG["Echo Service Serverless NEG"]
        EchoNEG --> EchoRun["grpc-echo-service (Cloud Run)"]
        EchoRun -.->|Inspect / Mutate / Allow / Deny| RegALB
    end

    subgraph "Agent Backend Execution"
        RegALB -->|HTTPS Forwarding| AgentNEG["Agent Backend Serverless NEG"]
        AgentNEG --> AgentRun["custom-authz-demo-agent (Cloud Run)"]
    end
```

### Key Components

1. **Proxy-Only Subnet**: A dedicated regional subnetwork with purpose `REGIONAL_MANAGED_PROXY` required by Envoy-based Regional External Application Load Balancers.
2. **Serverless NEGs**: Regional Network Endpoint Groups routing traffic directly to Cloud Run services without managing VM instances.
3. **Regional Backend Services**:
   - **Agent Backend**: Protocol `HTTPS` targeting the ReAct Agent on Cloud Run.
   - **Echo Callout Backend**: Protocol `HTTP2` targeting the gRPC `ext_proc` Service Extension on Cloud Run.
4. **Regional LB Frontend**: Regional Static IP address, Regional Self-Signed SSL Certificate, Regional URL Map, Regional Target HTTPS Proxy, and Regional Forwarding Rule (Port 443).
5. **LB Traffic Extension (`lbTrafficExtensions`)**: Regional Service Extension resource that intercepts `REQUEST_HEADERS`, `REQUEST_BODY`, `RESPONSE_HEADERS`, and `RESPONSE_BODY` in the data path.

---

## 2. Prerequisites & Permissions

### Required APIs
Ensure the following Google Cloud APIs are enabled on your project:
```bash
gcloud services enable \
  compute.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  networkservices.googleapis.com
```

### Required IAM Roles
* **Compute Load Balancer Admin** (`roles/compute.loadBalancerAdmin`)
* **Compute Network Admin** (`roles/compute.networkAdmin`)
* **Compute Security Admin** (`roles/compute.securityAdmin`)
* **Service Extensions Admin** (`roles/networkservices.serviceExtensionsAdmin`)
* **Cloud Run Admin / Developer** (`roles/run.admin` or `roles/run.developer`)

---

## 3. Automated Deployment

Use [`create-regional-lb.sh`](file:///Users/rajeshmi/projects/custom-authz-agent-gateway/create-regional-lb.sh) to automatically build, deploy, and wire up all components:

```bash
# Make script executable
chmod +x create-regional-lb.sh

# Deploy with custom load balancer name, region, and network:
./create-regional-lb.sh [LB_NAME] [REGION] [NETWORK]

# Example:
./create-regional-lb.sh my-agent-lb us-central1 default
```

### What the script handles automatically:
1. Verifies if `custom-authz-demo-agent` is deployed to Cloud Run; if not, builds and deploys it.
2. Verifies if `grpc-echo-service` is deployed to Cloud Run (with HTTP/2 enabled); if not, builds and deploys it.
3. Automatically creates an active **Regional Proxy-Only Subnet** with a safe, non-overlapping CIDR range outside `10.128.0.0/9`.
4. Creates Regional Serverless NEGs for both services.
5. Configures Regional Backend Services with protocol mapping (`HTTPS` for Agent, `HTTP2` for gRPC Extension).
6. Provisions a Regional Static IP, generates a Regional SSL Certificate, and configures URL Map, Target HTTPS Proxy, and Forwarding Rule.
7. Generates the Service Extension YAML manifest and imports it via `gcloud service-extensions lb-traffic-extensions import`.

---

## 4. Step-by-Step Manual `gcloud` Commands

If you prefer to run the commands manually:

### Step 4.1: Deploy Cloud Run Services

```bash
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"

# 1. Deploy Agent Service
gcloud builds submit --tag "us-central1-docker.pkg.dev/${PROJECT_ID}/gateway-docker/custom-authz-demo-agent:latest" agents/custom-authz-demo-agent/
gcloud run deploy custom-authz-demo-agent \
  --image "us-central1-docker.pkg.dev/${PROJECT_ID}/gateway-docker/custom-authz-demo-agent:latest" \
  --platform managed \
  --region "${REGION}" \
  --no-allow-unauthenticated \
  --port 8080

# 2. Deploy gRPC Echo Service (HTTP/2 enabled)
gcloud builds submit --tag "us-central1-docker.pkg.dev/${PROJECT_ID}/gateway-docker/grpc-echo-service:latest" grpc-echo-service/
gcloud run deploy grpc-echo-service \
  --image "us-central1-docker.pkg.dev/${PROJECT_ID}/gateway-docker/grpc-echo-service:latest" \
  --platform managed \
  --region "${REGION}" \
  --use-http2 \
  --allow-unauthenticated \
  --port 8080
```

### Step 4.2: Create Regional Proxy-Only Subnet

```bash
gcloud compute networks subnets create my-agent-lb-proxy-subnet \
  --purpose=REGIONAL_MANAGED_PROXY \
  --role=ACTIVE \
  --region="${REGION}" \
  --network=default \
  --range="10.0.0.0/23"
```

### Step 4.3: Create Serverless NEGs

```bash
# Agent NEG
gcloud compute network-endpoint-groups create my-agent-lb-agent-neg \
  --region="${REGION}" \
  --network-endpoint-type=serverless \
  --cloud-run-service=custom-authz-demo-agent

# Echo Service NEG
gcloud compute network-endpoint-groups create my-agent-lb-echo-neg \
  --region="${REGION}" \
  --network-endpoint-type=serverless \
  --cloud-run-service=grpc-echo-service
```

### Step 4.4: Create Regional Backend Services

```bash
# Agent Backend Service (HTTPS)
gcloud compute backend-services create my-agent-lb-agent-backend \
  --region="${REGION}" \
  --load-balancing-scheme=EXTERNAL_MANAGED \
  --protocol=HTTPS

gcloud compute backend-services add-backend my-agent-lb-agent-backend \
  --region="${REGION}" \
  --network-endpoint-group=my-agent-lb-agent-neg \
  --network-endpoint-group-region="${REGION}"

# Echo Backend Service (HTTP2 for gRPC callouts)
gcloud compute backend-services create my-agent-lb-echo-backend \
  --region="${REGION}" \
  --load-balancing-scheme=EXTERNAL_MANAGED \
  --protocol=HTTP2

gcloud compute backend-services add-backend my-agent-lb-echo-backend \
  --region="${REGION}" \
  --network-endpoint-group=my-agent-lb-echo-neg \
  --network-endpoint-group-region="${REGION}"
```

### Step 4.5: Provision Frontend Resources & Forwarding Rule

```bash
# 1. Reserve Regional Static IP
gcloud compute addresses create my-agent-lb-ip --region="${REGION}"

# 2. Generate and upload self-signed SSL Certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout key.pem -out cert.pem \
  -subj "/CN=my-agent-lb.example.com"

gcloud compute ssl-certificates create my-agent-lb-ssl-cert \
  --certificate=cert.pem \
  --private-key=key.pem \
  --region="${REGION}"

# 3. Create URL Map
gcloud compute url-maps create my-agent-lb-url-map \
  --region="${REGION}" \
  --default-service=my-agent-lb-agent-backend

# 4. Create Target HTTPS Proxy
gcloud compute target-https-proxies create my-agent-lb-https-proxy \
  --region="${REGION}" \
  --url-map=my-agent-lb-url-map \
  --ssl-certificates=my-agent-lb-ssl-cert

# 5. Create Forwarding Rule
gcloud compute forwarding-rules create my-agent-lb-fwd-rule \
  --region="${REGION}" \
  --load-balancing-scheme=EXTERNAL_MANAGED \
  --network=default \
  --address=my-agent-lb-ip \
  --ports=443 \
  --target-https-proxy=my-agent-lb-https-proxy \
  --target-https-proxy-region="${REGION}"
```

### Step 4.6: Attach Service Extension

Fetch the Cloud Run hostname for the echo service:
```bash
ECHO_URL=$(gcloud run services describe grpc-echo-service --region "${REGION}" --format='value(status.url)')
ECHO_HOST=$(echo "$ECHO_URL" | sed -e 's|^https://||' -e 's|/$||')
```

Create `traffic-ext.yaml`:
```yaml
name: projects/YOUR_PROJECT_ID/locations/us-central1/lbTrafficExtensions/my-agent-lb-echo-extension
loadBalancingScheme: EXTERNAL_MANAGED
forwardingRules:
  - https://www.googleapis.com/compute/v1/projects/YOUR_PROJECT_ID/regions/us-central1/forwardingRules/my-agent-lb-fwd-rule
extensionChains:
  - name: "grpc-echo-chain"
    matchCondition:
      celExpression: "true"
    extensions:
      - name: "grpc-echo-proc"
        authority: "YOUR_ECHO_HOST"
        service: "https://www.googleapis.com/compute/v1/projects/YOUR_PROJECT_ID/regions/us-central1/backendServices/my-agent-lb-echo-backend"
        timeout: 2.0s
        failOpen: false
        supportedEvents:
          - REQUEST_HEADERS
          - REQUEST_BODY
          - RESPONSE_HEADERS
          - RESPONSE_BODY
```

Import the Service Extension:
```bash
gcloud service-extensions lb-traffic-extensions import my-agent-lb-echo-extension \
  --source=traffic-ext.yaml \
  --location="${REGION}"
```

---

## 5. Testing and Validation

Use the testing script [`test-regional.sh`](file:///Users/rajeshmi/projects/custom-authz-agent-gateway/test-regional.sh):

```bash
# 1. Standard prompt test
./test-regional.sh "What is the weather in Fremont?" my-agent-lb us-central1

# 2. Custom mathematical prompt
./test-regional.sh "Calculate 45 * 12" my-agent-lb us-central1
```

### Testing with `curl` directly:

```bash
TOKEN=$(gcloud auth print-identity-token)
LB_IP=$(gcloud compute addresses describe my-agent-lb-ip --region us-central1 --format='value(address)')

# 1. Create a session on the Agent
SESSION_RESP=$(curl -k -s -X POST "https://${LB_IP}/apps/app/users/user-123/sessions" \
  -H "Host: my-agent-lb.example.com" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-agent-id: custom-authz-demo-agent" \
  -H "x-agent-tenant-id: finance-dept")

echo "Session: $SESSION_RESP"

# Extract session ID:
SESSION_ID=$(echo "$SESSION_RESP" | jq -r '.id')

# 2. Send prompt to Agent:
curl -k -X POST "https://${LB_IP}/run" \
  -H "Host: my-agent-lb.example.com" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"appName":"app","userId":"user-123","sessionId":"'"$SESSION_ID"'","newMessage":{"role":"user","parts":[{"text":"What is the capital of France?"}]}}'
```

---

## 6. Teardown & Cleanup

Use [`cleanup-regional-lb.sh`](file:///Users/rajeshmi/projects/custom-authz-agent-gateway/cleanup-regional-lb.sh) to delete all created resources cleanly in reverse dependency order:

```bash
# Make script executable
chmod +x cleanup-regional-lb.sh

# Run cleanup:
./cleanup-regional-lb.sh my-agent-lb us-central1
```

### Resources Deleted by Cleanup:
1. Service Extension (`lbTrafficExtensions`)
2. Regional Forwarding Rule
3. Regional Target HTTPS Proxy
4. Regional URL Map
5. Regional SSL Certificate
6. Regional Static IP Address
7. Regional Backend Services (`agent-backend` and `echo-backend`)
8. Regional Serverless NEGs (`agent-neg` and `echo-neg`)
9. Regional Proxy-Only Subnet (`proxy-subnet`)

---

## 7. Troubleshooting & Common Pitfalls

| Issue | Root Cause | Resolution |
| :--- | :--- | :--- |
| **`ipCidrRange cannot overlap with 10.128.0.0/9`** | In auto-mode VPC networks (`default`), `10.128.0.0/9` is reserved for automatic subnets. | Use a non-overlapping CIDR block like `10.0.0.0/23`, `10.1.0.0/23`, or `172.16.0.0/23`. |
| **`'loadBalancingScheme' is a required property`** | Missing `loadBalancingScheme: EXTERNAL_MANAGED` in `lbTrafficExtensions` import manifest. | Ensure `loadBalancingScheme: EXTERNAL_MANAGED` is at the root level of the YAML manifest. |
| **`ext_proc` callout fails / 502 / bypass** | Missing `:authority` header or HTTP/2 cleartext (`h2c`) configuration on Cloud Run. | Ensure the Cloud Run container is deployed with `--use-http2`, backend service uses `--protocol=HTTP2`, and extension manifest specifies `authority: <service-url>`. |
| **Direct Cloud Run access bypasses LB** | Cloud Run ingress is configured to accept public traffic. | Set Cloud Run ingress to `--ingress=internal-and-cloud-load-balancing` to force all traffic through the Load Balancer. |
