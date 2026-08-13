# ==============================================================================
# Tier 2: Agent Producer Module (Internal Tier)
# Regional Internal ALB + URL Rewriting + PSC NEG to Vertex AI + Service Attachment
# ==============================================================================

# 1. Regional PSC Network Endpoint Group targeting Vertex AI Google APIs
resource "google_compute_region_network_endpoint_group" "vertex_ai_psc_neg" {
  name                  = "${var.agent_name}-vertex-psc-neg"
  project               = var.project_id
  region                = var.region
  network_endpoint_type = "PRIVATE_SERVICE_CONNECT"
  psc_target_service    = "${var.region}-aiplatform.googleapis.com"
}

# 2. Regional Backend Service targeting the Vertex AI PSC NEG
resource "google_compute_region_backend_service" "agent_backend_service" {
  name                  = "${var.agent_name}-ilb-backend"
  project               = var.project_id
  region                = var.region
  protocol              = "HTTP2"
  load_balancing_scheme = "INTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.vertex_ai_psc_neg.id
  }

  log_config {
    enable      = true
    sample_rate = 1.0
  }
}

# 3. Regional URL Map with Host and Path Rewriting for Reasoning Engine
# Rewrites Host -> <region>-aiplatform.googleapis.com
# Rewrites Path -> /v1/projects/<agent_project>/locations/<region>/reasoningEngines/<engine_id>:streamQuery
resource "google_compute_region_url_map" "agent_url_map" {
  name            = "${var.agent_name}-ilb-url-map"
  project         = var.project_id
  region          = var.region
  default_service = google_compute_region_backend_service.agent_backend_service.id

  path_matcher {
    name            = "agent-route-matcher"
    default_service = google_compute_region_backend_service.agent_backend_service.id

    default_route_action {
      url_rewrite {
        host_rewrite        = "${var.region}-aiplatform.googleapis.com"
        path_prefix_rewrite = "/v1/projects/${var.agent_project_id}/locations/${var.region}/reasoningEngines/${var.reasoning_engine_id}:streamQuery"
      }
    }

    # Route /chat or /streamQuery to Vertex AI streamQuery endpoint
    path_rule {
      paths = ["/chat", "/chat/*", "/streamQuery", "/streamQuery/*"]
      service = google_compute_region_backend_service.agent_backend_service.id

      route_action {
        url_rewrite {
          host_rewrite        = "${var.region}-aiplatform.googleapis.com"
          path_prefix_rewrite = "/v1/projects/${var.agent_project_id}/locations/${var.region}/reasoningEngines/${var.reasoning_engine_id}:streamQuery"
        }
      }
    }

    # Route /query to Vertex AI synchronous query endpoint
    path_rule {
      paths = ["/query", "/query/*"]
      service = google_compute_region_backend_service.agent_backend_service.id

      route_action {
        url_rewrite {
          host_rewrite        = "${var.region}-aiplatform.googleapis.com"
          path_prefix_rewrite = "/v1/projects/${var.agent_project_id}/locations/${var.region}/reasoningEngines/${var.reasoning_engine_id}:query"
        }
      }
    }
  }

  host_rule {
    hosts        = ["*"]
    path_matcher = "agent-route-matcher"
  }
}

# 4. Regional Target HTTP Proxy
resource "google_compute_region_target_http_proxy" "agent_target_http_proxy" {
  name    = "${var.agent_name}-ilb-target-proxy"
  project = var.project_id
  region  = var.region
  url_map = google_compute_region_url_map.agent_url_map.id
}

# 5. Regional Forwarding Rule for Internal ALB with Global Access enabled
resource "google_compute_forwarding_rule" "agent_forwarding_rule" {
  name                  = "${var.agent_name}-ilb-fwd-rule"
  project               = var.project_id
  region                = var.region
  ip_protocol           = "TCP"
  port_range            = "80"
  load_balancing_scheme = "INTERNAL_MANAGED"
  network               = var.network_id
  subnetwork            = var.subnetwork_id
  target                = google_compute_region_target_http_proxy.agent_target_http_proxy.id
  allow_global_access   = true
}

# 6. Service Attachment published for Tier 1 PSC Consumers
resource "google_compute_service_attachment" "agent_service_attachment" {
  name                  = "${var.agent_name}-service-attachment"
  project               = var.project_id
  region                = var.region
  description           = "PSC Service Attachment for Agent ${var.agent_name} (Tier 2)"
  connection_preference = "ACCEPT_AUTOMATIC"
  target_service        = google_compute_forwarding_rule.agent_forwarding_rule.id
  nat_subnets           = var.psc_nat_subnet_ids
  enable_proxy_protocol = false
}
