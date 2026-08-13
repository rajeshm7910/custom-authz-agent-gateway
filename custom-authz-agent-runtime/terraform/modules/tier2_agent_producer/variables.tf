variable "project_id" {
  type        = string
  description = "GCP Project ID hosting the Tier 2 producer resources"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "GCP region for regional resources"
}

variable "agent_name" {
  type        = string
  description = "Identifier for the agent (e.g. agent-a, gw-ingress-test)"
}

variable "agent_project_id" {
  type        = string
  description = "Project ID where the Vertex AI Reasoning Engine resides"
}

variable "reasoning_engine_id" {
  type        = string
  description = "Reasoning Engine ID in Vertex AI Agent Runtime"
}

variable "network_id" {
  type        = string
  description = "VPC network self link or ID"
}

variable "subnetwork_id" {
  type        = string
  description = "Subnet self link or ID for the regional internal load balancer"
}

variable "psc_nat_subnet_ids" {
  type        = list(string)
  description = "Subnets dedicated for PSC NAT (purpose = PRIVATE_SERVICE_CONNECT)"
}

variable "backend_timeout_sec" {
  type        = number
  default     = 300
  description = "Timeout in seconds for streaming agent queries"
}
