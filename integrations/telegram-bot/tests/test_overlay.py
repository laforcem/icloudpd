import io

from bot.overlay import label
from bot.placeholder import PLACEHOLDER_JPEG
from PIL import Image


def _size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


def test_label_returns_a_jpeg_of_the_same_size_with_the_badge_drawn() -> None:
    out = label(PLACEHOLDER_JPEG, 7, False)
    assert out != PLACEHOLDER_JPEG
    image = Image.open(io.BytesIO(out))
    assert image.format == "JPEG"
    assert image.size == _size(PLACEHOLDER_JPEG)


def test_video_badge_differs_from_photo_badge() -> None:
    assert label(PLACEHOLDER_JPEG, 8, True) != label(PLACEHOLDER_JPEG, 8, False)


def test_different_numbers_draw_differently() -> None:
    assert label(PLACEHOLDER_JPEG, 1, False) != label(PLACEHOLDER_JPEG, 10, False)


def test_unreadable_image_is_returned_unchanged() -> None:
    assert label(b"not a jpeg", 3, True) == b"not a jpeg"
