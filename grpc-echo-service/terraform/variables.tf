variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "The Google Cloud Region for Cloud Run & Serverless NEGs"
}

variable "service_name" {
  type        = string
  default     = "grpc-echo-service"
  description = "Name of the gRPC Echo service deployed on Cloud Run"
}

variable "fail_open" {
  type        = bool
  default     = false
  description = "Whether the traffic extension should fail open (allow) or fail closed (deny) on error"
}
