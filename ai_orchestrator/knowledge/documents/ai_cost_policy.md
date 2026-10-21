# AI Cost and Vendor Policy

*Synthetic policy for the NexusAI demo. Owner: FinOps.*

## Budgets
The monthly budget for external AI model APIs is $500 per team. Spending above 80% of the budget
triggers an alert to the team lead. Any single workload expected to cost more than $50 per month
needs FinOps approval before launch.

## Cost controls
- Prefer local models for classification and routing; they have zero marginal cost.
- Every service that calls a paid model must enforce a hard spend cap per process.
- Token usage and cost must be recorded per request, by route and by model, and reviewed weekly
  on the operations dashboard.

## Vendor review
New AI vendors require a security review and a data processing agreement. Vendor contracts are
reviewed every 12 months.
