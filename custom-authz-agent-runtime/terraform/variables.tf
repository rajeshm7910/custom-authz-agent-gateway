variable "project_id" {
  type        = string
  description = "GCP Project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "GCP Region for regional load balancing and Vertex AI resources"
}

variable "service_name" {
  type        = string
  default     = "custom-authz-agent-gateway"
  description = "Name of the Custom Service Extension service"
}

variable "container_image" {
  type        = string
  default     = "us-central1-docker.pkg.dev/ai-practice-489716/gateway-docker/custom-authz-agent-gateway:latest"
  description = "Container image URI in Artifact Registry or GCR"
}

variable "target_api_url" {
  type        = string
  default     = "https://8.233.68.61.nip.io/custom-security"
  description = "URL of the external API to call for authorization decisions"
}

variable "target_api_key" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Secret API key for authenticating with the target API"
}

variable "fail_open" {
  type        = bool
  default     = false
  description = "Whether to allow requests if the target API fails or times out (fail-closed by default)"
}

variable "network_name" {
  type        = string
  default     = "agw-ingress-vpc"
  description = "VPC network name for the Ingress Gateway"
}

variable "primary_domain" {
  type        = string
  default     = "agw-ingress.agentgateway"
  description = "Primary common name for TLS certificate"
}

variable "agents" {
  type = map(object({
    host                = string
    reasoning_engine_id = string
    agent_project_id    = string
    region              = string
  }))
  default = {
    "gw-ingress-test" = {
      host                = "agw-ingress.agentgateway"
      reasoning_engine_id = "1231533837213761536"
      agent_project_id    = "622260204773"
      region              = "us-central1"
    }
  }
  description = "Configured agent backend (gw-ingress-test) behind the Ingress Gateway"
}
