terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.30"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_artifact_registry_repository" "supply_planner_repo" {
  location      = var.region
  repository_id = "${var.service_name}-repo"
  description   = "Container registry for Enterprise Supply Planner Multi-Agent System"
  format        = "DOCKER"
}

resource "google_service_account" "supply_planner_sa" {
  account_id   = "${var.service_name}-sa"
  display_name = "Supply Planner Multi-Agent Runtime Service Account"
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "${var.service_name}-gemini-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "gemini_secret_access" {
  secret_id = google_secret_manager_secret.gemini_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.supply_planner_sa.email}"
}

resource "google_cloud_run_v2_service" "supply_planner_service" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.supply_planner_sa.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.container_image

      ports {
        container_port = 8010
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "FAST_MODEL_NAME"
        value = "gemini-2.0-flash"
      }
      env {
        name  = "DEEP_MODEL_NAME"
        value = "gemini-1.5-pro"
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = var.service_name
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }
    }
  }
}
