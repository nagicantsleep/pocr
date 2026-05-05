import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def sample_image_bytes():
    # Create a minimal valid JPEG image in memory
    from io import BytesIO
    from PIL import Image
    img = Image.new('RGB', (100, 50), color=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()

@pytest.fixture
def sample_text_image_bytes():
    # Create an image with some dark pixels (simulating text)
    from io import BytesIO
    from PIL import Image
    img = Image.new('RGB', (200, 100), color=(255, 255, 255))
    # Draw some text-like dark pixels
    pixels = img.load()
    for x in range(50, 150):
        for y in range(30, 70):
            pixels[x, y] = (0, 0, 0)
    buf = BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()

@pytest.fixture
def blank_image_bytes():
    from io import BytesIO
    from PIL import Image
    img = Image.new('RGB', (100, 100), color=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()