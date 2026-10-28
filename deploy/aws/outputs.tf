output "instance_id" {
  value = aws_instance.nexus.id
}

output "bootstrap_log" {
  description = "Follow the first-boot install (about 8 minutes on m7i-flex.large)."
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

output "public_ip" {
  description = "Run in CloudShell after each start; the address changes on every stop/start."
  value       = "aws ec2 describe-instances --region ${var.region} --instance-ids ${aws_instance.nexus.id} --query 'Reservations[0].Instances[0].PublicIpAddress' --output text"
}

output "ssh_tunnel" {
  description = "Run on your laptop (with ssh_cidr and ssh_public_key set), then open http://localhost:8501"
  value       = "ssh -i ~/.ssh/nexus-ai -N -L 8501:localhost:8501 -L 8080:localhost:8080 -L 5001:localhost:5001 ubuntu@<PUBLIC_IP>"
}
