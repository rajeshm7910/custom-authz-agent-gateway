output "anycast_ip_address" {
  description = "Global Anycast IP address of Tier 1 External Application Load Balancer"
  value       = google_compute_global_address.tier1_anycast_ip.address
}

output "forwarding_rule_id" {
  description = "ID of Tier 1 Global Forwarding Rule"
  value       = google_compute_global_forwarding_rule.tier1_forwarding_rule.id
}

output "url_map_id" {
  description = "ID of Tier 1 Global URL Map"
  value       = google_compute_url_map.tier1_url_map.id
}

output "ssl_certificate_id" {
  description = "ID of SSL certificate configured on Tier 1"
  value       = google_compute_ssl_certificate.tier1_ssl_cert.id
}
