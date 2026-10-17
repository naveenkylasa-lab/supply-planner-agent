output "cloud_run_service_url" {
  description = "Public HTTPS URL of the Supply Planner Multi-Agent Control Tower"
  value       = google_cloud_run_v2_service.supply_planner_service.uri
}

output "artifact_registry_repository" {
  description = "Artifact Registry repository ID"
  value       = google_artifact_registry_repository.supply_planner_repo.id
}

output "runtime_service_account_email" {
  description = "Least-privilege IAM Service Account email"
  value       = google_service_account.supply_planner_sa.email
}
