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


def _jpeg(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(out, "JPEG")
    return out.getvalue()


def test_tall_thumbnail_is_cropped_to_the_collage_cell_aspect() -> None:
    # Telegram crops very tall tiles to about 2:3, which would cut the badge off.
    width, height = _size(label(_jpeg(282, 610), 4, False))
    assert width == 282
    assert width / height >= 0.65


def test_badge_survives_the_crop_in_the_top_left_corner() -> None:
    plain = Image.open(io.BytesIO(_jpeg(282, 610))).convert("RGB")
    out = Image.open(io.BytesIO(label(_jpeg(282, 610), 4, False))).convert("RGB")
    assert out.getpixel((14, 14)) != plain.getpixel((14, 14))


def test_landscape_thumbnail_keeps_its_size() -> None:
    assert _size(label(_jpeg(553, 311), 8, True)) == (553, 311)
