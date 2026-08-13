# Custom Authorization & Ingress Agent Gateway Demos

This repository implements secure ingress gateways with custom authorization controls for AI agents on Google Cloud. It provides two target deployment architectures using a centralized authorization service:

1. **Cloud Run Target**: Deploying ReAct agents directly to Google Cloud Run secured by an external Global Application Load Balancer (ALB) and service extensions.
2. **Vertex AI Agent Runtime Target (Two-Tier Ingress)**: Deploying ReAct agents into Vertex AI Agent Runtime (Reasoning Engines), secured by a two-tier Consumer-Producer PSC gateway architecture.

---

## Architecture Overview

```mermaid
graph TD
    subgraph Cloud Run Target
        CR_Client[Client] -->|HTTPS| CR_ALB[Global Load Balancer]
        CR_ALB -->|ext_proc / ext_authz| CR_Authz[Custom Authz Cloud Run]
        CR_ALB -->|Forward ALLOWED| CR_Agent[ReAct Agent Backend]
    end

    subgraph Agent Runtime Target (Two-Tier)
        RT_Client[Client] -->|HTTPS| RT_ALB_T1[Tier 1 Global ALB]
        RT_ALB_T1 -->|ext_proc| RT_Authz[Custom Authz Cloud Run]
        RT_ALB_T1 -->|PSC NEG| RT_Attachment[PSC Service Attachment]
        RT_Attachment -->|VPC Transit| RT_ALB_T2[Tier 2 Internal ALB]
        RT_ALB_T2 -->|PSC NEG| RT_Vertex[Vertex AI Reasoning Engine]
    end
```

---

## Directory Structure

* [**`custom-authz-service/`**](file:///Users/rajeshmi/projects/custom-authz-agent-gateway/custom-authz-service): Centralized authorization codebase. Contains the gRPC `ext_authz` and `ext_proc` servers, and the HTTP health/REST proxy server.
* [**`custom-authz-agent-cloud-run/`**](file:///Users/rajeshmi/projects/custom-authz-agent-gateway/custom-authz-agent-cloud-run): Terraform configurations and resources for wiring up the Cloud Run deployment.
* [**`custom-authz-agent-runtime/`**](file:///Users/rajeshmi/projects/custom-authz-agent-gateway/custom-authz-agent-runtime): Terraform configurations and resources for wiring up the Two-Tier Ingress Agent Runtime deployment.
* [**`agents/`**](file:///Users/rajeshmi/projects/custom-authz-agent-gateway/agents): Source code for the backend ReAct agent (`custom-authz-demo-agent`).

---

## Prerequisites

Ensure you have the following tools installed and configured:
* Google Cloud SDK (`gcloud`) authenticated to your GCP project.
* Terraform (`>= 1.5.0`).
* `uv` Python package installer (`pip install uv`).
* `agents-cli` tool.

---

## Deployment Instructions

### 1. Deploying to Cloud Run Target
Run the Cloud Run orchestration deployment script from the root directory:
```bash
./deploy-agent-cloud-run-demo.sh
```
This script:
1. Builds and deploys the centralized `custom-authz-service` to Cloud Run.
2. Deploys the ReAct agent onto Cloud Run using `agents-cli deploy`.
3. Runs Terraform to wire up the external Application Load Balancer and Service Extension.

### 2. Deploying to Vertex AI Agent Runtime Target
Run the Agent Runtime orchestration deployment script from the root directory:
```bash
./deploy-agent-runtime-demo.sh
```
This script:
1. Builds and deploys the centralized `custom-authz-service` to Cloud Run.
2. Deploys the ReAct agent onto Vertex AI Agent Runtime using `agents-cli deploy`.
3. Runs Terraform to wire up the Tier 1 Global Load Balancer, PSC service attachment tunnels, and Tier 2 Internal Load Balancer routing path.

---

## Verification and Testing

A unified testing script, [`test-agent.sh`](file:///Users/rajeshmi/projects/custom-authz-agent-gateway/test-agent.sh), is provided in the root directory. It automatically extracts the load balancer IP from the Terraform state and queries the active agent.

### Testing Cloud Run Target
Query the Cloud Run backend agent (uses a Google OIDC ID token for validation):
```bash
./test-agent.sh "What is the weather in Fremont?" cloud-run
```

### Testing Agent Runtime Target
Query the Vertex AI Reasoning Engine backend agent (uses a Google OAuth2 Access Token for validation):
```bash
./test-agent.sh "What is the weather in Fremont?" runtime
```

---

## Development & Local Testing

You can run local unit tests for the centralized authorization service using `uv`:
```bash
cd custom-authz-service
uv sync
uv run pytest
```

---

## Cleanup & Teardown

To clean up all deployed Google Cloud infrastructure, API services, and local configurations, use the provided teardown scripts:

### Cleaning up Cloud Run Target
Tears down the Application Load Balancer, IAM bindings, and deletes the Cloud Run services:
```bash
./cleanup-agent-cloud-run-demo.sh
```

### Cleaning up Agent Runtime Target
Tears down the Two-Tier Load Balancers, PSC endpoints, deletes the Vertex AI Reasoning Engine dynamically via Python SDK, and deletes the Cloud Run services:
```bash
./cleanup-agent-runtime-demo.sh
```

