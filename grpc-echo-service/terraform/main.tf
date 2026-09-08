terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0.0"
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
# 1. Cloud Run gRPC Echo Service
# ==============================================================================
resource "google_cloud_run_v2_service" "grpc_echo_service" {
  name     = var.service_name
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/gateway-docker/${var.service_name}:latest"
      
      ports {
        container_port = 8080
        name           = "h2c" # Enables HTTP/2 (gRPC) cleartext to the container
      }

      env {
        name  = "PORT"
        value = "8080"
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
      max_instance_count = 5
    }
  }
}

# Allow unauthenticated invocation (or manage via IAM)
resource "google_cloud_run_v2_service_iam_member" "grpc_echo_invoker" {
  project  = google_cloud_run_v2_service.grpc_echo_service.project
  location = google_cloud_run_v2_service.grpc_echo_service.location
  name     = google_cloud_run_v2_service.grpc_echo_service.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ==============================================================================
# 2. Serverless NEG and Global Backend Service (HTTP2 / gRPC)
# ==============================================================================
resource "google_compute_region_network_endpoint_group" "grpc_echo_neg" {
  name                  = "${var.service_name}-neg"
  project               = var.project_id
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.grpc_echo_service.name
  }
}

resource "google_compute_backend_service" "grpc_echo_backend" {
  name                  = "${var.service_name}-global-backend"
  project               = var.project_id
  protocol              = "HTTP2" # gRPC runs over HTTP/2
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.grpc_echo_neg.id
  }
}

# ==============================================================================
# 3. Global Application Load Balancer (Anycast IP + TLS)
# ==============================================================================
resource "google_compute_global_address" "grpc_echo_ip" {
  name        = "${var.service_name}-anycast-ip"
  project     = var.project_id
  description = "Global Static IP for gRPC Echo Service & Traffic Extension"
}

resource "tls_private_key" "grpc_echo_key" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "grpc_echo_cert" {
  private_key_pem = tls_private_key.grpc_echo_key.private_key_pem

  subject {
    common_name  = "${var.service_name}.example.com"
    organization = "Agent Gateway Sandbox"
  }

  validity_period_hours = 8760

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

resource "google_compute_ssl_certificate" "grpc_echo_ssl" {
  name        = "${var.service_name}-ssl-cert"
  project     = var.project_id
  private_key = tls_private_key.grpc_echo_key.private_key_pem
  certificate = tls_self_signed_cert.grpc_echo_cert.cert_pem

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_url_map" "grpc_echo_url_map" {
  name            = "${var.service_name}-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.grpc_echo_backend.id
}

resource "google_compute_target_https_proxy" "grpc_echo_https_proxy" {
  name             = "${var.service_name}-https-proxy"
  project          = var.project_id
  url_map          = google_compute_url_map.grpc_echo_url_map.id
  ssl_certificates = [google_compute_ssl_certificate.grpc_echo_ssl.id]
}

resource "google_compute_global_forwarding_rule" "grpc_echo_fwd_rule" {
  name                  = "${var.service_name}-https-fwd-rule"
  project               = var.project_id
  target                = google_compute_target_https_proxy.grpc_echo_https_proxy.id
  ip_address            = google_compute_global_address.grpc_echo_ip.address
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# ==============================================================================
# 4. GCP Service Extension (ext_proc Traffic Extension)
# ==============================================================================
resource "google_network_services_lb_traffic_extension" "grpc_echo_traffic_ext" {
  name                  = "${var.service_name}-traffic-ext"
  project               = var.project_id
  location              = "global"
  description           = "Traffic Extension with Sensitive Data (SSN) Denial & Response Modification"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  forwarding_rules      = [google_compute_global_forwarding_rule.grpc_echo_fwd_rule.id]

  extension_chains {
    name = "grpc-echo-chain"

    match_condition {
      cel_expression = "true"
    }

    extensions {
      name      = "grpc-echo-ext-proc"
      service   = google_compute_backend_service.grpc_echo_backend.id
      authority = replace(google_cloud_run_v2_service.grpc_echo_service.uri, "https://", "")
      fail_open = var.fail_open
      timeout   = "2s"
      supported_events = [
        "REQUEST_HEADERS",
        "REQUEST_BODY",
        "RESPONSE_BODY"
      ]
    }
  }
}
