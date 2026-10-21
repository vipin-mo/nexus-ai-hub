# Responsible AI Usage Policy

*Synthetic policy for the NexusAI demo. Owner: AI Governance Board.*

## Approved models
- Local models served by Ollama (for example Qwen 2.5) are approved for classification, routing,
  security screening and general answers. They run on company hardware and data never leaves the host.
- Anthropic Claude models are approved for complex reasoning, but only with PII-redacted input.

## Routing rule
Requests are routed to the cheapest capable model. A trained intent classifier handles routing; the
local LLM is consulted only when the classifier's confidence is below the threshold. Cloud models are
used for the answer step only when the reasoner provider is configured for them.

## Human oversight
AI output that triggers a financial action, a customer-facing message or a production change must be
reviewed by a person. Model answers must cite the internal documents they are based on.

## Evaluation before release
Every prompt or model change must pass the offline evaluation suite before it is merged: retrieval
hit rate, answer fact recall, routing accuracy and security block rate are compared with thresholds in
CI. A change that lowers any metric below its threshold is blocked.

## Prompt injection
User text is treated as data, never as instructions. Requests that try to override system rules,
reveal hidden prompts or extract credentials are blocked and logged.
