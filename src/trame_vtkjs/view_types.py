"""Public configuration types for vtk.js views."""

from typing import Literal

Tiles3DTexturePolicy = Literal["auto", "native", "rgba"]
Tiles3DQualityPolicy = Literal["adaptive", "fixed"]

__all__ = ["Tiles3DQualityPolicy", "Tiles3DTexturePolicy"]
