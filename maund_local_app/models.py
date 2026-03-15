from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def default_date_tag() -> str:
    return datetime.now().strftime("%y%m%d_%H%M%S")


@dataclass(frozen=True)
class EditorPreset:
    key: str
    label: str
    allowed_substitutions: frozenset[tuple[str, str]]
    allowed_rule_text: str
    primary_metric_label: str


@dataclass(frozen=True)
class BlockOverride:
    block_index: int
    block_name: str = ""
    desired_products: tuple[str, ...] = ()


@dataclass(frozen=True)
class BlockSpec:
    block_index: int
    sample_spec: str
    full_sequence: str
    target_window: str
    row_items: tuple[tuple[str, int], ...]
    block_name: str = ""
    desired_products: tuple[str, ...] = ()

    @property
    def sample_ids(self) -> tuple[int, ...]:
        return tuple(sample_id for _, sample_id in self.row_items)

    @property
    def display_name(self) -> str:
        return self.block_name or f"block_{self.block_index}"


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
    analysis_mode: str = "single_target"
    block_overrides: tuple[BlockOverride, ...] = ()
    date_tag: str = field(default_factory=default_date_tag)
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
    detected_blocks: tuple[BlockSpec, ...] = ()


@dataclass(frozen=True)
class RunResult:
    run_dir: Path
    status: str
    key_output_paths: dict[str, Path]
    warnings: tuple[str, ...]
