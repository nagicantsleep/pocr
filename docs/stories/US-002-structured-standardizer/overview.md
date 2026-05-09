# US-002 Structured OCR Standardizer

## Status

implemented

## Lane

high-risk

## Reason

This introduces optional external LLM provider behavior for structured output.
The default provider remains local heuristic extraction.

## Outcome

The service keeps PaddleOCR as the evidence extractor and adds a standardizer
boundary that produces `sample.json`-compatible structured data with
`inputCostItems`.

## Product Contract

Structured output must contain only information supported by OCR evidence from
the source image. Missing fields are omitted from the response or represented as
empty arrays for collection fields.
