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
# 1. VPC Network & Subnets for Ingress Architecture
# ==============================================================================

# VPC Network
resource "google_compute_network" "gateway_vpc" {
  name                    = var.network_name
  auto_create_subnetworks = false
}

# Standard Subnet for Regional Resources
resource "google_compute_subnetwork" "gateway_subnet" {
  name          = "${var.network_name}-subnet"
  ip_cidr_range = "10.128.0.0/20"
  region        = var.region
  network       = google_compute_network.gateway_vpc.id
}

# Proxy-Only Subnet required for Regional Internal ALBs (Tier 2)
resource "google_compute_subnetwork" "proxy_only_subnet" {
  name          = "${var.network_name}-proxy-subnet"
  ip_cidr_range = "10.129.0.0/23"
  region        = var.region
  purpose       = "REGIONAL_MANAGED_PROXY"
  role          = "ACTIVE"
  network       = google_compute_network.gateway_vpc.id
}

# Dedicated PSC NAT Subnet for Agent Backend Service Attachment
resource "google_compute_subnetwork" "psc_nat_subnet" {
  name          = "${var.network_name}-psc-nat-subnet"
  ip_cidr_range = "10.130.0.0/24"
  region        = var.region
  purpose       = "PRIVATE_SERVICE_CONNECT"
  network       = google_compute_network.gateway_vpc.id
}

# Firewall rule allowing health checks and proxy traffic
resource "google_compute_firewall" "allow_proxy_and_health_checks" {
  name    = "${var.network_name}-allow-internal-proxy"
  network = google_compute_network.gateway_vpc.id

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "8080", "50051"]
  }

  source_ranges = [
    "10.128.0.0/20", # Subnet range
    "10.129.0.0/23", # Proxy range
    "10.130.0.0/24", # PSC NAT range
    "35.191.0.0/16", # Google Cloud Health Checks
    "130.211.0.0/22",
  ]
}

# Cloud NAT Router to allow Envoy Proxies in Proxy Subnet to reach Cloud Run & External APIs
resource "google_compute_router" "gateway_nat_router" {
  name    = "${var.network_name}-nat-router"
  project = var.project_id
  region  = var.region
  network = google_compute_network.gateway_vpc.id
}

resource "google_compute_router_nat" "gateway_nat" {
  name                               = "${var.network_name}-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.gateway_nat_router.name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# ==============================================================================
# 2. Cloud Run Custom Authz / Model Armor Service Extension
# ==============================================================================

resource "google_cloud_run_v2_service" "agent_authz_gateway" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    containers {
      image = var.container_image

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
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "REASONING_ENGINE_ID"
        value = var.agents["custom-authz-demo-agent"].reasoning_engine_id
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
      max_instance_count = 10
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  project  = google_cloud_run_v2_service.agent_authz_gateway.project
  location = google_cloud_run_v2_service.agent_authz_gateway.location
  name     = google_cloud_run_v2_service.agent_authz_gateway.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Serverless NEG connecting Cloud Run to Tier 1 Global Load Balancer / Service Extension
resource "google_compute_region_network_endpoint_group" "serverless_neg" {
  name                  = "${var.service_name}-neg"
  project               = var.project_id
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.agent_authz_gateway.name
  }
}



# ==============================================================================
# 3. Tier 2: Agent Producer Module for gw-ingress-test
# ==============================================================================

module "tier2_agent_producer" {
  for_each = var.agents

  source = "./modules/tier2_agent_producer"

  project_id          = var.project_id
  region              = each.value.region
  agent_name          = each.key
  agent_project_id    = each.value.agent_project_id
  reasoning_engine_id = each.value.reasoning_engine_id
  network_id          = google_compute_network.gateway_vpc.id
  subnetwork_id       = google_compute_subnetwork.gateway_subnet.id
  psc_nat_subnet_ids  = [google_compute_subnetwork.psc_nat_subnet.id]

  depends_on = [
    google_compute_subnetwork.proxy_only_subnet,
    google_compute_subnetwork.psc_nat_subnet,
  ]
}

# ==============================================================================
# 4. Tier 1: External Ingress Gateway Module (Global External ALB)
# ==============================================================================

module "tier1_external_gateway" {
  source = "./modules/tier1_external_gateway"

  project_id     = var.project_id
  gateway_name   = "gemini-ingress-gw"
  primary_domain = var.primary_domain

  agents = {
    for k, v in var.agents : k => {
      host                  = v.host
      service_attachment_id = module.tier2_agent_producer[k].service_attachment_id
      region                = v.region
    }
  }

  depends_on = [module.tier2_agent_producer]
}

# Global Backend Service for the Authz Extension (EXTERNAL_MANAGED for Tier 1 Global External ALB)
resource "google_compute_backend_service" "agent_authz_global_backend" {
  name                  = "${var.service_name}-global-backend"
  project               = var.project_id
  protocol              = "HTTP2"
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.serverless_neg.id
  }
}

# ==============================================================================
# 5. Global Service Extension (ext_proc) Attached to Tier 1 Global External ALB
# ==============================================================================

resource "google_network_services_lb_traffic_extension" "agw_ingress_traffic_ext" {
  name                  = "agw-ingress-traffic-ext-v2"
  project               = var.project_id
  location              = "global"
  description           = "Custom Authz & Payload Inspection Service Extension for Ingress Gateway"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  forwarding_rules      = [module.tier1_external_gateway.forwarding_rule_id]

  extension_chains {
    name = "custom-authz-chain"

    match_condition {
      cel_expression = "true"
    }

    extensions {
      name      = "custom-authz-cloud-run"
      service   = google_compute_backend_service.agent_authz_global_backend.id
      authority = replace(google_cloud_run_v2_service.agent_authz_gateway.uri, "https://", "")
      fail_open = false
      timeout   = "5s"
      supported_events = [
        "REQUEST_HEADERS"
      ]
    }
  }
}
