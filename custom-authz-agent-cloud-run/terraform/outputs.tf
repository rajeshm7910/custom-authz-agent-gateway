output "global_anycast_ip" {
  description = "Public Anycast IPv4 address of the Tier 1 Global Load Balancer"
  value       = google_compute_global_address.alb_anycast_ip.address
}

output "authz_cloud_run_url" {
  description = "URI of the Cloud Run Custom Authz Service"
  value       = google_cloud_run_v2_service.agent_authz.uri
}

output "backend_agent_cloud_run_url" {
  description = "URI of the Cloud Run Backend Agent (adk-agent-app)"
  value       = google_cloud_run_v2_service.adk_agent_backend.uri
}

output "forwarding_rule_id" {
  description = "ID of the Global HTTPS Forwarding Rule"
  value       = google_compute_global_forwarding_rule.agent_forwarding_rule.id
}

output "service_extension_name" {
  description = "Name of the LB Traffic Extension"
  value       = google_network_services_lb_traffic_extension.custom_authz_ext.name
}

output "gateway_endpoint" {
  description = "Ingress HTTPS endpoint for testing"
  value       = "https://${google_compute_global_address.alb_anycast_ip.address}/chat"
}
