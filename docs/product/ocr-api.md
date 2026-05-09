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
