output "instance_id" {
  value = aws_instance.nexus.id
}

output "bootstrap_log" {
  description = "Follow the first-boot install (about 20-30 minutes)."
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.nexus.id} # then: sudo tail -f /var/log/nexus-bootstrap.log"
}

output "dashboard" {
  description = "Run locally, then open http://localhost:8501"
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.nexus.id} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"8501\"],\"localPortNumber\":[\"8501\"]}'"
}

output "gateway" {
  description = "Run locally, then call http://localhost:8080/api/v1"
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.nexus.id} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"8080\"],\"localPortNumber\":[\"8080\"]}'"
}

output "stop" {
  description = "Stop between demos: only the disk is billed while stopped."
  value       = "aws ec2 stop-instances --region ${var.region} --instance-ids ${aws_instance.nexus.id}"
}

output "start" {
  value = "aws ec2 start-instances --region ${var.region} --instance-ids ${aws_instance.nexus.id}"
}
