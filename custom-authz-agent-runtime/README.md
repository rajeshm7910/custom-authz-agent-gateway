# Self-Managed Ingress Gateway for Gemini Enterprise Agent Platform

An enterprise reference implementation of a **Two-Tier Self-Managed Ingress Gateway** for Google Cloud **Gemini Enterprise / Vertex AI Agent Runtime (Reasoning Engines / ADK)** using Google Cloud Application Load Balancing and Private Service Connect (PSC).

---

## Architecture

```
Client (agent-a.example.com / agent-b.example.com)
                      │
                      ▼
┌────────────────────────────────────────────────────────┐
│   Tier 1: Global External Application Load Balancer    │
│   • Anycast IP + TLS Termination (SNI)                 │
│   • Host-Based URL Map Routing (agent-a / agent-b)     │
│   • Regional PSC NEGs (global access mode)             │
│   • Cloud Armor WAF & Edge IAP                         │
└──────────────────────────┬─────────────────────────────┘
                           │ Private Service Connect (PSC)
                           ▼
┌────────────────────────────────────────────────────────┐
│   Tier 2: Regional Internal Application Load Balancer  │
│   • Per-Agent Producer Project (Service Attachment)    │
│   • URL Map Host & Path Rewrite (POST /chat -> REST)   │
│   • Model Armor & Custom Service Extension (ext_proc)  │
│   • Regional PSC NEG to Google APIs                    │
└──────────────────────────┬─────────────────────────────┘
                           │ Private Google API Transit
                           ▼
┌────────────────────────────────────────────────────────┐
│   Vertex AI Agent Runtime (Reasoning Engines / ADK)    │
│   • /v1/projects/.../reasoningEngines/<id>:streamQuery │
└────────────────────────────────────────────────────────┘
```

---

## Key Features

1. **Decoupled Two-Tier Topology**:
   - **Tier 1 (Consumer Project)**: Global External ALB (`EXTERNAL_MANAGED`), single Anycast IP, SNI TLS termination, hostname-based fan-out, and coarse-grained edge protection.
   - **Tier 2 (Producer Projects)**: Independent Regional Internal ALBs (`INTERNAL_MANAGED`) fronting each agent backend, published as PSC Service Attachments (`allow_global_access = true`).
2. **Dynamic URL & Host Rewriting**:
   - Client sends simple `POST /chat` with `Host: agent-a.example.com`.
   - Tier 2 rewrites `Host` to `<region>-aiplatform.googleapis.com` and path to `/v1/projects/<project>/locations/<region>/reasoningEngines/<engine_id>:streamQuery`.
3. **Private Connectivity to Vertex AI**:
   - Tier 2 uses `PRIVATE_SERVICE_CONNECT` NEGs to reach `aiplatform.googleapis.com` privately without traversing the public internet.
4. **Multi-Layer Policy Enforcement**:
   - **Transport Security**: HTTPS at edge, private mTLS/PSC across tiers.
   - **Identity-Aware Edge Protection (IAP)**: Validates identity, evaluates Context-Aware Access (CAA), and enforces IAM at edge.
   - **Inline AI Payload Security (Model Armor & Custom Service Extension)**: Ingress prompt injection detection and egress response PII sanitization.

---

## Project Structure

```
├── ARCHITECTURE.md                  # Comprehensive reference architecture & 10-step request flow
├── Dockerfile                       # Multi-stage container build for gRPC Service Extension
├── README.md                        # Documentation and deployment guide
├── requirements.txt                 # Dependencies
├── protos/                          # Envoy ext_authz & Google RPC proto files
├── scripts/
│   ├── test_two_tier_gateway.py     # End-to-end Two-Tier Gateway simulation & test
│   ├── query_reasoning_engine.py    # Direct Vertex AI Reasoning Engine query tool
│   ├── call_discovery_engine.py     # Gemini Enterprise Assistant API caller
│   ├── mock_external_api.py         # Mock Policy Engine server for local testing
│   └── test_gRPC_client.py          # gRPC client for local Authz Extension testing
├── src/
│   ├── authz_service.py             # Envoy ext_authz & Model Armor Servicer
│   ├── config.py                    # Environment configuration
│   ├── health_server.py             # Health check & readiness server
│   ├── main.py                      # Server entrypoint
│   └── generated/                   # Compiled gRPC stubs
├── terraform/                       # Infrastructure as Code
│   ├── main.tf                      # Root composition (VPC, Proxy Subnets, Tier 1, Tier 2)
│   ├── variables.tf                 # Global configuration & Agent map
│   ├── outputs.tf                   # Exported Anycast IP & Service Attachments
│   └── modules/
│       ├── tier1_external_gateway/  # Global External ALB + PSC NEGs
│       └── tier2_agent_producer/    # Regional Internal ALB + URL Rewrites + Vertex AI PSC NEG
└── tests/
    └── test_authz_service.py        # Pytest unit test suite
```

---

## Verification & Testing

### 1. Run Unit Tests
```bash
python3 -m pytest tests/ -v
```

### 2. Test Two-Tier Gateway Simulation
```bash
# Test routing for Agent A with path rewrite
python3 scripts/test_two_tier_gateway.py --host agent-a.example.com --path /chat --skip-live-call

# Test routing for Agent B
python3 scripts/test_two_tier_gateway.py --host agent-b.example.com --path /streamQuery --skip-live-call
```

---

## Deployment with Terraform

```bash
cd terraform

# 1. Initialize Terraform
terraform init

# 2. Review and apply configuration
terraform plan
terraform apply
```
