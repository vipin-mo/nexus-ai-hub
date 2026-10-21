# Data Retention and Privacy Policy

*Synthetic policy for the NexusAI demo. Owner: Privacy Office.*

## Retention periods
| Data | Store | Retention |
|---|---|---|
| Assistant conversation memory | MongoDB | 30 days, then deleted automatically by a TTL index |
| Security audit ledger | PostgreSQL | 1 year, append-only |
| Raw application logs | Data lake landing zone | 14 days |
| Sanitized logs and aggregated KPIs | Data lake (Parquet) / DuckDB warehouse | 13 months |
| Audio recordings | Audio inbox | Deleted after transcription; transcripts follow conversation retention |

## Personally identifiable information (PII)
PII includes names, email addresses, phone numbers, government identifiers such as Social Security
numbers, payment card numbers and IP addresses. PII must be redacted before data reaches the
analytics warehouse, model-training datasets, or any third-party (cloud) model provider.
Redaction replaces the value with a typed placeholder such as `<EMAIL>` or `<PERSON>`.

## Data subject requests
Requests to delete a person's data must be completed within 30 days. Because conversation memory
expires after 30 days, deletion requests mainly apply to the audit ledger, which stores only a SHA-256
hash of each query rather than the query text.

## Cross-border transfers
Customer data stays in the US region. Sending unredacted customer data to an external AI provider is
prohibited.
