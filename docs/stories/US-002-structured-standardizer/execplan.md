# Exec Plan

## Steps

1. Align Pydantic structured data models with `sample.json`.
2. Add provider-neutral standardizer boundary.
3. Keep a local default provider for tests and offline use.
4. Add optional OpenAI-compatible provider configuration.
5. Validate structured output through Pydantic before response emission.
6. Produce raw and structured fixture outputs through the running API.

## Non-Goals

- Do not infer fields that are absent from OCR evidence.
- Do not add vendor lookup or internal ID enrichment.
- Do not make an external LLM call unless explicitly configured.
