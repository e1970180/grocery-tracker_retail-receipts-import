"""Puts a receipt image the right way up and within a pixel budget before Gemini reads it."""

import io
import math

from PIL import ExifTags, Image, ImageOps

# Pillow format per accepted image type; a PDF is not here and is never touched.
_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class UnreadableImage(Exception):
    """The file is not an image Pillow can decode, or decoding it would exhaust memory."""


def prepare(data: bytes, mime: str, max_pixels: int) -> bytes:
    """The bytes to send: the original when already upright and small enough, else a new encoding.

    Works on a copy in memory; the saved file stays as the sender sent it.
    """
    image_format = _FORMATS.get(mime)
    if image_format is None:
        return data
    try:
        # The file comes from a chat, so only the accepted decoders may parse it.
        with Image.open(io.BytesIO(data), formats=list(_FORMATS.values())) as image:
            # Opening reads only the header; a truncated file fails only here.
            image.load()
            orientation = image.getexif().get(ExifTags.Base.Orientation, 1)
            if orientation == 1 and image.width * image.height <= max_pixels:
                return data
            upright = ImageOps.exif_transpose(image)
            return _encode(_fit(upright, max_pixels), image_format)
    # Pillow reports an oversized text chunk as ValueError; like OSError, it is the file's fault.
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise UnreadableImage(f"image cannot be read: {type(exc).__name__}") from None


def _fit(image: Image.Image, max_pixels: int) -> Image.Image:
    pixels = image.width * image.height
    if pixels <= max_pixels:
        return image
    scale = math.sqrt(max_pixels / pixels)
    # Rounded down, so the product never ends above the budget.
    size = (max(1, math.floor(image.width * scale)), max(1, math.floor(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _encode(image: Image.Image, image_format: str) -> bytes:
    if image_format == "JPEG" and image.mode not in ("RGB", "L", "CMYK"):
        image = image.convert("RGB")
    out = io.BytesIO()
    # Small print must stay legible; the default JPEG quality of 75 blurs it.
    image.save(out, format=image_format, quality=90)
    return out.getvalue()
