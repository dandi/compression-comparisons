"""Abstract base for codec adapters."""

from __future__ import annotations

from typing import Any, ClassVar

from numcodecs.abc import Codec


class CodecAdapter:
    """Wrap a `numcodecs.abc.Codec` with benchmark metadata.

    Subclasses set the class-level `name` (registry key) and `lossy` flag,
    then implement `__init__(**params)` and `make_codec()`.
    """

    name: ClassVar[str] = ""
    lossy: ClassVar[bool] = False

    def __init__(self, **params: Any) -> None:
        self.params: dict[str, Any] = dict(params)

    def make_codec(self) -> Codec:
        """Return a fresh `numcodecs.abc.Codec` instance."""
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        """Machine-readable description used in manifests and reports."""
        return {
            "name": self.name,
            "lossy": self.lossy,
            "params": self.params,
        }
