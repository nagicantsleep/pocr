import numpy as np

from app.services.ocr_engine import normalize_ocr_results


def test_normalize_paddleocr_35_result_with_dt_polys():
    raw_results = [
        {
            "rec_texts": ["NO.", "合計"],
            "rec_scores": [0.98, 0.91],
            "dt_polys": [
                np.array([[10, 20], [60, 20], [60, 40], [10, 40]], dtype=np.int16),
                np.array([[100, 120], [180, 120], [180, 150], [100, 150]], dtype=np.int16),
            ],
        }
    ]

    result = normalize_ocr_results(
        raw_results=raw_results,
        original_width=200,
        original_height=200,
        lang="japan",
        min_confidence=0.0,
        include_polygon=True,
        inference_time_ms=123,
    )

    assert result["summary"]["total_lines"] == 2
    assert result["summary"]["total_characters"] == 5
    assert result["results"][0]["text"] == "NO."
    assert result["results"][0]["bbox"] == {
        "top_left": [10.0, 20.0],
        "bottom_right": [60.0, 40.0],
    }
    assert result["results"][0]["bbox_normalized"] == {
        "top_left": [0.05, 0.1],
        "bottom_right": [0.3, 0.2],
    }
    assert result["results"][0]["polygon"] == [
        [10.0, 20.0],
        [60.0, 20.0],
        [60.0, 40.0],
        [10.0, 40.0],
    ]


def test_normalize_paddleocr_35_result_filters_confidence():
    raw_results = [
        {
            "rec_texts": ["keep", "drop"],
            "rec_scores": [0.9, 0.2],
            "dt_polys": [
                [[0, 0], [10, 0], [10, 10], [0, 10]],
                [[20, 20], [30, 20], [30, 30], [20, 30]],
            ],
        }
    ]

    result = normalize_ocr_results(
        raw_results=raw_results,
        original_width=100,
        original_height=100,
        lang="en",
        min_confidence=0.5,
        include_polygon=False,
        inference_time_ms=1,
    )

    assert [item["text"] for item in result["results"]] == ["keep"]
    assert "polygon" not in result["results"][0]
    assert result["summary"]["avg_confidence"] == 0.9
