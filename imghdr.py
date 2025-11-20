"""Compatibility shim for Python 3.13+ where imghdr was removed.

This implements a tiny subset of the original stdlib module so packages such
as python-telegram-bot (<=13.x) can continue to import it.
"""
from __future__ import annotations

import os
from typing import Callable, Iterable, Optional, Union

_PathLike = Union[str, bytes, os.PathLike]


def _read_header(source, count: int = 32) -> bytes:
    if hasattr(source, "read"):
        pos = source.tell()
        try:
            return source.read(count)
        finally:
            source.seek(pos)
    with open(source, "rb") as handle:
        return handle.read(count)


def what(source: Union[_PathLike, object], h: Optional[bytes] = None) -> Optional[str]:
    if h is None:
        h = _read_header(source)
    for test in _TESTS:
        kind = test(h, source)
        if kind:
            return kind
    return None


def _test_jpeg(h: bytes, _: object) -> Optional[str]:
    if h[6:10] in (b"JFIF", b"Exif"):
        return "jpeg"
    return None


def _test_png(h: bytes, _: object) -> Optional[str]:
    if h.startswith(b"\211PNG\r\n\032\n"):
        return "png"
    return None


def _test_gif(h: bytes, _: object) -> Optional[str]:
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def _test_webp(h: bytes, _: object) -> Optional[str]:
    if h.startswith(b"RIFF") and h[8:12] == b"WEBP":
        return "webp"
    return None


def _test_bmp(h: bytes, _: object) -> Optional[str]:
    if h[:2] == b"BM":
        return "bmp"
    return None


def _test_tiff(h: bytes, _: object) -> Optional[str]:
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def _test_pbm(h: bytes, _: object) -> Optional[str]:
    if h[:2] in (b"P1", b"P4"):
        return "pbm"
    return None


def _test_pgm(h: bytes, _: object) -> Optional[str]:
    if h[:2] in (b"P2", b"P5"):
        return "pgm"
    return None


def _test_ppm(h: bytes, _: object) -> Optional[str]:
    if h[:2] in (b"P3", b"P6"):
        return "ppm"
    return None


def _test_rast(h: bytes, _: object) -> Optional[str]:
    if h.startswith(b"Y\xA6j\x95"):
        return "rast"
    return None


def _test_xbm(h: bytes, _: object) -> Optional[str]:
    if h[:9] == b"#define " and b"_width" in h:
        return "xbm"
    return None


_TESTS: Iterable[Callable[[bytes, object], Optional[str]]] = (
    _test_jpeg,
    _test_png,
    _test_gif,
    _test_webp,
    _test_bmp,
    _test_tiff,
    _test_pbm,
    _test_pgm,
    _test_ppm,
    _test_rast,
    _test_xbm,
)
