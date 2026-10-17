variable "project_id" {
  description = "GCP Project ID for Supply Planner Control Tower"
  type        = string
}

variable "region" {
  description = "Primary GCP deployment region"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Name of the Cloud Run service"
  type        = string
  default     = "supply-planner-agent"
}

variable "environment" {
  description = "Deployment environment (production, staging, development)"
  type        = string
  default     = "production"
}

variable "container_image" {
  description = "Full Docker container image URI"
  type        = string
  default     = "us-central1-docker.pkg.dev/enterprise-supply/supply-planner-agent-repo/supply-planner-agent:latest"
}

variable "min_instances" {
  description = "Minimum warm Cloud Run instances"
  type        = number
  default     = 1
}

variable "max_instances" {
  description = "Maximum autoscaled Cloud Run instances"
  type        = number
  default     = 10
}
