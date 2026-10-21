# Incident Response Runbook

*Synthetic runbook for the NexusAI demo. Owner: Site Reliability Engineering.*

## Severity levels
- **SEV1** - full outage or confirmed data breach. Page the on-call engineer immediately; the incident
  commander must acknowledge within 5 minutes. Executive and legal notification within 1 hour.
- **SEV2** - major feature degraded (for example the AI assistant answering with errors for more than
  10% of requests). Acknowledge within 15 minutes.
- **SEV3** - minor degradation with a workaround. Handle within 1 business day.

## First steps
1. Declare the incident in the #incidents channel and assign an incident commander.
2. Freeze deployments using the change-freeze tool.
3. If a security breach is suspected, trigger `SECURITY_AUDIT_LOG_FREEZE` so audit records cannot be
   rotated while the investigation runs.
4. Capture timelines in the incident document; do not delete logs.

## Post-incident review
A blameless post-incident review is required for every SEV1 and SEV2 within 5 business days.
Action items must have an owner and a due date.

## AI-specific incidents
If the assistant leaks PII, follows a prompt injection, or produces a harmful action plan, treat it as
SEV2 at minimum. Disable cloud model routing (set the reasoner provider to the local model) until the
review is complete.
