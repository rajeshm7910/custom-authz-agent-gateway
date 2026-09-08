output "cloud_run_uri" {
  description = "The direct URI of the Cloud Run gRPC Echo Service"
  value       = google_cloud_run_v2_service.grpc_echo_service.uri
}

output "load_balancer_ip" {
  description = "The External Anycast IP of the Load Balancer with Traffic Extension attached"
  value       = google_compute_global_address.grpc_echo_ip.address
}

output "traffic_extension_id" {
  description = "The ID of the configured GCP LB Traffic Extension"
  value       = google_network_services_lb_traffic_extension.grpc_echo_traffic_ext.id
}
