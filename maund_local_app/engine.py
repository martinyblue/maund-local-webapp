from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from maund_workflow.run_pipeline import (
    build_miseq_summary_table,
    compute_edited_reads,
    discover_fastq_pairs,
    merge_samples,
    setup_work_dirs,
)

from .io_utils import (
    load_block_specs,
    load_sample_tail_mapping,
    load_seq_mappings,
    load_tail_sequences,
    slugify_name,
    target_slug,
    write_tsv,
)
from .lite_maund import run_maund_lite
from .models import AnalysisConfig, BlockSpec, RunResult, ValidationResult
from .presets import get_editor_preset
from .reporting import (
    build_analysis_flow_markdown,
    build_heatmap_tables,
    build_sample_reports,
    render_block_report_html,
    render_html,
)


DEFAULT_CONDITION = "one_condition"
DEFAULT_OFFSET = 29
DEFAULT_ANALYSIS_MODE = "single_target"
LogFunc = Callable[[str], None]


def _log(logger: LogFunc | None, message: str) -> None:
    if logger is not None:
        logger(message)


def _normalized_config(config: AnalysisConfig) -> AnalysisConfig:
    return replace(
        config,
        fastq_dir=Path(config.fastq_dir).expanduser(),
        seq_xlsx=Path(config.seq_xlsx).expanduser(),
        sample_tale_xlsx=Path(config.sample_tale_xlsx).expanduser() if config.sample_tale_xlsx else None,
        tale_array_xlsx=Path(config.tale_array_xlsx).expanduser() if config.tale_array_xlsx else None,
        target_seq=config.target_seq.strip().upper(),
        editor_type=config.editor_type.strip().lower() or "taled",
        analysis_mode=config.analysis_mode.strip().lower() or DEFAULT_ANALYSIS_MODE,
        output_base_dir=Path(config.output_base_dir).expanduser(),
        date_tag=config.date_tag.strip() or datetime.now().strftime("%y%m%d_%H%M%S"),
    )


def _build_selected_ids(
    *,
    requested_ids: tuple[int, ...],
    exclude_ids: tuple[int, ...],
    fastq_ids: set[int],
    seq_ids: set[int],
) -> list[int]:
    selected = set(requested_ids) if requested_ids else (fastq_ids & seq_ids)
    selected -= set(exclude_ids)
    return sorted(selected)


def _format_id_spec(sample_ids: tuple[int, ...]) -> str:
    if not sample_ids:
        return ""
    ids = sorted(set(sample_ids))
    parts: list[str] = []
    start = ids[0]
    prev = ids[0]
    for current in ids[1:]:
        if current == prev + 1:
            prev = current
            continue
        parts.append(f"{start}-{prev}" if start != prev else str(start))
        start = current
        prev = current
    parts.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(parts)


def _filter_block(block: BlockSpec, requested_ids: tuple[int, ...], exclude_ids: tuple[int, ...]) -> BlockSpec:
    include = set(requested_ids)
    exclude = set(exclude_ids)
    row_items = tuple(
        (label, sample_id)
        for label, sample_id in block.row_items
        if (not include or sample_id in include) and sample_id not in exclude
    )
    sample_spec = block.sample_spec if not requested_ids and not exclude_ids else _format_id_spec(
        tuple(sample_id for _, sample_id in row_items)
    )
    return replace(block, row_items=row_items, sample_spec=sample_spec or block.sample_spec)


def _unique_messages(messages: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for message in messages:
        if message not in seen:
            ordered.append(message)
            seen.add(message)
    return tuple(ordered)


def _load_tail_mapping_bundle(
    *,
    cfg: AnalysisConfig,
    selected_ids: list[int],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[int, dict[str, object]], list[str]]:
    warnings: list[str] = []
    tail_map: dict[int, dict[str, object]] = {}
    if cfg.sample_tale_xlsx and cfg.sample_tale_xlsx.exists():
        tail_map = load_sample_tail_mapping(cfg.sample_tale_xlsx)
    elif cfg.sample_tale_xlsx is None:
        tail_map = load_sample_tail_mapping(cfg.seq_xlsx)

    if not tail_map:
        warnings.append("Tail mapping xlsx was not available or contained no Left/Right combos. Tail-mapped outputs were skipped.")
        return [], [], {}, warnings

    left_sequences: dict[int, str] = {}
    right_sequences: dict[int, str] = {}
    if cfg.tale_array_xlsx and cfg.tale_array_xlsx.exists():
        left_sequences, right_sequences = load_tail_sequences(cfg.tale_array_xlsx)

    all_rows: list[dict[str, object]] = []
    for sample_id in sorted(tail_map):
        item = dict(tail_map[sample_id])
        left_idx = int(item.get("left_tail_index", 0) or 0)
        right_idx = int(item.get("right_tail_index", 0) or 0)
        item["left_tail_sequence"] = left_sequences.get(left_idx, "")
        item["right_tail_sequence"] = right_sequences.get(right_idx, "")
        all_rows.append(item)

    scope_rows = [row for row in all_rows if int(row["sample_id"]) in set(selected_ids)]
    by_sample = {int(row["sample_id"]): row for row in scope_rows}
    missing_scope = sorted(sample_id for sample_id in selected_ids if sample_id not in by_sample)
    if missing_scope:
        warnings.append("Tail mapping missing for selected sample IDs: " + ",".join(map(str, missing_scope)))
    return all_rows, scope_rows, by_sample, warnings


def _single_target_validation(cfg: AnalysisConfig) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        preset = get_editor_preset(cfg.editor_type)
    except ValueError as exc:
        errors.append(str(exc))
        preset = None

    if not cfg.fastq_dir.exists():
        errors.append(f"FASTQ directory not found: {cfg.fastq_dir}")
    if not cfg.seq_xlsx.exists():
        errors.append(f"Sequence xlsx not found: {cfg.seq_xlsx}")
    if cfg.sample_tale_xlsx and not cfg.sample_tale_xlsx.exists():
        errors.append(f"Sample TALE xlsx not found: {cfg.sample_tale_xlsx}")
    if cfg.tale_array_xlsx and not cfg.tale_array_xlsx.exists():
        errors.append(f"TALE array xlsx not found: {cfg.tale_array_xlsx}")
    if not cfg.target_seq:
        errors.append("Target sequence is required.")
    if cfg.date_tag and not cfg.date_tag.replace("_", "").isalnum():
        errors.append(f"Invalid date_tag: {cfg.date_tag}")

    if errors:
        return ValidationResult(
            is_valid=False,
            errors=tuple(errors),
            warnings=tuple(warnings),
            selected_sample_ids=(),
            available_fastq_ids=(),
            available_sequence_ids=(),
            missing_fastq_ids=(),
            missing_sequence_ids=(),
            invalid_target_sample_ids=(),
            target_mismatch_sample_ids=(),
            detected_blocks=(),
        )

    pairs = discover_fastq_pairs(cfg.fastq_dir)
    seq_map = load_seq_mappings(cfg.seq_xlsx)
    available_fastq_ids = sorted(pairs)
    available_sequence_ids = sorted(seq_map)
    selected_ids = _build_selected_ids(
        requested_ids=cfg.sample_ids,
        exclude_ids=cfg.exclude_samples,
        fastq_ids=set(pairs),
        seq_ids=set(seq_map),
    )

    if not selected_ids:
        errors.append("No samples selected after applying sample scope and exclusions.")

    missing_fastq_ids = tuple(sorted(sample_id for sample_id in selected_ids if sample_id not in pairs))
    missing_sequence_ids = tuple(sorted(sample_id for sample_id in selected_ids if sample_id not in seq_map))
    invalid_target_sample_ids = tuple(
        sorted(
            sample_id
            for sample_id in selected_ids
            if sample_id in seq_map and cfg.target_seq not in seq_map[sample_id]["sequence"].upper()
        )
    )
    target_mismatch_sample_ids = tuple(
        sorted(
            sample_id
            for sample_id in selected_ids
            if sample_id in seq_map and seq_map[sample_id]["target_window"].upper() != cfg.target_seq
        )
    )

    if missing_fastq_ids:
        errors.append("Missing FASTQ pairs for sample IDs: " + ",".join(map(str, missing_fastq_ids)))
    if missing_sequence_ids:
        errors.append("Missing sequence mapping for sample IDs: " + ",".join(map(str, missing_sequence_ids)))
    if invalid_target_sample_ids:
        errors.append(
            "Target sequence is not present in amplicon sequence for sample IDs: "
            + ",".join(map(str, invalid_target_sample_ids))
        )
    if target_mismatch_sample_ids:
        warnings.append(
            "Target in seq xlsx does not match the requested target for sample IDs: "
            + ",".join(map(str, target_mismatch_sample_ids))
        )
    if cfg.sample_tale_xlsx is None:
        warnings.append("sample_tale_xlsx not provided. Tail-module mapping outputs will be skipped unless seq xlsx contains combos.")
    if cfg.sample_tale_xlsx and cfg.tale_array_xlsx is None:
        warnings.append("tale_array_xlsx not provided. Tail sequences will be blank in mapping tables.")
    if preset is not None and not selected_ids:
        warnings.append(f"No samples available for preset {preset.label}.")

    return ValidationResult(
        is_valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        selected_sample_ids=tuple(selected_ids),
        available_fastq_ids=tuple(available_fastq_ids),
        available_sequence_ids=tuple(available_sequence_ids),
        missing_fastq_ids=missing_fastq_ids,
        missing_sequence_ids=missing_sequence_ids,
        invalid_target_sample_ids=invalid_target_sample_ids,
        target_mismatch_sample_ids=target_mismatch_sample_ids,
        detected_blocks=(),
    )


def _block_heatmap_validation(cfg: AnalysisConfig) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        get_editor_preset(cfg.editor_type)
    except ValueError as exc:
        errors.append(str(exc))

    if not cfg.fastq_dir.exists():
        errors.append(f"FASTQ directory not found: {cfg.fastq_dir}")
    if not cfg.seq_xlsx.exists():
        errors.append(f"Sequence xlsx not found: {cfg.seq_xlsx}")
    if cfg.sample_tale_xlsx and not cfg.sample_tale_xlsx.exists():
        errors.append(f"Sample TALE xlsx not found: {cfg.sample_tale_xlsx}")
    if cfg.tale_array_xlsx and not cfg.tale_array_xlsx.exists():
        errors.append(f"TALE array xlsx not found: {cfg.tale_array_xlsx}")
    if cfg.date_tag and not cfg.date_tag.replace("_", "").isalnum():
        errors.append(f"Invalid date_tag: {cfg.date_tag}")
    if errors:
        return ValidationResult(
            is_valid=False,
            errors=tuple(errors),
            warnings=tuple(warnings),
            selected_sample_ids=(),
            available_fastq_ids=(),
            available_sequence_ids=(),
            missing_fastq_ids=(),
            missing_sequence_ids=(),
            invalid_target_sample_ids=(),
            target_mismatch_sample_ids=(),
            detected_blocks=(),
        )

    blocks = tuple(
        filtered
        for block in load_block_specs(cfg.seq_xlsx, cfg.block_overrides)
        if (filtered := _filter_block(block, cfg.sample_ids, cfg.exclude_samples)).row_items
    )
    if not blocks:
        errors.append("No block was selected from the seq xlsx after applying sample scope and exclusions.")

    pairs = discover_fastq_pairs(cfg.fastq_dir)
    seq_map = load_seq_mappings(cfg.seq_xlsx)
    available_fastq_ids = sorted(pairs)
    available_sequence_ids = sorted(seq_map)
    selected_ids = sorted({sample_id for block in blocks for sample_id in block.sample_ids})

    missing_fastq_ids = tuple(sorted(sample_id for sample_id in selected_ids if sample_id not in pairs))
    missing_sequence_ids = tuple(sorted(sample_id for sample_id in selected_ids if sample_id not in seq_map))

    invalid_target_ids: set[int] = set()
    target_mismatch_ids: set[int] = set()
    for block in blocks:
        for sample_id in block.sample_ids:
            if sample_id not in seq_map:
                continue
            if block.target_window not in seq_map[sample_id]["sequence"].upper():
                invalid_target_ids.add(sample_id)
            if seq_map[sample_id]["target_window"].upper() != block.target_window:
                target_mismatch_ids.add(sample_id)
        if not block.desired_products:
            warnings.append(f"Desired product sequence was not provided for block {block.display_name}. The title will omit it.")

    if missing_fastq_ids:
        errors.append("Missing FASTQ pairs for sample IDs: " + ",".join(map(str, missing_fastq_ids)))
    if missing_sequence_ids:
        errors.append("Missing sequence mapping for sample IDs: " + ",".join(map(str, missing_sequence_ids)))
    if invalid_target_ids:
        errors.append(
            "Block target sequence is not present in amplicon sequence for sample IDs: "
            + ",".join(map(str, sorted(invalid_target_ids)))
        )
    if target_mismatch_ids:
        warnings.append(
            "Target in seq xlsx does not match the resolved block target for sample IDs: "
            + ",".join(map(str, sorted(target_mismatch_ids)))
        )
    if cfg.sample_tale_xlsx is None:
        warnings.append("sample_tale_xlsx not provided. Tail-module mapping outputs will be skipped unless seq xlsx contains combos.")
    if cfg.sample_tale_xlsx and cfg.tale_array_xlsx is None:
        warnings.append("tale_array_xlsx not provided. Tail sequences will be blank in mapping tables.")

    return ValidationResult(
        is_valid=not errors,
        errors=tuple(errors),
        warnings=_unique_messages(warnings),
        selected_sample_ids=tuple(selected_ids),
        available_fastq_ids=tuple(available_fastq_ids),
        available_sequence_ids=tuple(available_sequence_ids),
        missing_fastq_ids=missing_fastq_ids,
        missing_sequence_ids=missing_sequence_ids,
        invalid_target_sample_ids=tuple(sorted(invalid_target_ids)),
        target_mismatch_sample_ids=tuple(sorted(target_mismatch_ids)),
        detected_blocks=blocks,
    )


def validate_config(config: AnalysisConfig) -> ValidationResult:
    cfg = _normalized_config(config)
    if cfg.analysis_mode == "block_heatmap":
        return _block_heatmap_validation(cfg)
    if cfg.analysis_mode != "single_target":
        return ValidationResult(
            is_valid=False,
            errors=(f"Unsupported analysis mode: {cfg.analysis_mode}",),
            warnings=(),
            selected_sample_ids=(),
            available_fastq_ids=(),
            available_sequence_ids=(),
            missing_fastq_ids=(),
            missing_sequence_ids=(),
            invalid_target_sample_ids=(),
            target_mismatch_sample_ids=(),
            detected_blocks=(),
        )
    return _single_target_validation(cfg)


def _path_with_prefix(directory: Path, stem: str, date_tag: str, prefix: str, suffix: str) -> Path:
    return directory / f"{stem}_{prefix}_{date_tag}.{suffix}"


def _run_single_target_analysis(cfg: AnalysisConfig, validation: ValidationResult, logger: LogFunc | None) -> RunResult:
    preset = get_editor_preset(cfg.editor_type)
    selected_ids = list(validation.selected_sample_ids)
    run_root = cfg.output_base_dir / f"maund_{cfg.date_tag}"
    if run_root.exists():
        raise FileExistsError(f"Output folder already exists: {run_root}")

    _log(logger, f"Creating output folder: {run_root}")
    dirs = setup_work_dirs(run_root)
    seq_map = load_seq_mappings(cfg.seq_xlsx)
    pairs = discover_fastq_pairs(cfg.fastq_dir)

    requested_ids = set(cfg.sample_ids)
    skipped_rows: list[dict[str, object]] = []
    candidate_ids = sorted(set(pairs) | requested_ids)
    for sample_id in candidate_ids:
        if sample_id in set(cfg.exclude_samples):
            skipped_rows.append({"sample_id": sample_id, "reason": "excluded_by_user"})
        elif sample_id not in pairs:
            skipped_rows.append({"sample_id": sample_id, "reason": "missing_fastq_pair"})
        elif sample_id not in seq_map:
            skipped_rows.append({"sample_id": sample_id, "reason": "missing_sequence_mapping"})
        elif sample_id not in selected_ids:
            skipped_rows.append({"sample_id": sample_id, "reason": "not_in_selected_scope"})

    _log(logger, f"Merging FASTQ pairs for {len(selected_ids)} sample(s)")
    merge_rows = merge_samples(selected_ids, pairs, dirs["merged"], DEFAULT_OFFSET)

    _log(logger, "Running MAUND-compatible lite analysis")
    seq_map_selected = {
        sample_id: {
            "sequence": seq_map[sample_id]["sequence"],
            "target_window": cfg.target_seq,
        }
        for sample_id in selected_ids
    }
    run_rows = run_maund_lite(
        sample_ids=selected_ids,
        seq_map=seq_map_selected,
        pairs=pairs,
        merged_dir=dirs["merged"],
        maund_out_dir=dirs["maund_out"],
        logs_dir=dirs["logs"],
        condition=DEFAULT_CONDITION,
        otag=cfg.date_tag,
    )

    _log(logger, "Building step tables")
    mapping_rows = [
        {
            "sample_id": sample_id,
            "s_index": pairs[sample_id]["s_index"],
            "sequence": seq_map[sample_id]["sequence"],
            "target_from_seqxlsx": seq_map[sample_id]["target_window"],
            "target_used": cfg.target_seq,
        }
        for sample_id in selected_ids
    ]
    edited_rows = compute_edited_reads(run_rows)

    merge_path = dirs["tables"] / f"merge_stats_{cfg.date_tag}.tsv"
    run_status_path = dirs["tables"] / f"run_status_{cfg.date_tag}.tsv"
    skipped_path = dirs["tables"] / f"skipped_samples_{cfg.date_tag}.tsv"
    edited_path = dirs["tables"] / f"edited_reads_{cfg.date_tag}.tsv"
    mapping_path = dirs["tables"] / f"sample_mapping_used_{cfg.date_tag}.tsv"
    miseq_path = dirs["tables"] / f"maund_miseq_summary_{cfg.date_tag}.tsv"

    write_tsv(
        mapping_path,
        mapping_rows,
        ["sample_id", "s_index", "sequence", "target_from_seqxlsx", "target_used"],
    )
    write_tsv(
        merge_path,
        merge_rows,
        ["sample_id", "s_index", "read_count", "offset", "overlap_match_ratio", "merged_fastq"],
    )
    write_tsv(
        run_status_path,
        run_rows,
        [
            "sample_id",
            "replicate",
            "condition",
            "s_index",
            "aseq",
            "rgen",
            "return_code",
            "summary_file",
            "summary_exists",
            "window_file",
            "window_exists",
            "same_length_file",
            "same_length_exists",
            "log_file",
        ],
    )
    write_tsv(skipped_path, skipped_rows, ["sample_id", "reason"])
    write_tsv(
        edited_path,
        edited_rows,
        [
            "sample_id",
            "replicate",
            "condition",
            "s_index",
            "target_window_ref",
            "window_total_reads",
            "window_wt_reads",
            "edited_reads_percent",
            "maund_window_mutated",
            "maund_window_total",
            "maund_window_ratio",
            "maund_n_indels",
            "maund_n_all",
            "maund_indel_ratio",
        ],
    )
    build_miseq_summary_table(run_rows, miseq_path)

    _log(logger, "Building per-sample editing tables and HTML report")
    tail_all_rows, tail_scope_rows, tail_by_sample, tail_warnings = _load_tail_mapping_bundle(
        cfg=cfg,
        selected_ids=selected_ids,
    )
    warnings = list(validation.warnings) + tail_warnings
    per_sample_rows, ranked_rows, render_rows = build_sample_reports(
        run_rows=run_rows,
        preset=preset,
        tail_by_sample=tail_by_sample,
    )

    sample_slug = f"{cfg.editor_type.lower()}_{target_slug(cfg.target_seq)}"
    per_sample_path = dirs["tables"] / f"sample_editing_{sample_slug}_{cfg.date_tag}.tsv"
    ranked_path = dirs["tables"] / f"ranked_haplotypes_{sample_slug}_{cfg.date_tag}.tsv"
    render_path = dirs["tables"] / f"haplotype_render_rows_{sample_slug}_{cfg.date_tag}.tsv"
    html_path = dirs["tables"] / f"haplotype_colored_by_combo_{sample_slug}_{cfg.date_tag}.html"
    analysis_flow_path = dirs["tables"] / f"analysis_flow_{cfg.date_tag}.md"

    write_tsv(
        per_sample_path,
        per_sample_rows,
        [
            "sample_id",
            "replicate",
            "condition",
            "s_index",
            "tail_combo",
            "left_tail_module",
            "right_tail_module",
            "left_tail_sequence",
            "right_tail_sequence",
            "target_seq",
            "allowed_rule",
            "total_same_length_reads",
            "wt_reads",
            "wt_pct",
            "edited_reads_allowed_only",
            "edited_pct_allowed_only",
            "disallowed_mut_reads",
            "disallowed_mut_pct",
            "same_length_file",
        ],
    )
    write_tsv(
        ranked_path,
        ranked_rows,
        [
            "sample_id",
            "tail_combo",
            "left_tail_module",
            "right_tail_module",
            "target_seq",
            "edited_reads_allowed_only",
            "total_same_length_reads",
            "edited_pct_allowed_only",
            "disallowed_mut_pct",
        ],
    )
    write_tsv(
        render_path,
        render_rows,
        [
            "sample_id",
            "tail_combo",
            "left_tail_module",
            "right_tail_module",
            "target_seq",
            "rank",
            "haplotype",
            "reads",
            "edited_reads_percent",
            "primary_label",
            "primary_pct",
            "secondary_label",
            "secondary_pct",
            "same_length_total",
        ],
    )
    html_title = f"{preset.label} Haplotype View ({cfg.target_seq})"
    html_path.write_text(render_html(per_sample_rows=per_sample_rows, render_rows=render_rows, title=html_title))

    outputs_for_flow = [
        merge_path,
        run_status_path,
        skipped_path,
        edited_path,
        miseq_path,
        per_sample_path,
        ranked_path,
        render_path,
        html_path,
    ]

    if tail_all_rows:
        tail_all_path = dirs["tables"] / f"sample_tail_mapping_from_excel_{cfg.date_tag}.tsv"
        tail_scope_path = dirs["tables"] / f"sample_tail_mapping_analysis_scope_{cfg.date_tag}.tsv"
        write_tsv(
            tail_all_path,
            tail_all_rows,
            [
                "sample_id",
                "tail_combo",
                "left_tail_module",
                "right_tail_module",
                "left_tail_index",
                "right_tail_index",
                "left_tail_sequence",
                "right_tail_sequence",
            ],
        )
        write_tsv(
            tail_scope_path,
            tail_scope_rows,
            [
                "sample_id",
                "tail_combo",
                "left_tail_module",
                "right_tail_module",
                "left_tail_index",
                "right_tail_index",
                "left_tail_sequence",
                "right_tail_sequence",
            ],
        )
        outputs_for_flow.extend([tail_all_path, tail_scope_path])

    analysis_flow_path.write_text(
        build_analysis_flow_markdown(
            config=cfg,
            preset=preset,
            selected_sample_ids=selected_ids,
            outputs=outputs_for_flow,
            warnings=warnings,
        )
    )

    key_paths = {
        "run_dir": run_root,
        "merge_stats": merge_path,
        "run_status": run_status_path,
        "edited_reads": edited_path,
        "per_sample_editing": per_sample_path,
        "ranked_haplotypes": ranked_path,
        "render_rows": render_path,
        "html_report": html_path,
        "analysis_flow": analysis_flow_path,
    }

    _log(logger, f"Analysis completed: {run_root}")
    return RunResult(
        run_dir=run_root,
        status="completed_with_warnings" if warnings else "completed",
        key_output_paths=key_paths,
        warnings=tuple(warnings),
    )


def _run_block_heatmap_analysis(cfg: AnalysisConfig, validation: ValidationResult, logger: LogFunc | None) -> RunResult:
    preset = get_editor_preset(cfg.editor_type)
    blocks = list(validation.detected_blocks)
    selected_ids = list(validation.selected_sample_ids)
    run_root = cfg.output_base_dir / f"maund_{cfg.date_tag}"
    if run_root.exists():
        raise FileExistsError(f"Output folder already exists: {run_root}")

    _log(logger, f"Creating output folder: {run_root}")
    dirs = setup_work_dirs(run_root)
    seq_map = load_seq_mappings(cfg.seq_xlsx)
    pairs = discover_fastq_pairs(cfg.fastq_dir)

    _log(logger, f"Merging FASTQ pairs for {len(selected_ids)} sample(s)")
    merge_rows = merge_samples(selected_ids, pairs, dirs["merged"], DEFAULT_OFFSET)

    all_outputs: list[Path] = []
    key_paths: dict[str, Path] = {"run_dir": run_root}
    warnings = list(validation.warnings)
    block_summaries: list[str] = []

    for block in blocks:
        block_slug = slugify_name(block.display_name)
        block_ids = list(block.sample_ids)
        block_seq_map = {
            sample_id: {
                "sequence": block.full_sequence,
                "target_window": block.target_window,
            }
            for sample_id in block_ids
        }
        block_maund_dir = dirs["maund_out"] / block_slug
        block_logs_dir = dirs["logs"] / block_slug
        block_maund_dir.mkdir(parents=True, exist_ok=True)
        block_logs_dir.mkdir(parents=True, exist_ok=True)

        _log(logger, f"Running block {block.display_name} for {len(block_ids)} sample(s)")
        run_rows = run_maund_lite(
            sample_ids=block_ids,
            seq_map=block_seq_map,
            pairs=pairs,
            merged_dir=dirs["merged"],
            maund_out_dir=block_maund_dir,
            logs_dir=block_logs_dir,
            condition=DEFAULT_CONDITION,
            otag=f"{cfg.date_tag}.{block_slug}",
        )

        block_merge_rows = [row for row in merge_rows if int(row["sample_id"]) in set(block_ids)]
        block_mapping_rows = [
            {
                "sample_id": sample_id,
                "row_key": next(label for label, sid in block.row_items if sid == sample_id),
                "block_name": block.display_name,
                "s_index": pairs[sample_id]["s_index"],
                "sequence": block.full_sequence,
                "target_from_seqxlsx": seq_map[sample_id]["target_window"],
                "target_used": block.target_window,
            }
            for sample_id in block_ids
        ]
        block_edited_rows = compute_edited_reads(run_rows)

        merge_path = _path_with_prefix(dirs["tables"], "merge_stats", cfg.date_tag, block_slug, "tsv")
        run_status_path = _path_with_prefix(dirs["tables"], "run_status", cfg.date_tag, block_slug, "tsv")
        skipped_path = _path_with_prefix(dirs["tables"], "skipped_samples", cfg.date_tag, block_slug, "tsv")
        edited_path = _path_with_prefix(dirs["tables"], "edited_reads", cfg.date_tag, block_slug, "tsv")
        mapping_path = _path_with_prefix(dirs["tables"], "sample_mapping_used", cfg.date_tag, block_slug, "tsv")
        miseq_path = _path_with_prefix(dirs["tables"], "maund_miseq_summary", cfg.date_tag, block_slug, "tsv")

        write_tsv(
            mapping_path,
            block_mapping_rows,
            ["sample_id", "row_key", "block_name", "s_index", "sequence", "target_from_seqxlsx", "target_used"],
        )
        write_tsv(
            merge_path,
            block_merge_rows,
            ["sample_id", "s_index", "read_count", "offset", "overlap_match_ratio", "merged_fastq"],
        )
        write_tsv(
            run_status_path,
            run_rows,
            [
                "sample_id",
                "replicate",
                "condition",
                "s_index",
                "aseq",
                "rgen",
                "return_code",
                "summary_file",
                "summary_exists",
                "window_file",
                "window_exists",
                "same_length_file",
                "same_length_exists",
                "log_file",
            ],
        )
        write_tsv(skipped_path, [], ["sample_id", "reason"])
        write_tsv(
            edited_path,
            block_edited_rows,
            [
                "sample_id",
                "replicate",
                "condition",
                "s_index",
                "target_window_ref",
                "window_total_reads",
                "window_wt_reads",
                "edited_reads_percent",
                "maund_window_mutated",
                "maund_window_total",
                "maund_window_ratio",
                "maund_n_indels",
                "maund_n_all",
                "maund_indel_ratio",
            ],
        )
        build_miseq_summary_table(run_rows, miseq_path)

        _, _, tail_by_sample, tail_warnings = _load_tail_mapping_bundle(cfg=cfg, selected_ids=block_ids)
        warnings.extend(tail_warnings)
        per_sample_rows, ranked_rows, render_rows = build_sample_reports(
            run_rows=run_rows,
            preset=preset,
            tail_by_sample=tail_by_sample,
        )

        per_sample_by_id = {int(row["sample_id"]): row for row in per_sample_rows}
        ordered_per_sample_rows = [
            per_sample_by_id[sample_id]
            for _, sample_id in block.row_items
            if sample_id in per_sample_by_id
        ]
        heatmap_rows, heatmap_details, heatmap_columns = build_heatmap_tables(
            block=block,
            preset=preset,
            run_rows=run_rows,
        )

        per_sample_path = _path_with_prefix(dirs["tables"], "sample_editing", cfg.date_tag, block_slug, "tsv")
        ranked_path = _path_with_prefix(dirs["tables"], "ranked_haplotypes", cfg.date_tag, block_slug, "tsv")
        render_path = _path_with_prefix(dirs["tables"], "haplotype_render_rows", cfg.date_tag, block_slug, "tsv")
        heatmap_matrix_path = _path_with_prefix(dirs["tables"], "heatmap_matrix", cfg.date_tag, block_slug, "tsv")
        heatmap_detail_path = _path_with_prefix(dirs["tables"], "heatmap_detail", cfg.date_tag, block_slug, "tsv")
        report_path = _path_with_prefix(dirs["tables"], "report", cfg.date_tag, block_slug, "html")

        write_tsv(
            per_sample_path,
            ordered_per_sample_rows,
            [
                "sample_id",
                "replicate",
                "condition",
                "s_index",
                "tail_combo",
                "left_tail_module",
                "right_tail_module",
                "left_tail_sequence",
                "right_tail_sequence",
                "target_seq",
                "allowed_rule",
                "total_same_length_reads",
                "wt_reads",
                "wt_pct",
                "edited_reads_allowed_only",
                "edited_pct_allowed_only",
                "disallowed_mut_reads",
                "disallowed_mut_pct",
                "same_length_file",
            ],
        )
        write_tsv(
            ranked_path,
            ranked_rows,
            [
                "sample_id",
                "tail_combo",
                "left_tail_module",
                "right_tail_module",
                "target_seq",
                "edited_reads_allowed_only",
                "total_same_length_reads",
                "edited_pct_allowed_only",
                "disallowed_mut_pct",
            ],
        )
        write_tsv(
            render_path,
            render_rows,
            [
                "sample_id",
                "tail_combo",
                "left_tail_module",
                "right_tail_module",
                "target_seq",
                "rank",
                "haplotype",
                "reads",
                "edited_reads_percent",
                "primary_label",
                "primary_pct",
                "secondary_label",
                "secondary_pct",
                "same_length_total",
            ],
        )

        matrix_fields = ["sample_id", "row_label", "row_key", "is_wt", "total_same_length_reads"] + [
            str(column["field"]) for column in heatmap_columns
        ]
        write_tsv(heatmap_matrix_path, heatmap_rows, matrix_fields)
        write_tsv(
            heatmap_detail_path,
            heatmap_details,
            [
                "sample_id",
                "row_label",
                "row_key",
                "is_wt",
                "position",
                "ref_base",
                "intended_base",
                "intended_reads",
                "total_same_length_reads",
                "intended_pct",
                "is_highlighted",
            ],
        )

        report_title = f"{block.display_name} MAUND Report"
        report_path.write_text(
            render_block_report_html(
                title=report_title,
                block=block,
                preset=preset,
                per_sample_rows=ordered_per_sample_rows,
                ranked_rows=ranked_rows,
                render_rows=render_rows,
                heatmap_rows=heatmap_rows,
                heatmap_columns=heatmap_columns,
            )
        )

        key_paths[f"report_{block_slug}"] = report_path
        key_paths[f"heatmap_matrix_{block_slug}"] = heatmap_matrix_path
        key_paths[f"per_sample_editing_{block_slug}"] = per_sample_path
        all_outputs.extend(
            [
                merge_path,
                run_status_path,
                skipped_path,
                edited_path,
                mapping_path,
                miseq_path,
                per_sample_path,
                ranked_path,
                render_path,
                heatmap_matrix_path,
                heatmap_detail_path,
                report_path,
            ]
        )
        block_summaries.append(
            f"{block.display_name}: {block.sample_spec} | target={block.target_window} | desired={', '.join(block.desired_products) or 'not provided'}"
        )

    analysis_flow_path = dirs["tables"] / f"analysis_flow_{cfg.date_tag}.md"
    analysis_flow_path.write_text(
        build_analysis_flow_markdown(
            config=cfg,
            preset=preset,
            selected_sample_ids=selected_ids,
            outputs=all_outputs,
            warnings=list(_unique_messages(warnings)),
            block_summaries=block_summaries,
        )
    )
    key_paths["analysis_flow"] = analysis_flow_path

    _log(logger, f"Analysis completed: {run_root}")
    return RunResult(
        run_dir=run_root,
        status="completed_with_warnings" if warnings else "completed",
        key_output_paths=key_paths,
        warnings=_unique_messages(warnings),
    )


def run_analysis(config: AnalysisConfig, logger: LogFunc | None = None) -> RunResult:
    cfg = _normalized_config(config)
    validation = validate_config(cfg)
    if not validation.is_valid:
        raise ValueError("\n".join(validation.errors))
    if cfg.analysis_mode == "block_heatmap":
        return _run_block_heatmap_analysis(cfg, validation, logger)
    return _run_single_target_analysis(cfg, validation, logger)
