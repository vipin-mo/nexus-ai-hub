variable "region" {
  description = "AWS region. The account's organisation policy only allows us-east-2."
  type        = string
  default     = "us-east-2"
}

variable "instance_type" {
  description = "ARM (Graviton) instance; 16 GB fits Ollama with qwen2.5:3b plus the seven services."
  type        = string
  default     = "t4g.xlarge"
}

variable "ami_id" {
  description = "Override the Ubuntu 24.04 arm64 image. Empty = latest Canonical image."
  type        = string
  default     = ""
}

variable "volume_gb" {
  description = "Root volume size (images, models, databases)."
  type        = number
  default     = 50
}

variable "repo_url" {
  type    = string
  default = "https://github.com/vipin-mo/nexus-ai-hub.git"
}

variable "git_ref" {
  description = "Branch or tag to deploy."
  type        = string
  default     = "main"
}

variable "ssh_cidr" {
  description = "Optional CIDR (e.g. 203.0.113.7/32) allowed to SSH. Empty = no inbound rules; use Session Manager."
  type        = string
  default     = ""
}

variable "key_name" {
  description = "Optional EC2 key pair name, only needed with ssh_cidr."
  type        = string
  default     = ""
}

variable "auto_stop_hours" {
  description = "Stop the instance this many hours after every boot (cost guard). 0 = never."
  type        = number
  default     = 3
  validation {
    condition     = var.auto_stop_hours >= 0 && var.auto_stop_hours <= 24
    error_message = "auto_stop_hours must be between 0 and 24."
  }
}

variable "budget_email" {
  description = "Optional email for a monthly cost budget. Empty = no budget and no budget action."
  type        = string
  default     = ""
}

variable "budget_usd" {
  description = "Monthly budget, measured before credits. Email at 80%; the instance is stopped at 100%."
  type        = number
  default     = 10
}

variable "budget_stop_action" {
  description = "Let AWS Budgets stop the instance when actual spend reaches budget_usd."
  type        = bool
  default     = true
}
