# Cloud Run Custom Authz & Ingress Gateway for AI Agents

An enterprise reference implementation for securing, authorizing, and governing **AI Agents on Cloud Run (e.g. `adk-agent-app`)** using a **Tier 1 Global Application Load Balancer (Anycast IP)** with inline **Service Extensions (`ext_proc`)**, a **Cloud Run Custom Authz Service**, and the **Apigee Policy Engine**.

---

## Architecture

```
[ CLIENT ] ──► [ TIER 1 GLOBAL ALB (Anycast IP) ]
                      │
                      ├─► [ Service Extension (ext_proc) ] ──► [ Cloud Run Authz ] ──► [ Apigee ]
                      │                                                │
                      │                                                ▼ (ALLOWED)
                      ▼ (Forward)
              [ Cloud Run Backend Agent (e.g. adk-agent-app) ]
```

### Key Highlights
1. **Tier 1 Global External ALB**: Single global Anycast IP terminating TLS with Cloud Armor edge security and rate limiting.
2. **Inline Envoy `ext_proc` Service Extension**: Intercepts `REQUEST_HEADERS` and `REQUEST_BODY` synchronously at the load balancer edge before requests reach the backend.
3. **Cloud Run Custom Authz Service**: Evaluates caller context against Apigee Policy Engine, enforces prompt guardrails (Model Armor), and enriches request headers with validated identity.
4. **Cloud Run Backend Agent (`adk-agent-app`)**: Containerized Agent application built with ADK / FastAPI receiving authenticated caller headers (`x-agentgateway-auth-status: ALLOWED`, `x-agentgateway-principal`).

---

## Project Structure

```
├── ARCHITECTURE.md                  # Comprehensive architecture specification & sequence flow
├── Dockerfile                       # Multi-stage container build for Cloud Run Custom Authz
├── README.md                        # Project documentation and quickstart
├── requirements.txt                 # Dependencies for local testing & services
├── agent_backend/                   # Sample ADK / Cloud Run Agent Application
│   ├── Dockerfile                   # Container build for Backend Agent
│   ├── main.py                      # FastAPI Agent service (/chat, /query, /streamQuery)
│   └── requirements.txt             # Agent backend dependencies
├── protos/                          # Envoy ext_proc, ext_authz & Google RPC proto files
│   ├── envoy/                       # Envoy core and service definitions
│   └── google/                      # Google RPC status definitions
├── scripts/
│   ├── compile_protos.py            # Protobuf compilation script
│   ├── mock_apigee_server.py        # Mock Apigee Policy Engine for local development
│   ├── test_e2e_simulation.py       # Full end-to-end multi-scenario simulation suite
│   └── test_grpc_client.py          # Direct gRPC client for ext_proc testing
├── src/                             # Cloud Run Custom Authz Service Implementation
│   ├── authz_service.py             # Envoy ext_authz servicer
│   ├── config.py                    # Environment and policy configuration
│   ├── ext_proc_service.py          # Envoy ext_proc servicer & Model Armor guardrails
│   ├── generated/                   # Compiled Python protobuf & gRPC stubs
│   ├── health_server.py             # Auxiliary HTTP / health check server
│   └── main.py                      # Server entrypoint with graceful shutdown
├── terraform/                       # Infrastructure as Code (Terraform)
│   ├── main.tf                      # ALB, Service Extension, Serverless NEGs & Cloud Run
│   ├── outputs.tf                   # Exported Anycast IP, URIs and endpoints
│   ├── terraform.tfvars.example     # Example configuration variables
│   └── variables.tf                 # Variable declarations
└── tests/                           # Pytest unit & integration test suite
    ├── test_authz.py                # Tests for ext_authz servicer
    └── test_ext_proc.py             # Tests for ext_proc servicer & Model Armor
```

---

## Verification & Local Testing

### 1. Compile Protobuf Definitions
```bash
python3 scripts/compile_protos.py
```

### 2. Run Pytest Suite
```bash
PYTHONPATH=. pytest tests/ -v
```

### 3. Run End-to-End Multi-Scenario Simulation
Simulates the entire flow (Mock Apigee + Cloud Run Authz + Cloud Run Backend Agent + ALB forwarding):
```bash
python3 scripts/test_e2e_simulation.py
```

Scenarios evaluated:
- **Scenario 1**: Authorized Request (`Alice` -> `adk-agent-app`) — Apigee passes, headers mutated, backend executes agent query.
- **Scenario 2**: Blocked Principal Policy Denial — Apigee rejects `blocked-user`, ALB immediately halts with HTTP 403.
- **Scenario 3**: Model Armor Prompt Injection Detection — Malicious prompt detected in body, intercepted with HTTP 403.
- **Scenario 4**: Backend Agent Health Check.

---

## Deploying to Google Cloud

### Step 1: Build and Push Container Images

```bash
# 1. Build and push Custom Authz Service
gcloud builds submit --tag gcr.io/$PROJECT_ID/custom-authz-cloud-run:latest .

# 2. Build and push Backend Agent Service
cd agent_backend
gcloud builds submit --tag gcr.io/$PROJECT_ID/adk-agent-app:latest .
cd ..
```

### Step 2: Provision Infrastructure with Terraform

```bash
cd terraform

# Copy and edit variables
cp terraform.tfvars.example terraform.tfvars
# (Edit terraform.tfvars with your GCP project ID and domain)

# Initialize and apply
terraform init
terraform plan
terraform apply
```

### Step 3: Test the Deployed Gateway

```bash
GATEWAY_IP=$(terraform output -raw global_anycast_ip)

# Query the Agent via Tier 1 Global ALB
curl -X POST "https://${GATEWAY_IP}/chat" \
  -H "Host: agent.example.com" \
  -H "Authorization: Bearer my-user-token" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the status of our deployment?"}' \
  --insecure
```

---

## Environment Variables Reference

| Variable | Default | Description |
| :--- | :--- | :--- |
| `TARGET_API_URL` | `http://localhost:8082/v1/authz/evaluate` | Apigee Policy Engine or custom auth webhook endpoint |
| `TARGET_API_KEY` | `""` | API Key or Bearer token for authenticating with Apigee |
| `TARGET_API_TIMEOUT_SECONDS` | `2.0` | Timeout in seconds for Apigee evaluation call |
| `FAIL_OPEN` | `false` | If `true`, permits requests when Apigee is unreachable |
| `ENABLE_PROMPT_INSPECTION` | `true` | Enables inline Model Armor prompt injection guardrails |
| `PORT` | `8080` | Port for Cloud Run gRPC service |
| `HEALTH_PORT` | `8081` | Port for auxiliary HTTP health checks |
