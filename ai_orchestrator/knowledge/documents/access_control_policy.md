# Access Control Policy

*Synthetic policy for the NexusAI demo. Owner: Identity and Access Management.*

## Roles
| Role | Who | Can do |
|---|---|---|
| `ADMIN` | Platform administrators | Query the assistant, read the audit ledger, manage API clients |
| `ANALYST` | Business and operations analysts | Query the assistant |
| `INGEST_SERVICE` | Machine identity of the audio ingestion service | Submit audio transcripts only |

Access follows least privilege: a role gets only the permissions listed above. Admin access is
reviewed every quarter.

## API keys
Every client authenticates with an API key sent in the `X-API-Key` header. The gateway stores only the
SHA-256 hash of each key. Keys must be rotated every 90 days, and a key that has been unused for 60
days is disabled.

## Tool permissions
Some operational tools are restricted by role. Refund dispatch and audit-log freezes require `ADMIN`.
Analysts may use reporting, ticketing and export tools. The assistant never recommends a tool the
caller's role is not allowed to use.

## Audit
Every request to the gateway, including rejected ones, is written to the append-only audit ledger with
the client name, role, endpoint, a hash of the query, the outcome and the latency.
