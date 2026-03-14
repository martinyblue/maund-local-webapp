from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class EditorPreset:
    key: str
    label: str
    allowed_substitutions: frozenset[tuple[str, str]]
    allowed_rule_text: str
    primary_metric_label: str


@dataclass(frozen=True)
class AnalysisConfig:
    fastq_dir: Path
    seq_xlsx: Path
    sample_tale_xlsx: Path | None = None
    tale_array_xlsx: Path | None = None
    sample_ids: tuple[int, ...] = ()
    exclude_samples: tuple[int, ...] = ()
    target_seq: str = ""
    editor_type: str = "taled"
    date_tag: str = field(default_factory=lambda: datetime.now().strftime("%y%m%d"))
    output_base_dir: Path = Path.cwd()


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    selected_sample_ids: tuple[int, ...]
    available_fastq_ids: tuple[int, ...]
    available_sequence_ids: tuple[int, ...]
    missing_fastq_ids: tuple[int, ...]
    missing_sequence_ids: tuple[int, ...]
    invalid_target_sample_ids: tuple[int, ...]
    target_mismatch_sample_ids: tuple[int, ...]


@dataclass(frozen=True)
class RunResult:
    run_dir: Path
    status: str
    key_output_paths: dict[str, Path]
    warnings: tuple[str, ...]
