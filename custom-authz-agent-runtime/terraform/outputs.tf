output "tier1_anycast_ip" {
  description = "Tier 1 Global External Application Load Balancer Anycast Public IP"
  value       = module.tier1_external_gateway.anycast_ip_address
}

output "tier1_url_map_id" {
  description = "Tier 1 Global URL Map ID"
  value       = module.tier1_external_gateway.url_map_id
}

output "tier2_service_attachments" {
  description = "Published Tier 2 PSC Service Attachments per agent"
  value = {
    for k, v in module.tier2_agent_producer : k => v.service_attachment_id
  }
}

output "cloud_run_authz_service_uri" {
  description = "URI of Cloud Run Authz & Model Armor Service Extension"
  value       = google_cloud_run_v2_service.agent_authz_gateway.uri
}

output "traffic_extension_id" {
  description = "ID of the Global Service Extension (ext_proc) on Tier 1 Global ALB"
  value       = google_network_services_lb_traffic_extension.agw_ingress_traffic_ext.id
}


