# Operations Tool Catalog Guide

*Synthetic guide for the NexusAI demo. Owner: Internal Tools.*

| Tool | Purpose | Minimum role |
|---|---|---|
| `POSTGRES_EXPORT` | Export query results from the operational database to CSV | ANALYST |
| `JIRA_TICKET_GEN` | Create a Jira ticket from a description | ANALYST |
| `DASHBOARD_SNAPSHOT` | Capture a PDF snapshot of a BI dashboard | ANALYST |
| `LOG_SEARCH` | Search sanitized application logs | ANALYST |
| `COST_REPORT` | Generate the weekly AI spend report | ANALYST |
| `ONCALL_PAGE` | Page the on-call engineer | ANALYST |
| `SECURITY_AUDIT_LOG_FREEZE` | Freeze audit log rotation during an investigation | ADMIN |
| `REFUND_DISPATCH` | Issue a customer refund (requires HITL approval) | ADMIN |
| `ACCESS_REVIEW` | Start a quarterly access review | ADMIN |
| `KEY_ROTATION` | Rotate an API client key | ADMIN |

Ask the assistant "which tool should I use to ..." to get recommendations. Recommendations combine
how relevant a tool is to your request with which tools people in similar roles use together.
