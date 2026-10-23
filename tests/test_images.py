"""Image preparation on synthetic images only; no receipt photo enters the tests."""

import io
import struct
import zlib

import pytest
from PIL import ExifTags, Image

from retail_receipts_import.adapters.gemini.images import UnreadableImage, prepare

RED = (255, 0, 0)
ORIENTATION = ExifTags.Base.Orientation


def marked_image(
    fmt: str, size: tuple[int, int] = (40, 20), orientation: int | None = None
) -> bytes:
    """A white image with a red square in its stored top-left corner."""
    image = Image.new("RGB", size, "white")
    image.paste(RED, (0, 0, 8, 8))
    exif = Image.Exif()
    if orientation is not None:
        exif[ORIENTATION] = orientation
    out = io.BytesIO()
    image.save(out, format=fmt, exif=exif, quality=95)
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def is_red(pixel: object) -> bool:
    assert isinstance(pixel, tuple)
    red, green, blue = pixel[:3]
    return bool(red > 200 and green < 60 and blue < 60)


def test_pdf_is_passed_byte_identical() -> None:
    data = b"%PDF-1.7 not even a real pdf"
    assert prepare(data, "application/pdf", 10) is data


FORMATS = [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")]


@pytest.mark.parametrize(("fmt", "mime"), FORMATS)
def test_upright_image_within_the_cap_is_the_original(fmt: str, mime: str) -> None:
    data = marked_image(fmt)
    assert prepare(data, mime, 800) is data
    tagged = marked_image(fmt, orientation=1)
    assert prepare(tagged, mime, 800) is tagged


def test_rotated_photo_is_made_upright_and_capped() -> None:
    data = marked_image("JPEG", size=(400, 200), orientation=6)
    prepared = opened(prepare(data, "image/jpeg", 20_000))
    assert prepared.format == "JPEG"
    # Orientation 6 means "turn 90 degrees clockwise to view": landscape becomes portrait,
    # and the marked top-left corner ends top-right.
    assert prepared.height > prepared.width
    assert prepared.width * prepared.height <= 20_000
    assert prepared.getexif().get(ORIENTATION, 1) == 1
    assert is_red(prepared.getpixel((prepared.width - 2, 1)))
    assert not is_red(prepared.getpixel((1, 1)))


@pytest.mark.parametrize(("fmt", "mime"), FORMATS)
def test_large_image_is_scaled_down_in_its_own_format(fmt: str, mime: str) -> None:
    prepared = opened(prepare(marked_image(fmt, size=(100, 50)), mime, 1250))
    assert prepared.format == fmt
    assert prepared.size == (50, 25)


def test_rotated_webp_is_made_upright() -> None:
    prepared = opened(prepare(marked_image("WEBP", orientation=6), "image/webp", 16_000_000))
    assert prepared.format == "WEBP"
    assert prepared.size == (20, 40)
    assert is_red(prepared.getpixel((prepared.width - 2, 1)))


def test_oversized_text_chunk_is_unreadable() -> None:
    plain = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(plain, format="PNG")
    payload = b"Comment\x00\x00" + zlib.compress(b"A" * 20_000_000)
    chunk = struct.pack(">I", len(payload)) + b"zTXt" + payload
    chunk += struct.pack(">I", zlib.crc32(b"zTXt" + payload))
    data = plain.getvalue()
    # After the signature and the header chunk, as a text chunk may stand.
    with pytest.raises(UnreadableImage):
        prepare(data[:33] + chunk + data[33:], "image/png", 16_000_000)


def test_truncated_jpeg_is_unreadable() -> None:
    data = marked_image("JPEG", size=(200, 100))
    with pytest.raises(UnreadableImage):
        prepare(data[: len(data) // 2], "image/jpeg", 16_000_000)


def test_bytes_that_are_no_image_are_unreadable() -> None:
    with pytest.raises(UnreadableImage):
        prepare(b"not an image", "image/png", 16_000_000)


def test_other_formats_are_not_decoded() -> None:
    gif = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(gif, format="GIF")
    with pytest.raises(UnreadableImage):
        prepare(gif.getvalue(), "image/png", 16_000_000)


def test_decompression_bomb_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pillow refuses an image above twice this many pixels before decoding it.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(UnreadableImage, match="DecompressionBombError"):
        prepare(marked_image("PNG"), "image/png", 16_000_000)
