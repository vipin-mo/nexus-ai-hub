variable "region" {
  description = "AWS region. The account's organisation policy only allows us-east-2."
  type        = string
  default     = "us-east-2"
}

variable "instance_type" {
  description = <<-EOT
    m7i-flex.large (2 vCPU, 8 GB, x86) is the largest type an AWS Free plan account can launch and is
    what the published evidence was measured on (with swap_gb set). On a paid account t4g.xlarge
    (4 vCPU, 16 GB, ARM) gives more headroom. The Ubuntu image architecture follows the instance type.
  EOT
  type        = string
  default     = "m7i-flex.large"
}

variable "swap_gb" {
  description = "Swap file size in GB. Needed on 8 GB instances; harmless on larger ones. 0 = none."
  type        = number
  default     = 4
}

variable "ssh_public_key" {
  description = "Your SSH public key (contents of ~/.ssh/nexus-ai.pub). Used with ssh_cidr when Session Manager is not available from your laptop."
  type        = string
  default     = ""
}

variable "ami_id" {
  description = "Override the Ubuntu 24.04 image. Empty = latest Canonical image for the instance architecture."
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
  description = "Optional CIDR allowed to SSH: your laptop's public IP + /32 (from the laptop, not CloudShell). Empty = no inbound rules."
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
