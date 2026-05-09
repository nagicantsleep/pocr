# Validation

## Expected Proof

| Layer | Proof |
| --- | --- |
| Unit | Direct standardizer validation against sample-like OCR evidence. |
| Integration | Compile app and tests in CPU image environment. |
| Platform | Rebuild CPU container and call `/ocr/structured` with fixture images. |

## Evidence

- `docker run --rm -v ${PWD}:/work -w /work pocr-ocr-api-cpu python -m compileall app tests`
- Direct standardizer validation in the CPU image passed against sample-like OCR evidence.
- `docker compose -f docker-compose.cpu.yml up -d --build ocr-api-cpu`
- `/ocr` and `/ocr/structured` were called through the running CPU container for every `tests/fixtures/img*.png`.
- Raw OCR outputs were written to `out/img*.json`.
- Structured outputs were written to `out/img*.structured.json`.
- `sample.json` validates against `StructuredOCRData`; extra downstream fields such as `vendorCode` are rejected.
- `STANDARDIZER_PROVIDER=openai` fails closed without `STANDARDIZER_API_KEY`.
- `STANDARDIZER_PROVIDER=openrouter` fails closed without `STANDARDIZER_API_KEY`.

## Fixture Result Summary

| Fixture | Raw OCR lines | Structured status | Input cost item count | Tax count |
| --- | ---: | --- | ---: | ---: |
| `img1.png` | 27 | success | 0 | 0 |
| `img2.png` | 27 | success | 0 | 0 |
| `img3.png` | 27 | success | 0 | 0 |
| `img4.png` | 47 | success | 0 | 0 |
| `img5.png` | 34 | success | 0 | 0 |
| `img6.png` | 28 | success | 0 | 1 |
| `img7.png` | 24 | success | 0 | 0 |
