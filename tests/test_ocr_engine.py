import sys
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from app.services import ocr_engine


def test_get_ocr_engine_maps_ja_to_installed_japanese_model_name():
    ocr_engine._ocr_engines.clear()

    paddle_ocr = MagicMock()
    with patch.dict(sys.modules, {"paddleocr": SimpleNamespace(PaddleOCR=paddle_ocr)}):
        ocr_engine.get_ocr_engine("ja")

    assert paddle_ocr.call_args.kwargs["lang"] == "japan"
    ocr_engine._ocr_engines.clear()


def test_get_ocr_engine_maps_auto_default_ja_to_installed_japanese_model_name():
    ocr_engine._ocr_engines.clear()

    paddle_ocr = MagicMock()
    settings = SimpleNamespace(MODEL_LANG="ja", PADDLE_DEVICE="cpu")
    with patch.object(ocr_engine, "get_settings", return_value=settings), patch.dict(
        sys.modules, {"paddleocr": SimpleNamespace(PaddleOCR=paddle_ocr)}
    ):
        ocr_engine.get_ocr_engine("auto")

    assert paddle_ocr.call_args.kwargs["lang"] == "japan"
    ocr_engine._ocr_engines.clear()


def test_gpu_fallback_maps_auto_default_ja_to_installed_japanese_model_name():
    ocr_engine._ocr_engines.clear()
    ocr_engine._cpu_fallback_engines.clear()
    ocr_engine._ocr_engines["japan"] = MagicMock(
        ocr=MagicMock(side_effect=RuntimeError("CUDA out of memory"))
    )
    cpu_engine = MagicMock(ocr=MagicMock(return_value=[]))
    paddle_ocr = MagicMock(return_value=cpu_engine)
    settings = SimpleNamespace(MODEL_LANG="ja", PADDLE_DEVICE="gpu")
    image = Image.new("RGB", (1, 1), color="white")
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")

    with patch.object(ocr_engine, "get_settings", return_value=settings), patch.dict(
        sys.modules, {"paddleocr": SimpleNamespace(PaddleOCR=paddle_ocr)}
    ), patch.object(ocr_engine, "normalize_ocr_results", return_value={}):
        ocr_engine.run_ocr(image_bytes.getvalue(), lang="auto")

    assert paddle_ocr.call_args.kwargs == {"lang": "japan", "device": "cpu"}
    ocr_engine._ocr_engines.clear()
    ocr_engine._cpu_fallback_engines.clear()
