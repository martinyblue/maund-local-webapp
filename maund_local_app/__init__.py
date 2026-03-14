"""Local MAUND web application package."""

from .engine import run_analysis, validate_config
from .models import AnalysisConfig, EditorPreset, RunResult, ValidationResult
from .presets import EDITOR_PRESETS, get_editor_preset
from .version import __version__, get_version

__all__ = [
    "AnalysisConfig",
    "EDITOR_PRESETS",
    "EditorPreset",
    "RunResult",
    "ValidationResult",
    "__version__",
    "get_editor_preset",
    "get_version",
    "run_analysis",
    "validate_config",
]
