# ==============================================================================
# Tier 1: External Ingress Gateway Module (Consumer Tier)
# Global External ALB + Anycast IP + Host-based Routing + PSC NEGs to Tier 2
# ==============================================================================

# 1. Regional PSC NEGs targeting Tier 2 Service Attachments
resource "google_compute_region_network_endpoint_group" "tier2_psc_neg" {
  for_each              = var.agents
  name                  = "${each.key}-tier1-psc-neg"
  project               = var.project_id
  region                = each.value.region
  network_endpoint_type = "PRIVATE_SERVICE_CONNECT"
  psc_target_service    = each.value.service_attachment_id

  lifecycle {
    ignore_changes = [network, subnetwork]
  }
}

# 2. Global Backend Services for each Agent backend
resource "google_compute_backend_service" "agent_global_backend" {
  for_each              = var.agents
  name                  = "${each.key}-tier1-global-backend"
  project               = var.project_id
  protocol              = "HTTP"
  port_name             = "http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = var.backend_timeout_sec

  backend {
    group = google_compute_region_network_endpoint_group.tier2_psc_neg[each.key].id
  }

  log_config {
    enable      = true
    sample_rate = 1.0
  }

  security_policy = var.security_policy_id != "" ? var.security_policy_id : null
}

# 3. Fallback / Default Backend Service if request matches no host rule
resource "google_compute_backend_service" "default_global_backend" {
  name                  = "${var.gateway_name}-default-backend"
  project               = var.project_id
  protocol              = "HTTP"
  port_name             = "http"
  load_balancing_scheme = "EXTERNAL_MANAGED"

  # Uses the first configured agent backend as default fallback
  backend {
    group = google_compute_region_network_endpoint_group.tier2_psc_neg[keys(var.agents)[0]].id
  }
}

# 4. Global URL Map with Host-based routing per agent
resource "google_compute_url_map" "tier1_url_map" {
  name            = "${var.gateway_name}-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.default_global_backend.id

  dynamic "host_rule" {
    for_each = var.agents
    content {
      hosts        = [host_rule.value.host]
      path_matcher = "${host_rule.key}-matcher"
    }
  }

  dynamic "path_matcher" {
    for_each = var.agents
    content {
      name            = "${path_matcher.key}-matcher"
      default_service = google_compute_backend_service.agent_global_backend[path_matcher.key].id
    }
  }
}

# 5. TLS Private Key and Self-Signed Certificate for SNI & HTTPS Front Door
resource "tls_private_key" "tier1_key" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "tier1_cert_data" {
  private_key_pem = tls_private_key.tier1_key.private_key_pem

  subject {
    common_name  = var.primary_domain
    organization = "Gemini Enterprise Ingress Gateway"
  }

  # Add all agent hostnames as SANs (Subject Alternative Names)
  dns_names = concat(
    [var.primary_domain],
    [for k, v in var.agents : v.host]
  )

  validity_period_hours = 8760 # 1 year

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]

  lifecycle {
    ignore_changes = [dns_names, allowed_uses, subject]
  }
}

resource "google_compute_ssl_certificate" "tier1_ssl_cert" {
  name        = "${var.gateway_name}-ssl-cert"
  project     = var.project_id
  private_key = tls_private_key.tier1_key.private_key_pem
  certificate = tls_self_signed_cert.tier1_cert_data.cert_pem

  lifecycle {
    ignore_changes = [certificate, private_key]
  }
}

# 6. Global Target HTTPS Proxy
resource "google_compute_target_https_proxy" "tier1_https_proxy" {
  name             = "${var.gateway_name}-https-proxy"
  project          = var.project_id
  url_map          = google_compute_url_map.tier1_url_map.id
  ssl_certificates = [google_compute_ssl_certificate.tier1_ssl_cert.id]
}

# 7. Global Anycast Static IP Address
resource "google_compute_global_address" "tier1_anycast_ip" {
  name    = "${var.gateway_name}-anycast-ip"
  project = var.project_id
}

# 8. Global Forwarding Rule (Port 443)
resource "google_compute_global_forwarding_rule" "tier1_forwarding_rule" {
  name                  = "${var.gateway_name}-fwd-rule"
  project               = var.project_id
  ip_protocol           = "TCP"
  port_range            = "443"
  target                = google_compute_target_https_proxy.tier1_https_proxy.id
  ip_address            = google_compute_global_address.tier1_anycast_ip.id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
