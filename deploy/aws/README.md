# Deploying to AWS (one EC2 instance)

The whole stack runs on one Graviton instance with Docker Compose, the same as on a laptop, with
Ollama on the host. There is no load balancer, NAT gateway or EKS cluster: for a demo they would
cost more per month than the instance itself.

```
your laptop ──Session Manager port forward──▶ EC2 t4g.xlarge (default VPC, no inbound ports)
                                               ├─ Ollama: qwen2.5:3b, nomic-embed-text
                                               └─ Docker Compose: 7 services, all on 127.0.0.1
```

| Resource | Why |
|---|---|
| `t4g.xlarge` (4 vCPU, 16 GB, ARM) | Ollama plus seven services need about 10 GB; ARM matches the images built on Apple silicon and is cheaper per GB |
| Security group with no inbound rules | Access is through Session Manager, so nothing is exposed; SSH is opt-in (`ssh_cidr`) |
| IAM role with `AmazonSSMManagedInstanceCore` only | Lets Session Manager reach the instance; no other AWS permissions |
| Encrypted 50 GB gp3 root volume, IMDSv2 only | Images, models and databases; blocks the old metadata API |
| Auto-stop `auto_stop_hours` (default 3) after every boot | A forgotten instance stops itself; shutdown means stop, never terminate |
| Optional monthly budget (`budget_email`) with a stop action | Email at 80% of `budget_usd`; at 100% AWS Budgets stops the instance |

Secrets are generated on the instance at first boot (`scripts/generate_env.sh`) and never leave it.
Claude is off: no Anthropic key is deployed.

## Cost (us-east-2, on-demand)

| State | Approximate cost |
|---|---|
| Running | about $0.145 per hour: instance $0.134, public IPv4 $0.005, volume $0.0055 |
| Running at full CPU | up to about $0.24 per hour: CPU above the 40% baseline adds about $0.04 per vCPU-hour (`unlimited` credits) |
| Stopped | about $4 per month for the 50 GB volume; the public IPv4 address is released |
| Destroyed | $0 |

Left running for a month, the instance would cost about $105. The guards are there for that case.

## Cost guards

AWS has no hard spending cap, so there are two layers:

1. **Auto-stop on the instance.** A systemd unit installed at the very start of first boot schedules a
   shutdown `auto_stop_hours` after every boot, and `instance_initiated_shutdown_behavior = "stop"`
   makes that a stop. One forgotten session costs at most about 3 x $0.24 = $0.72. Starting the
   instance again starts a new 3-hour window. To keep a session going on the instance:
   `sudo shutdown -c && sudo shutdown -P +120`.
2. **Budget action.** With `budget_email` set, a monthly cost budget emails at 80% and, at 100%, runs
   the AWS-StopEC2Instance automation through a role that has only the AWS managed policy for budget
   actions. The budget measures usage **before credits**; by default budgets subtract credits, so
   with $100 of credits the actual cost would stay at $0 and nothing would fire. This is a backstop:
   billing data lags by several hours, and the action runs once per budget period.

Stop or destroy between demos:

| | Stop and start | Destroy and apply again |
|---|---|---|
| Idle cost | about $4 per month | $0 |
| Ready in | 2-3 minutes | 20-30 minutes (full first boot) |
| Data and API keys | kept | wiped; new keys in `/opt/nexus/.env` |

Stop between demos in a week with interviews; destroy if it will be idle for more than about a week.

## Deploy from AWS CloudShell

CloudShell already has credentials for the account. Terraform is installed into `~/bin` because
CloudShell keeps only the home directory between sessions. The home directory is limited to 1 GB and
the AWS provider plugin alone is several hundred MB, so `TF_DATA_DIR` puts the plugins in `/tmp`.

```bash
mkdir -p ~/bin && cd ~/bin
V=1.17.0; A=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
curl -fsSLO https://releases.hashicorp.com/terraform/$V/terraform_${V}_linux_$A.zip
unzip -o terraform_${V}_linux_$A.zip terraform && rm terraform_${V}_linux_$A.zip
export PATH=~/bin:$PATH TF_DATA_DIR=/tmp/nexus-tf

cd ~ && git clone https://github.com/vipin-mo/nexus-ai-hub.git && cd nexus-ai-hub/deploy/aws
terraform init
terraform plan -var budget_email=you@example.com
terraform apply -var budget_email=you@example.com
```

The state file stays in `~/nexus-ai-hub/deploy/aws/` in CloudShell. Keep it: `terraform destroy`
needs it. (CloudShell deletes home directories after 120 days without use.) `/tmp` is cleared when a
session ends, so in a new session run this before any other `terraform` command:

```bash
export PATH=~/bin:$PATH TF_DATA_DIR=/tmp/nexus-tf && cd ~/nexus-ai-hub/deploy/aws && terraform init
```

First boot installs Docker and Ollama, pulls the models and builds the images. That takes about 20 to
30 minutes. To watch it:

```bash
aws ssm start-session --region us-east-2 --target "$(terraform output -raw instance_id)"
sudo tail -f /var/log/nexus-bootstrap.log     # finished when it prints "nexus bootstrap finished"
```

## Use it from your laptop

Install the AWS CLI and the
[Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html),
and sign in to the account. Then run `terraform output dashboard` (or `gateway`) and paste the
command. It forwards the port to your laptop, and the dashboard opens at http://localhost:8501.

To run the demo script on the instance:

```bash
cd /opt/nexus && sudo -u ubuntu make demo
```

## Stop, start, destroy

```bash
terraform output -raw stop | sh       # between demos; containers come back on start
terraform output -raw start | sh
terraform destroy                     # removes everything, including the databases
```

## If something is blocked

The account belongs to an organisation whose policies deny some actions (only us-east-2 is open).
If `apply` fails with `explicit deny in a service control policy`:

- On `budgets:*`: leave out `budget_email` and set a budget in the Billing console instead. If only
  the budget action is denied, keep the budget and add `-var budget_stop_action=false`.
- If Session Manager does not connect: apply with `-var ssh_cidr=$(curl -s https://checkip.amazonaws.com)/32
  -var key_name=<an EC2 key pair>` and use `ssh -L 8501:localhost:8501 ubuntu@<public IP>`.
