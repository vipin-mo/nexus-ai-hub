# Nexus Corp Security Protocol

*Synthetic policy written for the NexusAI demo knowledge base. Version 3.2, owner: Security Engineering.*

## 1. Data storage
All relational customer metadata must reside in the primary PostgreSQL cluster (`nexus_operational`).
Customer data may not be copied to laptops, spreadsheets or personal cloud drives. Analytical copies
are allowed only in the DuckDB warehouse after PII has been redacted by the ingestion pipeline.

## 2. AI orchestration safety gates
Any destructive database write (DROP, TRUNCATE, DELETE without a WHERE clause, schema changes) or any
transactional credit execution initiated by an autonomous LLM agent requires a Human-In-The-Loop (HITL)
approval: a named engineer must review the exact statement and sign the change request before it runs.
Agents may read data on their own, but every write path must pass through the HITL queue.
Approvals expire after 4 hours.

## 3. Network access
Database nodes communicate only over isolated private network bridges using TLS 1.3. Plain-text
database connections are blocked at the firewall. Public ingress is limited to the API gateway on
port 443; internal services such as the orchestrator WebSocket port are never exposed to the internet.

## 4. Secrets
API keys and database passwords live in the secrets manager (Kubernetes Secrets in the cluster, a
local `.env` file for development). Secrets must never be committed to git or baked into container
images. Leaked keys must be revoked within 1 hour of discovery.

## 5. Vulnerability management
Critical vulnerabilities (CVSS 9.0 or higher) must be patched within 72 hours. High-severity issues
(CVSS 7.0-8.9) must be patched within 14 days. Container base images are rebuilt weekly.
