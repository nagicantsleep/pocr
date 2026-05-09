# US-001 CPU OCR Fixtures Return Text

## Status

implemented

## Lane

normal

## Product Contract

CPU deployment OCR requests using the repository fixture images return detected
text lines instead of a successful response with an empty `results` array.

## Relevant Product Docs

- `docs/product/ocr-api.md`

## Acceptance Criteria

- The OCR engine sends PaddleOCR 3.5.x a supported image input type.
- PaddleOCR 3.5.x dictionary output with `rec_texts`, `rec_scores`, and
  `dt_polys` is normalized into API `results`.
- The CPU deployment returns non-empty results for `tests/fixtures/img*.png`.

## Design Notes

- API: response shape remains unchanged.
- Domain rules: fixture OCR output should produce positive line and character
  counts.
- Runtime: CPU container uses PaddleOCR 3.5.0 and PaddlePaddle 3.2.2.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | Normalize a PaddleOCR 3.5-style dictionary with `dt_polys`. |
| Integration | Compile app and tests in the CPU image environment. |
| E2E | Not applicable; API-only change. |
| Platform | Rebuild CPU container and call `/ocr` with fixture images. |
| Release | Not run. |

## Harness Delta

No harness process change was needed.

## Evidence

- `docker run --rm -v ${PWD}:/work -w /work pocr-ocr-api-cpu python -m compileall app tests`
- `docker run --rm -v ${PWD}:/work -w /work pocr-ocr-api-cpu python -c "... normalize_ocr_results ..."`
- `docker compose -f docker-compose.cpu.yml up -d --build ocr-api-cpu`
- `curl.exe -s -X POST http://localhost:8000/ocr -F "file=@tests/fixtures/img1.png" -H "X-Lang: japan"` returned 27 lines and 118 characters.
- All fixture smoke results after rebuild:

| Fixture | Lines | Characters |
| --- | ---: | ---: |
| `img1.png` | 27 | 118 |
| `img2.png` | 27 | 90 |
| `img3.png` | 27 | 118 |
| `img4.png` | 47 | 193 |
| `img5.png` | 34 | 180 |
| `img6.png` | 28 | 188 |
| `img7.png` | 24 | 186 |
