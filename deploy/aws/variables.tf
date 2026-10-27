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

variable "budget_email" {
  description = "Optional email for a monthly cost budget alert. Empty = no budget."
  type        = string
  default     = ""
}

variable "budget_usd" {
  type    = number
  default = 10
}
