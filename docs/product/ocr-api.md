# OCR API

## Contract

The REST API accepts image uploads or base64 image payloads and returns a
successful OCR response with normalized text results, confidence scores,
bounding boxes, optional polygons, metadata, and summary counts.

For PaddleOCR 3.5.x, the OCR engine receives image input as a decoded RGB
`numpy.ndarray`, not raw encoded image bytes. Raw bytes are not a supported
PaddleOCR input type and must not be passed to the engine.

PaddleOCR 3.5.x result dictionaries may expose recognized text in `rec_texts`,
scores in `rec_scores`, and polygons in `dt_polys`. The API normalizes this
shape into the public `results[]` response.

## CPU Deployment Fixture Expectation

The CPU container must return non-empty OCR results for the fixture images in
`tests/fixtures/img*.png` when called with Japanese OCR language.

## Structured Output Boundary

The OCR service extracts evidence from images. It must not invent business
fields that are not present in the image.

The downstream structured JSON shape is represented by `sample.json`. Structured
output should contain only information supported by OCR/VLM evidence from the
source image. Fields that cannot be found in the image should be `null` or
omitted according to the downstream schema, not guessed.

The intended production flow is:

```text
image
  -> PaddleOCR OCR/VLM evidence extraction
  -> LLM standardizer for sample.json-compatible fields
  -> schema validation
  -> downstream JSON
```

PaddleOCR remains the extraction layer. The LLM standardizer is responsible for
mapping extracted evidence into the downstream contract, including enum labels,
dates, amounts, taxes, and `inputCostItems`.

The default standardizer provider is `heuristic`, which makes no external calls.
`STANDARDIZER_PROVIDER=openrouter` enables the OpenRouter OpenAI-compatible
chat-completions adapter. `STANDARDIZER_PROVIDER=openai` enables the direct
OpenAI Responses adapter. Both adapters request JSON schema output and the
service validates the returned JSON with Pydantic before responding.
