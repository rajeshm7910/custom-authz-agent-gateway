terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "7.43.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ==============================================================================
# 1. VPC Network & Regional Subnet
# ==============================================================================

resource "google_compute_network" "agent_vpc" {
  name                    = var.network_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "agent_subnet" {
  name          = "${var.network_name}-subnet"
  ip_cidr_range = "10.140.0.0/20"
  region        = var.region
  network       = google_compute_network.agent_vpc.id
}

# ==============================================================================
# 2. Cloud Run Custom Authz Service (Envoy ext_proc gRPC Endpoint)
# ==============================================================================

resource "google_cloud_run_v2_service" "agent_authz" {
  name     = var.authz_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = var.authz_container_image

      ports {
        name           = "h2c"
        container_port = 8080
      }

      env {
        name  = "TARGET_API_URL"
        value = var.target_api_url
      }

      env {
        name  = "TARGET_API_KEY"
        value = var.target_api_key
      }

      env {
        name  = "FAIL_OPEN"
        value = tostring(var.fail_open)
      }

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      env {
        name  = "ENABLE_PROMPT_INSPECTION"
        value = "true"
      }

      startup_probe {
        grpc {
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 10
        timeout_seconds       = 3
      }

      liveness_probe {
        grpc {
          port = 8080
        }
        period_seconds  = 10
        timeout_seconds = 3
      }

      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 1
      max_instance_count = 20
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "authz_invoker" {
  project  = google_cloud_run_v2_service.agent_authz.project
  location = google_cloud_run_v2_service.agent_authz.location
  name     = google_cloud_run_v2_service.agent_authz.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Serverless NEG for Custom Authz Service
resource "google_compute_region_network_endpoint_group" "authz_serverless_neg" {
  name                  = "${var.authz_service_name}-neg"
  project               = var.project_id
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.agent_authz.name
  }
}

# Global Backend Service for Custom Authz (EXTERNAL_MANAGED with HTTP2/gRPC for Service Extension)
resource "google_compute_backend_service" "authz_global_backend" {
  name                  = "${var.authz_service_name}-global-backend"
  project               = var.project_id
  protocol              = "HTTP2"
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.authz_serverless_neg.id
  }
}

# ==============================================================================
# 3. Cloud Run Backend Agent Service (adk-agent-app)
# ==============================================================================

resource "google_cloud_run_v2_service" "adk_agent_backend" {
  name     = var.backend_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = var.backend_container_image

      ports {
        container_port = 8080
      }

      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "us-central1"
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 20
        period_seconds        = 5
        failure_threshold     = 30
        timeout_seconds       = 3
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        period_seconds  = 10
        timeout_seconds = 3
      }

      resources {
        limits = {
          cpu    = "1000m"
          memory = "1Gi"
        }
      }
    }

    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "backend_invoker" {
  project  = google_cloud_run_v2_service.adk_agent_backend.project
  location = google_cloud_run_v2_service.adk_agent_backend.location
  name     = google_cloud_run_v2_service.adk_agent_backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Serverless NEG for Backend Agent Service
resource "google_compute_region_network_endpoint_group" "backend_serverless_neg" {
  name                  = "${var.backend_service_name}-neg"
  project               = var.project_id
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.adk_agent_backend.name
  }
}

# Global Backend Service for Backend Agent
resource "google_compute_backend_service" "agent_backend_service" {
  name                  = "${var.backend_service_name}-backend-service"
  project               = var.project_id
  protocol              = "HTTPS"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy       = var.enable_cloud_armor ? google_compute_security_policy.agent_armor_policy[0].id : null

  backend {
    group = google_compute_region_network_endpoint_group.backend_serverless_neg.id
  }
}

# ==============================================================================
# 4. Tier 1 Global Application Load Balancer (Anycast IP)
# ==============================================================================

# Reserved Static Anycast IP Address
resource "google_compute_global_address" "alb_anycast_ip" {
  name        = "${var.backend_service_name}-anycast-ip"
  project     = var.project_id
  description = "Tier 1 Global Anycast IP for Agent Ingress"
}

# Self-Signed / Managed Certificate for TLS Termination
resource "tls_private_key" "agent_gw_key" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "agent_gw_cert" {
  private_key_pem = tls_private_key.agent_gw_key.private_key_pem

  subject {
    common_name  = var.primary_domain
    organization = "Enterprise Agent Gateway"
  }

  validity_period_hours = 8760

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

resource "google_compute_ssl_certificate" "agent_gw_ssl" {
  name        = "${var.backend_service_name}-ssl-cert"
  project     = var.project_id
  private_key = tls_private_key.agent_gw_key.private_key_pem
  certificate = tls_self_signed_cert.agent_gw_cert.cert_pem

  lifecycle {
    create_before_destroy = true
  }
}

# URL Map Routing to Cloud Run Backend Agent
resource "google_compute_url_map" "agent_url_map" {
  name            = "${var.backend_service_name}-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.agent_backend_service.id

  host_rule {
    hosts        = ["*"]
    path_matcher = "all-paths"
  }

  path_matcher {
    name            = "all-paths"
    default_service = google_compute_backend_service.agent_backend_service.id
  }
}

# Target HTTPS Proxy
resource "google_compute_target_https_proxy" "agent_https_proxy" {
  name             = "${var.backend_service_name}-https-proxy"
  project          = var.project_id
  url_map          = google_compute_url_map.agent_url_map.id
  ssl_certificates = [google_compute_ssl_certificate.agent_gw_ssl.id]
}

# Global Forwarding Rule (Anycast IP:443)
resource "google_compute_global_forwarding_rule" "agent_forwarding_rule" {
  name                  = "${var.backend_service_name}-https-fwd-rule"
  project               = var.project_id
  target                = google_compute_target_https_proxy.agent_https_proxy.id
  ip_address            = google_compute_global_address.alb_anycast_ip.address
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# ==============================================================================
# 5. Service Extension (ext_proc) Attached to Tier 1 Global Forwarding Rule
# ==============================================================================

resource "google_network_services_lb_traffic_extension" "custom_authz_ext" {
  name                  = "${var.backend_service_name}-authz-extension"
  project               = var.project_id
  location              = "global"
  description           = "Custom Authz & Model Armor Service Extension for Cloud Run Backend Agent"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  forwarding_rules      = [google_compute_global_forwarding_rule.agent_forwarding_rule.id]

  extension_chains {
    name = "custom-authz-chain"

    match_condition {
      cel_expression = "true"
    }

    extensions {
      name      = "custom-authz-cloud-run"
      service   = google_compute_backend_service.authz_global_backend.id
      authority = replace(google_cloud_run_v2_service.agent_authz.uri, "https://", "")
      fail_open = var.fail_open
      timeout   = "2s"
      supported_events = [
        "REQUEST_HEADERS",
        "REQUEST_BODY"
      ]
    }
  }
}

# ==============================================================================
# 6. Google Cloud Armor Edge Security Policy
# ==============================================================================

resource "google_compute_security_policy" "agent_armor_policy" {
  count       = var.enable_cloud_armor ? 1 : 0
  name        = "${var.backend_service_name}-armor-policy"
  project     = var.project_id
  description = "Cloud Armor Security Policy for Agent Gateway Edge"

  # Default rule: Allow traffic
  rule {
    action   = "allow"
    priority = "2147483647"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Default allow rule"
  }

  # Rate limiting rule: Max 100 requests per minute per client IP
  rule {
    action   = "rate_based_ban"
    priority = "1000"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 100
        interval_sec = 60
      }
      ban_duration_sec = 300
    }
    description = "Rate limit agents to 100 req/min per IP"
  }
}
