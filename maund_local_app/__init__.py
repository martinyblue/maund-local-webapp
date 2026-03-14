"""Local MAUND web application package."""

from .engine import run_analysis, validate_config
from .models import AnalysisConfig, EditorPreset, RunResult, ValidationResult
from .presets import EDITOR_PRESETS, get_editor_preset

__all__ = [
    "AnalysisConfig",
    "EDITOR_PRESETS",
    "EditorPreset",
    "RunResult",
    "ValidationResult",
    "get_editor_preset",
    "run_analysis",
    "validate_config",
]
