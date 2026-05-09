# Design

## Flow

```text
image
  -> PaddleOCR
  -> normalized OCR evidence
  -> standardizer provider
  -> StructuredOCRData validation
  -> StructuredOCRResponse
```

## Providers

- `heuristic`: default local parser, no external dependency.
- `mock`: alias for the local heuristic parser.
- `none`: alias for the local heuristic parser.
- `openrouter`: optional OpenRouter OpenAI-compatible chat-completions adapter
  using `STANDARDIZER_API_KEY`.
- `openai`: optional direct OpenAI Responses API adapter using
  `STANDARDIZER_API_KEY`.

## OpenRouter Defaults

- `STANDARDIZER_BASE_URL=https://openrouter.ai/api/v1`
- `STANDARDIZER_MODEL=openrouter/owl-alpha`

`openrouter/owl-alpha` was selected as a free test model because OpenRouter's
public model metadata currently marks it with zero prompt/completion pricing
and structured output support. The model can be changed through
`STANDARDIZER_MODEL`.

## Schema

The downstream data schema follows `sample.json`:

- `title`
- `originalNumber`
- `inputCostType`
- `issueDate`
- `paymentDate`
- `vendorName`
- `paymentMethod`
- `description`
- `totalAmount`
- `taxes`
- `inputCostItems`

Removed from structured data output:

- `vendorId`
- `vendorCode`
- `inputCostImages`

Those are not guaranteed to exist in the source image and should be handled by
downstream enrichment when needed.
