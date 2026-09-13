"""Turn any image we can decode into the package icon.

`preview/thumb.jpg` is the only image the browser ever loads, so every asset
should have one whatever its source format was - including the float formats an
HDRI arrives in. A linear 32-bit equirect cannot simply be clamped to 8 bits;
it has to be exposed and gamma-corrected, which is what `types.json` already
asks for on the hdri type (`"preview": "tonemap"`).

Every heavy dependency here is OPTIONAL and imported defensively. numpy and
OpenEXR being absent must degrade to "no decoder for this format", never to an
exception - `assetlib` has to stay importable by Houdini's interpreter and by a
bare Python with nothing installed. The same discipline hashing.py uses when it
falls back from xxh3 to blake2b.
"""

from __future__ import annotations

import io
from pathlib import Path

try:
    from PIL import Image
except ImportError:                                  # pragma: no cover
    Image = None

try:
    import numpy as np
except ImportError:                                  # pragma: no cover
    np = None

try:
    import OpenEXR
except ImportError:                                  # pragma: no cover
    OpenEXR = None

THUMB_SIZE = 512
JPEG_QUALITY = 88
# What transparency is composited onto. Matches ui/theme.tile_colour() - Base
# lightened 130 under the forced dark scheme - by VALUE, because assetlib holds
# no Qt and cannot ask. If the theme's tile ever changes, this follows by hand.
FLATTEN_GROUND = (58, 58, 58)

# Formats whose pixels are linear and unbounded. They need exposure, not a cast.
FLOAT_EXTS = {".hdr", ".exr"}

# sRGB transfer, and the luminance weights used to pick an exposure.
_SRGB_KNEE = 0.0031308
_LUMA = (0.2126, 0.7152, 0.0722)
# Middle grey: where the log-average luminance of a scene is placed. 0.18 is the
# photographic convention and it is what stops a bright window deciding the
# exposure for the whole room.
_MIDDLE_GREY = 0.18
_LOG_EPSILON = 1e-6
# Above this, the pixels are radiance and want exposing; below it they are data
# stored in float. The slack matters: Poly Haven's 8K normal maps peak at 1.016,
# so a threshold of exactly 1.0 sent a normal map down the tone-mapping path and
# came back with it two stops dark.
_HDR_THRESHOLD = 1.05


# ------------------------------------------------------------------ tone map


def _tonemap(rgb):
    """Linear float HxWx3 -> 8-bit sRGB HxWx3.

    Exposure comes from the LOG-AVERAGE luminance, the photographic "key" of the
    image, not from a high percentile. A percentile is set by whatever is
    brightest - the sun, or a window - and dividing the whole image by that
    crushes everything else: an interior HDRI whose median pixel is 0.04 against
    a window at 11.6 came out essentially black. The key is anchored to middle
    grey and highlights are rolled off rather than clipped, so a 6000:1 range
    lands in 8 bits with the room still visible.

    Data that never exceeds 1.0 is not radiance - it is a normal map or a
    roughness map that happens to be stored in float - so it is passed through
    untouched apart from the transfer curve.
    """
    rgb = np.nan_to_num(rgb.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    rgb = np.clip(rgb, 0.0, None)

    if float(rgb.max(initial=0.0)) > _HDR_THRESHOLD:
        luma = (rgb[..., 0] * _LUMA[0] + rgb[..., 1] * _LUMA[1]
                + rgb[..., 2] * _LUMA[2])
        lit = luma[luma > 0]
        key = float(np.exp(np.mean(np.log(lit + _LOG_EPSILON)))) if lit.size else _MIDDLE_GREY
        if not np.isfinite(key) or key <= 0:
            key = _MIDDLE_GREY
        rgb = rgb * (_MIDDLE_GREY / key)
        rgb = rgb / (1.0 + rgb)                  # Reinhard: roll off, do not clip

    rgb = np.clip(rgb, 0.0, 1.0)
    srgb = np.where(rgb <= _SRGB_KNEE, rgb * 12.92,
                    1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)
    return (np.clip(srgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


# ------------------------------------------------------------- radiance .hdr


def _read_hdr(path: Path, size: int):
    """Decode a Radiance RGBE file, subsampling as it goes.

    An 8K equirect is 33M pixels; expanded to float32 that is 400 MB for an
    image we are about to shrink to 512px. The scanlines must all be walked
    because the RLE is sequential, but only every Nth one is kept.
    """
    with path.open("rb") as fh:
        if not fh.readline().startswith(b"#?"):
            return None
        fmt = None
        while True:
            line = fh.readline()
            if not line or line in (b"\n", b"\r\n"):
                break
            if line.startswith(b"FORMAT="):
                fmt = line.strip().split(b"=", 1)[1]
        if fmt not in (None, b"32-bit_rle_rgbe"):
            return None                              # XYZE and friends: not ours
        dims = fh.readline().split()
        if len(dims) != 4 or dims[0] != b"-Y" or dims[2] != b"+X":
            return None                              # a rotated/flipped variant
        height, width = int(dims[1]), int(dims[3])
        data = fh.read()

    if width <= 0 or height <= 0:
        return None
    step = max(1, width // max(size, 1))

    pos = 0
    kept = []
    row = np.empty((4, width), dtype=np.uint8)
    for y in range(height):
        if pos + 4 > len(data):
            break
        head = data[pos:pos + 4]
        if head[0] == 2 and head[1] == 2 and (head[2] << 8 | head[3]) == width \
                and 8 <= width < 32768:
            pos += 4
            for channel in range(4):                 # new-style RLE, per channel
                x = 0
                while x < width:
                    if pos >= len(data):
                        return None
                    count = data[pos]
                    pos += 1
                    if count > 128:                  # a run of one value
                        run = count - 128
                        row[channel, x:x + run] = data[pos]
                        pos += 1
                    else:                            # literal bytes
                        run = count
                        row[channel, x:x + run] = np.frombuffer(
                            data, np.uint8, run, pos)
                        pos += run
                    x += run
        else:                                        # flat, uncompressed RGBE
            if pos + width * 4 > len(data):
                break
            row = np.frombuffer(data, np.uint8, width * 4, pos).reshape(width, 4).T
            pos += width * 4
        if y % step == 0:
            kept.append(row[:, ::step].copy())

    if not kept:
        return None

    rgbe = np.stack(kept)                            # (rows, 4, cols)
    exponent = rgbe[:, 3, :].astype(np.int32)
    # RGBE: value = mantissa * 2^(exponent - 128 - 8). Exponent 0 means black.
    scale = np.ldexp(np.ones(exponent.shape, dtype=np.float32), exponent - 136)
    scale = np.where(exponent > 0, scale, np.float32(0.0))
    rgb = rgbe[:, :3, :].astype(np.float32) * scale[:, None, :]
    return np.transpose(rgb, (0, 2, 1))              # (rows, cols, 3)


# --------------------------------------------------------------------- .exr


def _read_exr(path: Path, size: int):
    """Decode an EXR to linear float RGB, subsampled towards `size`.

    Two things vary between builds of the OpenEXR bindings and both have bitten
    us, so neither is trusted:

      * `part.width` is a property in some builds and a METHOD in others, which
        is why the stride is taken from the pixel array's own shape instead;
      * channels may arrive as separate R/G/B planes, or as ONE channel called
        "RGB" holding an (h, w, 3) array. Poly Haven's 8K maps are the latter.
    """
    with OpenEXR.File(str(path)) as handle:
        channels = handle.parts[0].channels
        if not channels:
            return None

        def stride(array) -> int:
            return max(1, array.shape[1] // max(size, 1))

        # Interleaved: one channel already holding RGB.
        for channel in channels.values():
            pixels = channel.pixels
            if getattr(pixels, "ndim", 0) == 3 and pixels.shape[2] >= 3:
                step = stride(pixels)
                return np.asarray(pixels[::step, ::step, :3], dtype=np.float32)

        # Separate planes. The stride comes from the first one and is applied to
        # all, so the planes still stack.
        planes = {name: channel.pixels for name, channel in channels.items()}
        planes = {n: p for n, p in planes.items() if getattr(p, "ndim", 0) == 2}
        if not planes:
            return None
        step = stride(next(iter(planes.values())))

        def plane(name):
            return np.asarray(planes[name][::step, ::step], dtype=np.float32)

        if {"R", "G", "B"} <= set(planes):
            return np.stack([plane("R"), plane("G"), plane("B")], axis=-1)

        names = [n for n in planes if n not in ("A", "alpha")] or list(planes)
        if len(names) >= 3:
            return np.stack([plane(n) for n in names[:3]], axis=-1)
        grey = plane(names[0])                       # a single data channel
        return np.stack([grey, grey, grey], axis=-1)


# ------------------------------------------------------------------- public


def _hdr_dimensions(path: Path):
    """Radiance dimensions from the header alone - no pixels decoded."""
    try:
        with path.open("rb") as fh:
            if not fh.readline().startswith(b"#?"):
                return None
            while True:
                line = fh.readline()
                if not line:
                    return None
                if line in (b"\n", b"\r\n"):
                    break
            dims = fh.readline().split()
        if len(dims) == 4 and dims[0] == b"-Y" and dims[2] == b"+X":
            return int(dims[3]), int(dims[1])
    except Exception:                                # noqa: BLE001
        return None
    return None


def dimensions(src):
    """(width, height) without decoding the image, or None.

    Callers use this to measure an image - an HDRI is recognised by its 2:1
    aspect - so it has to answer for the float formats too. Asking Pillow alone
    silently failed on EXR, which meant an EXR equirect was never detected as an
    HDRI at all.
    """
    src = Path(src)
    ext = src.suffix.lower()

    if ext == ".exr" and OpenEXR is not None:
        # Measured from the header's dataWindow, NOT part.width: in header-only
        # mode this binding reports width 0, and opening an 8K EXR without that
        # flag decodes it - 1.5 seconds to answer a question about its size.
        try:
            with OpenEXR.File(str(src), header_only=True) as handle:
                part = handle.parts[0]
                header = part.header
                header = header() if callable(header) else header
                window = header.get("dataWindow") if header else None
                if window is not None:
                    low, high = window
                    return (int(high[0]) - int(low[0]) + 1,
                            int(high[1]) - int(low[1]) + 1)
                width, height = part.width, part.height
                width = width() if callable(width) else width
                height = height() if callable(height) else height
                if width and height:
                    return int(width), int(height)
        except Exception:                            # noqa: BLE001
            return None
        return None
    if ext == ".hdr":
        return _hdr_dimensions(src)
    if Image is None:
        return None
    try:
        with Image.open(src) as opened:
            return opened.size
    except Exception:                                # noqa: BLE001
        return None


def why_not(src) -> str:
    """Empty string if this file can be turned into an icon, else the reason."""
    src = Path(src)
    ext = src.suffix.lower()
    if Image is None:
        return "Pillow is not installed"
    if ext in FLOAT_EXTS:
        if np is None:
            return f"{ext} needs numpy, which is not installed"
        if ext == ".exr" and OpenEXR is None:
            return "exr needs the openexr package, which is not installed"
        return ""
    if ext not in Image.registered_extensions():
        return f"no decoder for {ext}"
    return ""


def _flatten(opened):
    """Any mode -> RGB, compositing transparency onto the tile ground.

    `convert("RGB")` is what this replaced, and it does not composite: it drops
    the alpha channel and keeps whatever RGB was stored underneath. For a
    rounded app icon that is invisible when the exporter wrote black there and
    glaring when it wrote WHITE - a bright square around the icon on a dark
    grid. Measured, on the same image saved two ways:

        transparent corners, black underneath -> (0, 0, 0)
        transparent corners, white underneath -> (255, 255, 255)

    Neither was chosen. Now the ground is, and it is dark because these are
    dark-UI icons on a forced-dark grid - white corners would be the most
    visible thing in the window. FLATTEN_GROUND matches `theme.tile_colour()`
    by value rather than by import: `assetlib` holds no Qt, so the number is
    duplicated here deliberately and the comment is what keeps them together.

    No single ground is right - a tile is also drawn selected, and blue when the
    asset is on a server - so this is the common case, chosen, not a guess.
    """
    if opened.mode in ("RGBA", "LA", "PA") or "transparency" in opened.info:
        rgba = opened.convert("RGBA")
        ground = Image.new("RGB", rgba.size, FLATTEN_GROUND)
        ground.paste(rgba, mask=rgba.split()[-1])
        return ground
    return opened.convert("RGB")


def render(src, size: int = THUMB_SIZE):
    """Decode `src` and return a PIL RGB image no larger than `size`."""
    src = Path(src)
    if why_not(src):
        return None
    ext = src.suffix.lower()

    try:
        if ext in FLOAT_EXTS:
            rgb = _read_hdr(src, size) if ext == ".hdr" else _read_exr(src, size)
            if rgb is None:
                return None
            image = Image.fromarray(_tonemap(rgb), mode="RGB")
        else:
            with Image.open(src) as opened:
                # Cheap partial decode: JPEG can downscale while reading.
                opened.draft("RGB", (size * 2, size * 2))
                if opened.mode in ("F", "I", "I;16", "I;16B", "I;16L"):
                    if np is None:
                        return None
                    plane = np.asarray(opened, dtype=np.float32)
                    image = Image.fromarray(
                        _tonemap(np.stack([plane] * 3, axis=-1)), mode="RGB")
                else:
                    image = _flatten(opened)
        image.thumbnail((size, size))
        return image
    except Exception:                                # noqa: BLE001
        # A corrupt or exotic file must cost the asset its icon, nothing more.
        return None


def make_thumb(src, dst, size: int = THUMB_SIZE) -> bool:
    """Write the icon. Returns False rather than raising - an asset without a
    thumbnail is still a perfectly good asset."""
    image = render(src, size)
    if image is None:
        return False
    try:
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        image.save(dst, "JPEG", quality=JPEG_QUALITY)
        return True
    except Exception:                                # noqa: BLE001
        return False


def thumb_bytes(src, size: int = THUMB_SIZE):
    """The same icon as JPEG bytes, for showing before anything is committed.

    The preview box and the committed file therefore come from one decoder:
    what you see in the window is what lands in preview/thumb.jpg.
    """
    image = render(src, size)
    if image is None:
        return None
    buffer = io.BytesIO()
    try:
        image.save(buffer, "JPEG", quality=JPEG_QUALITY)
    except Exception:                                # noqa: BLE001
        return None
    return buffer.getvalue()
