variable "project_id" {
  type        = string
  description = "GCP Project ID hosting Tier 1 External Ingress Gateway"
}

variable "gateway_name" {
  type        = string
  default     = "gemini-ingress-gw"
  description = "Name prefix for Tier 1 gateway resources"
}

variable "primary_domain" {
  type        = string
  default     = "agentgateway.example.com"
  description = "Primary common name for TLS certificate"
}

variable "agents" {
  type = map(object({
    host                  = string
    service_attachment_id = string
    region                = string
  }))
  description = "Map of agents to register with hostnames, target Service Attachments, and regions"
}

variable "backend_timeout_sec" {
  type        = number
  default     = 300
  description = "Timeout in seconds for agent backend calls"
}

variable "security_policy_id" {
  type        = string
  default     = ""
  description = "Optional Cloud Armor security policy ID"
}
