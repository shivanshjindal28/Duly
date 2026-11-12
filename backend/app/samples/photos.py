"""Turn a rendered invoice page into a realistic phone photo or a low-quality scan.

Deterministic (seeded) so the git-tracked demo files are reproducible. Pure Pillow + NumPy +
OpenCV (all pip wheels); nothing here is used at run time, only by the invoice generator
and tests.
"""
from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image, ImageFilter

from app.ingestion.extract_text import render_pages


def _jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def page_image(pdf: bytes, dpi: int) -> Image.Image:
    return render_pages(pdf, "pdf", dpi=dpi)[0]


def phone_photo(pdf: bytes, seed: int = 7, dpi: int = 170, tilt_deg: float = 1.6, quality: int = 82) -> bytes:
    """The paper invoice photographed on a desk: slight perspective and tilt, uneven light
    (a soft shadow from the phone), sensor noise and JPEG compression."""
    rng = np.random.default_rng(seed)
    page = np.asarray(page_image(pdf, dpi)).astype(np.float32)
    h, w = page.shape[:2]
    pad = int(0.06 * w)
    canvas_w, canvas_h = w + 2 * pad, h + 2 * pad
    # Corners of the sheet on the photo: a mild keystone (phone held slightly tilted).
    jitter = lambda s: float(rng.uniform(-s, s))  # noqa: E731
    k = 0.012 * w
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[pad + k + jitter(4), pad + jitter(4)], [pad + w - k + jitter(4), pad + jitter(4)],
                      [pad + w + jitter(4), pad + h + jitter(4)], [pad + jitter(4), pad + h + jitter(4)]])
    m = cv2.getPerspectiveTransform(src, dst)
    desk = np.array([196, 186, 170], dtype=np.float32)  # warm wooden desk
    warped = cv2.warpPerspective(page, m, (canvas_w, canvas_h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=desk.tolist())
    rot = cv2.getRotationMatrix2D((canvas_w / 2, canvas_h / 2), tilt_deg, 1.0)
    warped = cv2.warpAffine(warped, rot, (canvas_w, canvas_h), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=desk.tolist())
    # Lighting: brighter top-left, a soft shadow towards the bottom-right, gentle vignette.
    yy, xx = np.mgrid[0:canvas_h, 0:canvas_w].astype(np.float32)
    light = 1.04 - 0.16 * (xx / canvas_w * 0.4 + yy / canvas_h * 0.6)
    cx, cy = canvas_w / 2, canvas_h / 2
    light *= 1 - 0.10 * (((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / 2
    img = warped * light[..., None]
    img = img * np.array([1.0, 0.985, 0.95], dtype=np.float32)  # warm white balance
    img += rng.normal(0, 3.5, img.shape).astype(np.float32)
    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.5))
    return _jpeg(out, quality)


def blurry_photo(pdf: bytes, dpi: int = 130, tilt_deg: float = 1.2, blur: float = 0.9, quality: int = 40) -> bytes:
    """A hurried, out-of-focus photo: tilted, blurred, heavily compressed. OCR confidence drops
    so Duly sends the uncertain fields to a human (scenario 12)."""
    page = page_image(pdf, dpi)
    photo = page.rotate(tilt_deg, expand=True, fillcolor="#d8d4cc").filter(ImageFilter.GaussianBlur(blur))
    return _jpeg(photo, quality)


def scanned_pdf(pdf: bytes, seed: int = 11, dpi: int = 150, quality: int = 55) -> bytes:
    """A cheap office scan: greyscale, a little skew, toner speckle and JPEG artefacts,
    wrapped in an image-only PDF (no text layer, so Duly falls back to OCR)."""
    rng = np.random.default_rng(seed)
    page = page_image(pdf, dpi).convert("L").rotate(-0.6, expand=False, fillcolor=250)
    arr = np.asarray(page).astype(np.float32)
    arr = 18 + arr * 0.9  # scanner lifts the blacks and dims the whites
    speckle = rng.random(arr.shape) < 0.0008
    arr[speckle] = rng.uniform(40, 120, int(speckle.sum()))
    arr += rng.normal(0, 4, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.4))
    jpg = Image.open(io.BytesIO(_jpeg(img, quality)))
    buf = io.BytesIO()
    jpg.save(buf, format="PDF", resolution=dpi)
    return buf.getvalue()
