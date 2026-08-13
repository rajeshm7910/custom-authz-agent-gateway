variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
}

variable "region" {
  description = "Google Cloud primary region for Cloud Run and Regional resources"
  type        = string
  default     = "us-central1"
}

variable "network_name" {
  description = "VPC Network name for the agent infrastructure"
  type        = string
  default     = "custom-authz-agent-vpc"
}

variable "authz_service_name" {
  description = "Name of the Custom Authz Cloud Run service"
  type        = string
  default     = "custom-authz-cloud-run"
}

variable "authz_container_image" {
  description = "Container image for the Custom Authz Cloud Run service"
  type        = string
  default     = "gcr.io/cloudrun/hello" # Replace with built image URI
}

variable "backend_service_name" {
  description = "Name of the Backend Agent Cloud Run service (e.g. adk-agent-app)"
  type        = string
  default     = "adk-agent-app"
}

variable "backend_container_image" {
  description = "Container image for the ADK Agent Backend Cloud Run service"
  type        = string
  default     = "gcr.io/cloudrun/hello" # Replace with built image URI
}

variable "target_api_url" {
  description = "Apigee Policy Engine or custom authorization webhook endpoint URL"
  type        = string
  default     = "https://apigee.googleapis.com/v1/organizations/my-org/environments/prod/authz:evaluate"
}

variable "target_api_key" {
  description = "API Key or Bearer token for authenticating with Apigee"
  type        = string
  default     = ""
  sensitive   = true
}

variable "fail_open" {
  description = "Whether to fail-open (allow traffic) if Apigee / Authz service is unreachable"
  type        = bool
  default     = false
}

variable "primary_domain" {
  description = "Primary domain for the Agent Gateway ALB (e.g. agent.example.com)"
  type        = string
  default     = "agent.example.com"
}

variable "enable_cloud_armor" {
  description = "Enable Google Cloud Armor Edge Security Policy"
  type        = bool
  default     = true
}
