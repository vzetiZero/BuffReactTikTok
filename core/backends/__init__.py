"""Các backend xử lý account."""

from .base import BaseBackend, Progress, StopFlag
from .mock_backend import MockBackend

__all__ = ["BaseBackend", "Progress", "StopFlag", "MockBackend", "build_backend"]


def build_backend(kind: str, proxy_pool=None, rotate_on_block: bool = True):
    """kind: 'http' | 'mock'"""
    if kind == "mock":
        return MockBackend()
    from .http_backend import HttpBackend

    return HttpBackend(pool=proxy_pool, rotate_on_block=rotate_on_block)
