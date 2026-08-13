output "service_attachment_id" {
  description = "The ID / URI of the published PSC Service Attachment"
  value       = google_compute_service_attachment.agent_service_attachment.id
}

output "forwarding_rule_id" {
  description = "The ID of the Tier 2 Regional Forwarding Rule"
  value       = google_compute_forwarding_rule.agent_forwarding_rule.id
}

output "backend_service_id" {
  description = "The ID of the Tier 2 Regional Backend Service"
  value       = google_compute_region_backend_service.agent_backend_service.id
}

output "url_map_id" {
  description = "The ID of the Tier 2 Regional URL Map"
  value       = google_compute_region_url_map.agent_url_map.id
}

output "target_http_proxy_id" {
  description = "The ID of the Tier 2 Regional Target HTTP Proxy"
  value       = google_compute_region_target_http_proxy.agent_target_http_proxy.id
}
