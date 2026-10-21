# Change Management Policy

*Synthetic policy for the NexusAI demo. Owner: Platform Engineering.*

## Deployment windows
Production deployments happen Monday to Thursday between 10:00 and 16:00 Central Time. No
deployments on Fridays, weekends or public holidays unless they fix a SEV1 or SEV2 incident.

## Approvals
Every production change needs a pull request with at least one approving review and a green CI
pipeline (unit tests, integration tests and the AI evaluation gate). Database migrations need a second
reviewer from the data team.

## Rollback
Each release must have a tested rollback plan. If error rates rise above 2% within 30 minutes of a
deployment, the release is rolled back first and investigated second.

## Database migrations
Schema changes are applied with Flyway migration scripts that are version-controlled. Manual schema
edits in production are prohibited.
