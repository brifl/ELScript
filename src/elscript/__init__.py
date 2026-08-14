"""Public ELScript API."""

from .api import astream, render, render_document, render_yaml, stream
from .domain import (
    AudioChunk,
    Diagnostic,
    DiagnosticSeverity,
    OutputMode,
    RenderOptions,
    RenderResult,
    SceneResult,
    SegmentResult,
)

__version__ = "0.1.0a0"

__all__ = [
    "AudioChunk",
    "Diagnostic",
    "DiagnosticSeverity",
    "OutputMode",
    "RenderOptions",
    "RenderResult",
    "SceneResult",
    "SegmentResult",
    "__version__",
    "astream",
    "render",
    "render_document",
    "render_yaml",
    "stream",
]
