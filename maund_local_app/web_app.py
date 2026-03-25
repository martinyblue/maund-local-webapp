from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from maund_local_app.engine import run_analysis, validate_config
from maund_local_app.io_utils import (
    infer_flat_blocks,
    load_block_specs,
    parse_desired_products,
    parse_scaffold_sequence,
)
from maund_local_app.models import AnalysisConfig, BlockOverride, ValidationResult
from maund_local_app.presets import EDITOR_PRESETS
from maund_local_app.version import get_version


HOST = "127.0.0.1"
PORT = 8501
BLOCK_NAME_PREFIX = "block_name_"
DESIRED_PRODUCTS_PREFIX = "desired_products_"
SCAFFOLD_SEQUENCE_PREFIX = "scaffold_sequence_"

FIELD_DEFAULTS = {
    "fastq_dir": str(Path.home() / "Downloads"),
    "seq_xlsx": str(Path.home() / "Downloads" / "seq정보.xlsx"),
    "sample_tale_xlsx": str(Path.home() / "Downloads" / "sample id+ TALE.xlsx"),
    "tale_array_xlsx": str(
        Path.home() / "Downloads" / "TALE-array-Golden Gate assembly (조박사님) arabidopsis.xlsx"
    ),
    "output_base_dir": str(Path.home() / "Desktop"),
    "sample_scope": "",
    "exclude_scope": "",
    "target_seq": "",
    "editor_type": "taled",
    "analysis_mode": "single_target",
    "heatmap_scale_max": "5",
    "desired_products": "",
    "scaffold_sequence": "",
}

PICKER_FIELDS = {
    "fastq_dir": "directory",
    "seq_xlsx": "file",
    "sample_tale_xlsx": "file",
    "tale_array_xlsx": "file",
    "output_base_dir": "directory",
}

STATE: dict[str, object] = {
    "form": dict(FIELD_DEFAULTS),
    "messages": [],
    "validation": None,
    "result": None,
    "logs": [],
}


def _form() -> dict[str, str]:
    form = STATE.get("form")
    if not isinstance(form, dict):
        form = dict(FIELD_DEFAULTS)
        STATE["form"] = form
    return form


def _set_messages(messages: list[dict[str, str]]) -> None:
    STATE["messages"] = messages


def _clear_result_state() -> None:
    STATE["validation"] = None
    STATE["result"] = None
    STATE["logs"] = []


def _is_block_override_field(key: str) -> bool:
    return (
        key.startswith(BLOCK_NAME_PREFIX)
        or key.startswith(DESIRED_PRODUCTS_PREFIX)
        or key.startswith(SCAFFOLD_SEQUENCE_PREFIX)
    )


def _editor_family(form: dict[str, str]) -> str:
    editor_type = form.get("editor_type", "taled").strip().lower()
    preset = EDITOR_PRESETS.get(editor_type)
    return preset.analysis_family if preset is not None else "base_editing"


def _save_form(data: dict[str, str]) -> None:
    form = _form()
    for key in FIELD_DEFAULTS:
        if key in data:
            form[key] = data[key].strip()
    for key, value in data.items():
        if _is_block_override_field(key):
            form[key] = value.strip()
    STATE["form"] = form


def _parse_scope(text: str) -> tuple[int, ...]:
    cleaned = text.strip()
    if not cleaned:
        return ()
    parts: list[int] = []
    for token in cleaned.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            beg, end = token.split("-", 1)
            parts.extend(range(int(beg), int(end) + 1))
        elif "~" in token:
            beg, end = token.split("~", 1)
            parts.extend(range(int(beg), int(end) + 1))
        else:
            parts.append(int(token))
    return tuple(parts)


def _parse_block_overrides(form: dict[str, str]) -> tuple[BlockOverride, ...]:
    indices: set[int] = set()
    for key in form:
        match = re.match(r"^(?:block_name|desired_products|scaffold_sequence)_(\d+)$", key)
        if match:
            indices.add(int(match.group(1)))

    overrides: list[BlockOverride] = []
    for index in sorted(indices):
        name = form.get(f"{BLOCK_NAME_PREFIX}{index}", "").strip()
        desired_products = parse_desired_products(form.get(f"{DESIRED_PRODUCTS_PREFIX}{index}", ""))
        scaffold_sequence = parse_scaffold_sequence(form.get(f"{SCAFFOLD_SEQUENCE_PREFIX}{index}", ""))
        if name or desired_products or scaffold_sequence:
            overrides.append(
                BlockOverride(
                    block_index=index,
                    block_name=name,
                    desired_products=desired_products,
                    scaffold_sequence=scaffold_sequence,
                )
            )
    return tuple(overrides)


def _build_config_from_form(form: dict[str, str]) -> AnalysisConfig:
    editor_type = form["editor_type"]
    analysis_family = _editor_family(form)
    return AnalysisConfig(
        fastq_dir=Path(form["fastq_dir"]),
        seq_xlsx=Path(form["seq_xlsx"]),
        sample_tale_xlsx=(
            None
            if analysis_family == "prime_editing" or not form["sample_tale_xlsx"]
            else Path(form["sample_tale_xlsx"])
        ),
        tale_array_xlsx=(
            None
            if analysis_family == "prime_editing" or not form["tale_array_xlsx"]
            else Path(form["tale_array_xlsx"])
        ),
        sample_ids=_parse_scope(form["sample_scope"]),
        exclude_samples=_parse_scope(form["exclude_scope"]),
        target_seq=form["target_seq"].strip().upper(),
        editor_type=editor_type,
        desired_products=parse_desired_products(form.get("desired_products", "")),
        scaffold_sequence=parse_scaffold_sequence(form.get("scaffold_sequence", "")),
        analysis_mode=form.get("analysis_mode", "single_target"),
        heatmap_color_max_pct=float(form.get("heatmap_scale_max", "5").strip() or "5"),
        block_overrides=_parse_block_overrides(form),
        output_base_dir=Path(form["output_base_dir"]),
    )


def _resolve_initial_picker_dir(initial: str) -> Path:
    initial_path = Path(initial).expanduser()
    candidate = initial_path if initial_path.is_dir() else initial_path.parent
    return candidate if candidate.exists() else Path.home()


def _apple_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _powershell_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _build_macos_picker_command(kind: str, initial: str, prompt: str) -> list[str]:
    initial_dir = _resolve_initial_picker_dir(initial)
    choose_expr = "choose folder" if kind == "directory" else "choose file"
    script_lines = [
        f"set defaultLocation to POSIX file {_apple_string(str(initial_dir))}",
        f"set chosenItem to {choose_expr} with prompt {_apple_string(prompt)} default location defaultLocation",
        "POSIX path of chosenItem",
    ]
    command = ["/usr/bin/osascript"]
    for line in script_lines:
        command.extend(["-e", line])
    return command


def _build_windows_picker_command(kind: str, initial: str, prompt: str) -> list[str]:
    initial_dir = _resolve_initial_picker_dir(initial)
    if kind == "directory":
        script = "\n".join(
            [
                "Add-Type -AssemblyName System.Windows.Forms | Out-Null",
                "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog",
                f"$dialog.Description = {_powershell_string(prompt)}",
                f"$dialog.SelectedPath = {_powershell_string(str(initial_dir))}",
                "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {",
                "  [Console]::Out.Write($dialog.SelectedPath)",
                "}",
            ]
        )
    else:
        script = "\n".join(
            [
                "Add-Type -AssemblyName System.Windows.Forms | Out-Null",
                "$dialog = New-Object System.Windows.Forms.OpenFileDialog",
                f"$dialog.Title = {_powershell_string(prompt)}",
                f"$dialog.InitialDirectory = {_powershell_string(str(initial_dir))}",
                "$dialog.Filter = 'Excel files (*.xlsx)|*.xlsx|All files (*.*)|*.*'",
                "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {",
                "  [Console]::Out.Write($dialog.FileName)",
                "}",
            ]
        )
    return ["powershell", "-NoProfile", "-STA", "-Command", script]


def _run_picker_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("경로 선택창 실행 도구를 찾지 못했습니다.") from exc
    except subprocess.CalledProcessError as exc:
        details = "\n".join(part for part in [exc.stdout, exc.stderr] if part).strip()
        lowered = details.lower()
        if "user canceled" in lowered or "cancelled" in lowered or "canceled" in lowered or "-128" in details:
            return ""
        raise RuntimeError(details or f"경로 선택창 실행에 실패했습니다. exit={exc.returncode}") from exc
    return completed.stdout.strip()


def _choose_path(kind: str, initial: str, prompt: str) -> str:
    if sys.platform.startswith("darwin"):
        return _run_picker_command(_build_macos_picker_command(kind, initial, prompt))
    if os.name == "nt":
        return _run_picker_command(_build_windows_picker_command(kind, initial, prompt))
    raise RuntimeError("이 운영체제에서는 선택 버튼을 지원하지 않습니다. 경로를 직접 입력하세요.")


def _dialog_choose_directory(initial: str) -> str:
    return _choose_path("directory", initial, "폴더를 선택하세요.")


def _dialog_choose_file(initial: str) -> str:
    return _choose_path("file", initial, "파일을 선택하세요.")


def _open_path(path: str) -> None:
    if sys.platform.startswith("darwin"):
        subprocess.run(["open", path], check=False)
        return
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    subprocess.run(["xdg-open", path], check=False)


def _validation_value(validation: ValidationResult | dict[str, object] | None, key: str) -> object:
    if validation is None:
        return None
    if isinstance(validation, ValidationResult):
        return getattr(validation, key)
    if isinstance(validation, dict):
        return validation.get(key)
    return None


def _detected_blocks(validation: ValidationResult | dict[str, object] | None) -> list[dict[str, object]]:
    blocks = _validation_value(validation, "detected_blocks")
    out: list[dict[str, object]] = []
    if isinstance(blocks, tuple):
        blocks = list(blocks)
    if not isinstance(blocks, list):
        return out
    for block in blocks:
        if hasattr(block, "block_index"):
            row_items = [{"label": label, "sample_id": sample_id} for label, sample_id in getattr(block, "row_items")]
            out.append(
                {
                    "block_index": getattr(block, "block_index"),
                    "block_name": getattr(block, "block_name"),
                    "display_name": getattr(block, "display_name"),
                    "sample_spec": getattr(block, "sample_spec"),
                    "target_window": getattr(block, "target_window"),
                    "desired_products": list(getattr(block, "desired_products")),
                    "scaffold_sequence": getattr(block, "scaffold_sequence"),
                    "row_items": row_items,
                }
            )
            continue
        if isinstance(block, dict):
            row_items = []
            raw_rows = block.get("row_items", [])
            if isinstance(raw_rows, list):
                for item in raw_rows:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        row_items.append({"label": item[0], "sample_id": item[1]})
                    elif isinstance(item, dict):
                        row_items.append(
                            {
                                "label": item.get("label", item.get("row_key", "")),
                                "sample_id": item.get("sample_id", ""),
                            }
                        )
            display_name = str(block.get("block_name") or f"block_{block.get('block_index', '')}")
            out.append(
                {
                    "block_index": int(block.get("block_index", len(out) + 1)),
                    "block_name": str(block.get("block_name", "")),
                    "display_name": display_name,
                    "sample_spec": str(block.get("sample_spec", "")),
                    "target_window": str(block.get("target_window", "")),
                    "desired_products": [str(item) for item in block.get("desired_products", [])],
                    "scaffold_sequence": str(block.get("scaffold_sequence", "")),
                    "row_items": row_items,
                }
            )
    return out


def _preview_blocks(form: dict[str, str], validation: ValidationResult | dict[str, object] | None) -> list[dict[str, object]]:
    fallback = _detected_blocks(validation)
    if form.get("analysis_mode", "single_target") != "block_heatmap":
        return fallback

    seq_xlsx = Path(form.get("seq_xlsx", "")).expanduser()
    if not seq_xlsx.exists():
        return fallback

    try:
        overrides = _parse_block_overrides(form)
        default_desired_products = parse_desired_products(form.get("desired_products", ""))
        default_scaffold_sequence = parse_scaffold_sequence(form.get("scaffold_sequence", ""))
        blocks = load_block_specs(
            seq_xlsx,
            overrides,
            default_desired_products=default_desired_products,
            default_scaffold_sequence=default_scaffold_sequence,
        )
        if not blocks and _editor_family(form) == "prime_editing":
            blocks = infer_flat_blocks(
                seq_xlsx,
                overrides,
                default_desired_products=default_desired_products,
                default_scaffold_sequence=default_scaffold_sequence,
            )
        if not blocks:
            return fallback

        include = set(_parse_scope(form.get("sample_scope", "")))
        exclude = set(_parse_scope(form.get("exclude_scope", "")))
        filtered_blocks = []
        for block in blocks:
            row_items = tuple(
                (label, sample_id)
                for label, sample_id in block.row_items
                if (not include or sample_id in include) and sample_id not in exclude
            )
            if row_items:
                filtered_blocks.append(
                    {
                        "block_index": block.block_index,
                        "block_name": block.block_name,
                        "display_name": block.display_name,
                        "sample_spec": block.sample_spec,
                        "target_window": block.target_window,
                        "desired_products": list(block.desired_products),
                        "scaffold_sequence": block.scaffold_sequence,
                        "row_items": [{"label": label, "sample_id": sample_id} for label, sample_id in row_items],
                    }
                )
        return filtered_blocks or fallback
    except Exception:
        return fallback


def _validation_to_text(validation: ValidationResult | dict[str, object]) -> str:
    selected = _validation_value(validation, "selected_sample_ids") or []
    fastq_ids = _validation_value(validation, "available_fastq_ids") or []
    sequence_ids = _validation_value(validation, "available_sequence_ids") or []
    errors = _validation_value(validation, "errors") or []
    warnings = _validation_value(validation, "warnings") or []
    blocks = _detected_blocks(validation)

    lines = [
        f"유효 여부: {'정상' if bool(_validation_value(validation, 'is_valid')) else '오류 있음'}",
        "선택된 sample IDs: " + (", ".join(map(str, selected)) if selected else "없음"),
        "FASTQ에 있는 sample IDs: " + (", ".join(map(str, fastq_ids)) if fastq_ids else "없음"),
        "Sequence xlsx에 있는 sample IDs: " + (", ".join(map(str, sequence_ids)) if sequence_ids else "없음"),
    ]
    if blocks:
        lines.extend(["", "[감지된 블록]"])
        for block in blocks:
            desired = ", ".join(block["desired_products"]) if block["desired_products"] else "없음"
            scaffold = str(block.get("scaffold_sequence", "")).strip() or "없음"
            lines.append(
                f"- {block['display_name']}: samples={block['sample_spec']}, target={block['target_window']}, desired={desired}, scaffold={scaffold}"
            )
    if errors:
        lines.extend(["", "[오류]"])
        lines.extend(f"- {text}" for text in errors)
    if warnings:
        lines.extend(["", "[경고]"])
        lines.extend(f"- {text}" for text in warnings)
    return "\n".join(lines)


def _picker_rows(form: dict[str, str]) -> list[dict[str, str]]:
    rows = [
        {
            "name": "fastq_dir",
            "label": "FASTQ 폴더",
            "button": "폴더 선택",
            "hint": "R1/R2 FASTQ 파일이 들어 있는 폴더를 Finder 또는 파일 선택창에서 고르세요.",
        },
        {
            "name": "seq_xlsx",
            "label": "Sequence xlsx",
            "button": "파일 선택",
            "hint": "기본 분석은 단순 sample/sequence/target 형식도 가능하고 `68(wild type)` 같은 표기도 읽습니다. heatmap 분석은 block 구조 xlsx를 기본으로 쓰고, Prime Editing은 flat xlsx 1개도 자동으로 1개 block으로 인식할 수 있습니다.",
        },
        {
            "name": "output_base_dir",
            "label": "결과 저장 폴더",
            "button": "폴더 선택",
            "hint": "분석 결과 폴더 `maund_<날짜>_<시간>` 이 생성될 상위 폴더를 선택하세요.",
        },
    ]
    if _editor_family(form) != "prime_editing":
        rows[2:2] = [
            {
                "name": "sample_tale_xlsx",
                "label": "Sample TALE xlsx (선택 사항)",
                "button": "파일 선택",
                "hint": "sample ID와 Left/Right module 매핑이 들어 있는 xlsx 파일입니다. 없으면 tail mapping 결과가 생략됩니다.",
            },
            {
                "name": "tale_array_xlsx",
                "label": "TALE array xlsx (선택 사항)",
                "button": "파일 선택",
                "hint": "Left/Right tail sequence를 채우고 싶을 때 사용하는 xlsx 파일입니다.",
            },
        ]
    return rows


def _esc(text: object) -> str:
    return html.escape(str(text))


def _mode_options(form: dict[str, str]) -> str:
    options = [
        ("single_target", "기본 분석"),
        ("block_heatmap", "heatmap 분석"),
    ]
    chunks = []
    for value, label in options:
        selected = "selected" if form.get("analysis_mode", "single_target") == value else ""
        chunks.append(f'<option value="{_esc(value)}" {selected}>{_esc(label)}</option>')
    return "".join(chunks)


def _heatmap_scale_options(form: dict[str, str]) -> str:
    options = [
        ("1", "0-1"),
        ("5", "0-5"),
        ("100", "0-100"),
    ]
    selected_value = form.get("heatmap_scale_max", "5")
    chunks = []
    for value, label in options:
        selected = "selected" if selected_value == value else ""
        chunks.append(f'<option value="{_esc(value)}" {selected}>{_esc(label)}</option>')
    return "".join(chunks)


def _render_block_override_section(
    form: dict[str, str],
    validation: ValidationResult | dict[str, object] | None,
) -> str:
    if form.get("analysis_mode", "single_target") != "block_heatmap":
        return ""
    blocks = _preview_blocks(form, validation)
    is_prime = _editor_family(form) == "prime_editing"
    if not blocks:
        return """
        <div class="card">
          <h2>블록 미리보기</h2>
          <div class="hint">`입력 확인`을 누르면 xlsx에서 감지된 block과 block별 이름/desired product 입력칸이 여기에 표시됩니다. Prime Editing은 flat xlsx여도 inferred block 1개로 표시될 수 있습니다.</div>
        </div>
        """

    rows: list[str] = []
    for block in blocks:
        index = int(block["block_index"])
        block_name_key = f"{BLOCK_NAME_PREFIX}{index}"
        desired_key = f"{DESIRED_PRODUCTS_PREFIX}{index}"
        scaffold_key = f"{SCAFFOLD_SEQUENCE_PREFIX}{index}"
        desired_default = ", ".join(block["desired_products"])
        scaffold_default = str(block.get("scaffold_sequence", ""))
        scaffold_row = ""
        if is_prime:
            scaffold_row = f"""
              <div class="row">
                <label for="{_esc(scaffold_key)}">Scaffold sequence (optional)</label>
                <input type="text" id="{_esc(scaffold_key)}" name="{_esc(scaffold_key)}" value="{_esc(form.get(scaffold_key, scaffold_default))}" />
                <div class="hint">scaffold-derived byproduct를 따로 분류하고 싶을 때만 입력하세요. 비우면 scaffold 분류를 사용하지 않습니다.</div>
              </div>
            """
        rows.append(
            f"""
            <div class="block-box">
              <div class="block-head">
                <div class="block-title">{_esc(block['display_name'])}</div>
                <div class="block-meta">samples {_esc(block['sample_spec'])}</div>
              </div>
              <div class="hint">target: <span class="mono">{_esc(block['target_window'])}</span></div>
              <div class="hint">rows: {_esc(", ".join(f"{item['label']}={item['sample_id']}" for item in block['row_items']))}</div>
              <div class="row">
                <label for="{_esc(block_name_key)}">Block 이름</label>
                <input type="text" id="{_esc(block_name_key)}" name="{_esc(block_name_key)}" value="{_esc(form.get(block_name_key, str(block['display_name'])))}" />
                <div class="hint">xlsx 이름을 바꾸고 싶을 때만 수정하세요. 비우면 xlsx 또는 자동 이름을 사용합니다.</div>
              </div>
              <div class="row">
                <label for="{_esc(desired_key)}">Desired product sequence</label>
                <textarea id="{_esc(desired_key)}" name="{_esc(desired_key)}" rows="3">{_esc(form.get(desired_key, desired_default))}</textarea>
                <div class="hint">여러 개면 쉼표 또는 줄바꿈으로 구분하세요. 비우면 xlsx 값 또는 기본값을 사용합니다.</div>
              </div>
              {scaffold_row}
            </div>
            """
        )
    block_hint = "heatmap 분석에서는 아래 block별 이름과 desired product를 필요할 때만 수정하면 됩니다."
    if is_prime:
        block_hint = "Prime Editing heatmap 분석에서는 block별 desired product와 optional scaffold를 여기서 보완할 수 있습니다."
    return f"""
    <div class="card">
      <h2>블록 미리보기와 보완 입력</h2>
      <div class="hint">{_esc(block_hint)}</div>
      {''.join(rows)}
    </div>
    """


def _render_result_actions(result: dict[str, object]) -> str:
    key_paths = result.get("key_output_paths", {})
    if not isinstance(key_paths, dict):
        return ""

    buttons = [
        '<form method="post" action="/open/run_dir" style="display:inline;"><button type="submit">결과 폴더 열기</button></form>'
    ]

    report_keys = sorted(key for key in key_paths if key == "html_report" or key.startswith("report_"))
    for key in report_keys:
        if key == "html_report":
            label = "HTML 결과 열기"
        else:
            label = f"{key.removeprefix('report_').upper()} HTML 열기"
        buttons.append(
            f'<form method="post" action="/open/{_esc(key)}" style="display:inline;"><button type="submit" class="secondary">{_esc(label)}</button></form>'
        )

    if "analysis_flow" in key_paths:
        buttons.append(
            '<form method="post" action="/open/analysis_flow" style="display:inline;"><button type="submit" class="ghost">분석 메모 열기</button></form>'
        )
    return "".join(buttons)


def _render_page() -> str:
    form = _form()
    analysis_family = _editor_family(form)
    is_prime = analysis_family == "prime_editing"
    messages = STATE.get("messages", [])
    validation = STATE.get("validation")
    result = STATE.get("result")
    logs = STATE.get("logs", [])

    picker_rows_html = []
    for field in _picker_rows(form):
        picker_rows_html.append(
            f"""
            <div class="row">
              <label for="{_esc(field['name'])}">{_esc(field['label'])}</label>
              <div class="picker">
                <input type="text" id="{_esc(field['name'])}" name="{_esc(field['name'])}" value="{_esc(form[field['name']])}" />
                <button type="submit" name="action" value="pick:{_esc(field['name'])}" class="ghost">{_esc(field['button'])}</button>
              </div>
              <div class="hint">{_esc(field['hint'])}</div>
            </div>
            """
        )

    preset_options = []
    for key, preset in EDITOR_PRESETS.items():
        selected = "selected" if form["editor_type"] == key else ""
        preset_options.append(
            f'<option value="{_esc(key)}" {selected}>{_esc(preset.label)} ({_esc(preset.allowed_rule_text)})</option>'
        )

    message_blocks = []
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                message_blocks.append(
                    f'<div class="msg {_esc(message.get("kind", "warn"))}">{_esc(message.get("text", ""))}</div>'
                )

    validation_block = ""
    if isinstance(validation, (ValidationResult, dict)):
        validation_block = f"""
        <div class="card">
          <h2>입력 확인 결과</h2>
          <pre>{_esc(_validation_to_text(validation))}</pre>
        </div>
        """

    logs_block = ""
    if isinstance(logs, list) and logs:
        logs_block = f"""
        <div class="card">
          <h2>실행 로그</h2>
          <pre>{_esc(chr(10).join(map(str, logs)))}</pre>
        </div>
        """

    result_block = ""
    if isinstance(result, dict):
        output_boxes = []
        key_paths = result.get("key_output_paths", {})
        if isinstance(key_paths, dict):
            for key, value in key_paths.items():
                output_boxes.append(
                    f"""
                    <div class="result-box">
                      <div class="title">{_esc(key)}</div>
                      <div class="value mono">{_esc(value)}</div>
                    </div>
                    """
                )
        result_block = f"""
        <div class="card">
          <h2>결과</h2>
          <div class="result-grid">
            {''.join(output_boxes)}
          </div>
          <div class="actions">
            {_render_result_actions(result)}
          </div>
        </div>
        """

    target_block = """
          <div class="row">
            <label for="target_seq">Target sequence</label>
            <input type="text" id="target_seq" name="target_seq" value="{target_value}" />
            <div class="hint">분석할 target sequence를 그대로 붙여넣으세요. 예: <span class="mono">AAATGAATCTGCTAATGAA</span></div>
          </div>
    """.format(target_value=_esc(form["target_seq"]))
    if form.get("analysis_mode", "single_target") == "block_heatmap":
        target_block = """
          <div class="row">
            <label>Target sequence</label>
            <input type="text" value="" disabled />
            <div class="hint">heatmap 분석에서는 target sequence를 직접 입력하지 않습니다. seq xlsx 안의 block target 또는 Prime flat xlsx에서 inferred target을 사용합니다.</div>
          </div>
        """

    heatmap_scale_block = ""
    if form.get("analysis_mode", "single_target") == "block_heatmap":
        heatmap_scale_block = f"""
          <div class="row">
            <label for="heatmap_scale_max">Heatmap 색상 범위</label>
            <select id="heatmap_scale_max" name="heatmap_scale_max">
              {_heatmap_scale_options(form)}
            </select>
            <div class="hint">heatmap 셀 숫자는 실제 %를 그대로 보여주고, 색상만 선택한 범위로 잘라서 표시합니다. 아주 낮은 편집율 차이를 강하게 보려면 <span class="mono">0-1</span>, 현재 데이터처럼 낮은 편집율을 보려면 <span class="mono">0-5</span>, 논문 그림처럼 넓은 범위 기준으로 보려면 <span class="mono">0-100</span>을 고르면 됩니다.</div>
          </div>
        """

    block_override_section = _render_block_override_section(form, validation)
    prime_input_block = ""
    if is_prime:
        desired_hint = (
            "원하는 edited sequence를 그대로 넣으세요. 여러 개면 쉼표 또는 줄바꿈으로 구분합니다. 예: ACATTTCGTCCTAGCTGCTTGGCCTGT. v1에서는 target과 길이가 같은 substitution형만 지원합니다."
        )
        if form.get("analysis_mode", "single_target") == "block_heatmap":
            desired_hint = (
                "Prime heatmap 분석에서 flat xlsx를 쓰는 경우, 여기 입력한 desired product를 inferred block의 기본값으로 사용합니다. block이 여러 개면 아래 block 보완 입력에서 각각 덮어쓸 수 있습니다."
            )
        prime_input_block = f"""
          <div class="row">
            <label for="desired_products">Desired edited sequence</label>
            <textarea id="desired_products" name="desired_products" rows="3">{_esc(form.get("desired_products", ""))}</textarea>
            <div class="hint">{_esc(desired_hint)}</div>
          </div>
          <div class="row">
            <label for="scaffold_sequence">Scaffold sequence (optional)</label>
            <input type="text" id="scaffold_sequence" name="scaffold_sequence" value="{_esc(form.get("scaffold_sequence", ""))}" />
            <div class="hint">scaffold-derived byproduct를 따로 분류하고 싶을 때만 입력하세요. 공백은 자동으로 제거합니다.</div>
          </div>
        """
    editor_hint = "TALED는 A>G, T>C, DdCBE는 C>T, G>A 규칙을 사용합니다."
    if is_prime:
        editor_hint = "Prime Editing은 desired edited sequence를 기준으로 exact intended / intended+extra / other substitution / optional scaffold-derived / indel only 를 분리합니다."

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MAUND Local Web App</title>
  <style>
    :root {{
      --bg: #f7f4ee;
      --panel: #fffdf9;
      --ink: #1f2328;
      --sub: #59606a;
      --line: #d8d1c5;
      --accent: #8a5a2b;
      --accent-2: #ece4d8;
      --ok: #dff3e6;
      --warn: #fff3d7;
      --err: #fde1df;
    }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top right, rgba(168, 122, 72, 0.10), transparent 30%),
        linear-gradient(180deg, #fbf8f2 0%, #f6f2ea 100%);
      color: var(--ink);
      font-family: "Apple SD Gothic Neo", "Malgun Gothic", "Segoe UI", sans-serif;
    }}
    .wrap {{
      max-width: 1160px;
      margin: 0 auto;
      padding: 24px 18px 40px;
    }}
    h1 {{ margin: 0; font-size: 30px; }}
    h2 {{ margin-top: 0; }}
    .title-row {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }}
    .version-badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      background: #efe4d4;
      color: var(--accent);
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 700;
    }}
    .lead {{ margin: 0 0 18px; color: var(--sub); line-height: 1.6; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 8px 28px rgba(28, 24, 18, 0.05);
      margin-bottom: 16px;
    }}
    .steps {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .step {{ background: #f4ede2; border-radius: 14px; padding: 12px 14px; }}
    .step .num {{ font-size: 12px; color: var(--accent); font-weight: 700; margin-bottom: 4px; }}
    .step .txt {{ font-size: 14px; line-height: 1.5; }}
    .grid {{ display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 16px; }}
    .row {{ margin-bottom: 12px; }}
    label {{ display: block; font-weight: 700; margin-bottom: 6px; }}
    .hint {{ font-size: 12px; color: var(--sub); margin-top: 4px; line-height: 1.5; white-space: pre-wrap; }}
    .picker {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; }}
    input[type="text"], select, textarea {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 11px 12px;
      font-size: 14px;
      background: white;
      font-family: inherit;
    }}
    textarea {{
      resize: vertical;
      min-height: 82px;
    }}
    input[disabled] {{
      background: #f6f1e8;
      color: #7a746b;
    }}
    button {{
      border: 0;
      border-radius: 12px;
      background: var(--accent);
      color: white;
      padding: 11px 14px;
      font-size: 14px;
      cursor: pointer;
    }}
    button.secondary {{ background: #6e7681; }}
    button.ghost {{ background: var(--accent-2); color: var(--ink); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }}
    .msg {{ border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; line-height: 1.5; white-space: pre-wrap; }}
    .ok {{ background: var(--ok); }}
    .warn {{ background: var(--warn); }}
    .err {{ background: var(--err); }}
    .mono, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    pre {{
      background: #faf7f2;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      overflow: auto;
      white-space: pre-wrap;
      line-height: 1.45;
    }}
    .result-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin-top: 10px;
    }}
    .result-box {{ background: #f4ede2; border-radius: 12px; padding: 12px; }}
    .result-box .title {{ font-size: 12px; color: var(--sub); margin-bottom: 6px; }}
    .result-box .value {{ word-break: break-all; font-size: 14px; }}
    .block-box {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fbf7f0;
      padding: 14px;
      margin-top: 10px;
    }}
    .block-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      flex-wrap: wrap;
    }}
    .block-title {{ font-size: 17px; font-weight: 700; }}
    .block-meta {{ color: var(--sub); font-size: 13px; }}
    @media (max-width: 880px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .picker {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title-row">
      <h1>MAUND Local Web App</h1>
      <div class="version-badge">Version v{_esc(get_version())}</div>
    </div>
    <p class="lead">
      이 페이지는 <b>내 컴퓨터 안에서만</b> 실행되는 로컬 분석 화면입니다.<br />
      브라우저가 자동으로 열리지 않으면 주소창을 한 번 클릭한 뒤 <span class="mono">http://127.0.0.1:8501</span> 를 그대로 붙여넣고 Enter를 누르세요.
    </p>
    <div class="steps">
      <div class="step"><div class="num">STEP 1</div><div class="txt">각 입력칸 오른쪽의 <b>선택</b> 버튼을 누르면 Finder 또는 파일 선택창이 뜹니다. 잠깐 로딩처럼 보여도 정상입니다.</div></div>
      <div class="step"><div class="num">STEP 2</div><div class="txt"><b>입력 확인</b> 버튼을 눌러 오류가 없는지 확인합니다. heatmap 분석은 이 단계에서 block 미리보기가 생깁니다.</div></div>
      <div class="step"><div class="num">STEP 3</div><div class="txt"><b>분석 실행</b> 버튼을 누른 뒤 완료될 때까지 기다립니다. block마다 별도 HTML 결과가 만들어집니다.</div></div>
      <div class="step"><div class="num">STEP 4</div><div class="txt">완료되면 <b>결과 폴더 열기</b> 또는 block별 <b>HTML 열기</b> 버튼으로 결과를 바로 확인합니다.</div></div>
    </div>

    <form method="post" action="/action">
      <div class="grid">
        <div>
          <div class="card">
            <h2>입력 파일과 폴더</h2>
            {''.join(picker_rows_html)}
          </div>
          {block_override_section}
        </div>
        <div class="card">
          <h2>분석 설정</h2>
          <div class="row">
            <label for="analysis_mode">분석 모드</label>
            <select id="analysis_mode" name="analysis_mode">
              {_mode_options(form)}
            </select>
            <div class="hint">기본 분석은 기존 방식이고, heatmap 분석은 xlsx 안의 block을 자동 감지해 block별 HTML과 heatmap을 만듭니다. block은 1개만 있어도 됩니다.</div>
          </div>
          <div class="row">
            <label for="sample_scope">분석할 샘플 번호</label>
            <input type="text" id="sample_scope" name="sample_scope" value="{_esc(form['sample_scope'])}" />
            <div class="hint">예시: <span class="mono">71,72,75-85</span>. 비워두면 자동으로 가능한 샘플 전체를 사용합니다.</div>
          </div>
          <div class="row">
            <label for="exclude_scope">제외할 샘플 번호</label>
            <input type="text" id="exclude_scope" name="exclude_scope" value="{_esc(form['exclude_scope'])}" />
            <div class="hint">예시: <span class="mono">73,74</span>. 제외할 샘플만 적으세요.</div>
          </div>
          {target_block}
          {heatmap_scale_block}
          <div class="row">
            <label for="editor_type">Editor type</label>
            <select id="editor_type" name="editor_type">
              {''.join(preset_options)}
            </select>
            <div class="hint">{_esc(editor_hint)}</div>
          </div>
          {prime_input_block}
          <div class="actions">
            <button type="submit" name="action" value="validate">입력 확인</button>
            <button type="submit" name="action" value="run" class="secondary">분석 실행</button>
            <button type="submit" name="action" value="reset" class="ghost">입력값 초기화</button>
          </div>
        </div>
      </div>
    </form>

    {'<div class="card"><h2>상태</h2>' + ''.join(message_blocks) + '</div>' if message_blocks else ''}
    {validation_block}
    {logs_block}
    {result_block}
  </div>
</body>
</html>
"""


def _handle_action(data: dict[str, str]) -> None:
    _save_form(data)
    form = _form()
    action = data.get("action", "")
    messages: list[dict[str, str]] = []

    if action == "reset":
        STATE["form"] = dict(FIELD_DEFAULTS)
        _clear_result_state()
        _set_messages([{"kind": "ok", "text": "입력값을 기본값으로 초기화했습니다."}])
        return

    if action.startswith("pick:"):
        field = action.split(":", 1)[1]
        if field in PICKER_FIELDS:
            try:
                if PICKER_FIELDS[field] == "directory":
                    selected = _dialog_choose_directory(form.get(field, ""))
                else:
                    selected = _dialog_choose_file(form.get(field, ""))
            except Exception as exc:
                messages.append({"kind": "err", "text": f"선택창을 여는 중 오류가 발생했습니다.\n{exc}"})
            else:
                if selected:
                    form[field] = selected
                    STATE["form"] = form
                    messages.append({"kind": "ok", "text": f"{field} 경로를 선택했습니다."})
                else:
                    messages.append({"kind": "warn", "text": "경로 선택이 취소되었습니다."})
        _set_messages(messages)
        return

    try:
        config = _build_config_from_form(form)
    except Exception as exc:
        _set_messages([{"kind": "err", "text": f"입력값을 해석할 수 없습니다.\n{exc}"}])
        return

    try:
        validation = validate_config(config)
    except Exception as exc:
        STATE["validation"] = None
        _set_messages([{"kind": "err", "text": f"입력 확인 중 오류가 발생했습니다.\n{exc}"}])
        return

    STATE["validation"] = validation

    if action == "validate":
        if validation.is_valid:
            if config.analysis_mode == "block_heatmap":
                messages.append(
                    {
                        "kind": "ok",
                        "text": f"입력 확인이 끝났습니다. 감지된 block은 {len(validation.detected_blocks)}개입니다. 필요하면 block 이름/desired product를 수정한 뒤 분석 실행을 누르세요.",
                    }
                )
            else:
                messages.append({"kind": "ok", "text": "입력 확인이 끝났습니다. 이제 '분석 실행'을 눌러도 됩니다."})
        else:
            messages.append({"kind": "err", "text": "입력 오류가 있습니다. 아래 '입력 확인 결과'를 보고 수정하세요."})
        _set_messages(messages)
        return

    if action == "run":
        if not validation.is_valid:
            messages.append({"kind": "err", "text": "입력 확인에서 오류가 있어 실행할 수 없습니다. 먼저 오류를 수정하세요."})
            _set_messages(messages)
            return

        logs: list[str] = []

        def logger(message: str) -> None:
            logs.append(message)

        try:
            result = run_analysis(config, logger=logger)
        except Exception as exc:
            STATE["logs"] = logs
            _set_messages([{"kind": "err", "text": f"분석 실행 중 오류가 발생했습니다.\n{exc}"}])
            return

        STATE["logs"] = logs
        STATE["result"] = {
            "run_dir": str(result.run_dir),
            "status": result.status,
            "warnings": list(result.warnings),
            "key_output_paths": {key: str(path) for key, path in result.key_output_paths.items()},
        }
        if config.analysis_mode == "block_heatmap":
            messages.append(
                {"kind": "ok", "text": "분석이 완료되었습니다. 아래에서 결과 폴더와 block별 HTML 리포트를 바로 열 수 있습니다."}
            )
        else:
            messages.append({"kind": "ok", "text": "분석이 완료되었습니다. 아래 결과 영역에서 폴더와 HTML을 바로 열 수 있습니다."})
        for warning in result.warnings:
            messages.append({"kind": "warn", "text": warning})
        _set_messages(messages)
        return

    _set_messages([{"kind": "warn", "text": "알 수 없는 동작 요청입니다."}])


def _open_output(kind: str) -> None:
    result = STATE.get("result")
    if not isinstance(result, dict):
        _set_messages([{"kind": "err", "text": "열 수 있는 결과가 아직 없습니다. 먼저 분석을 실행하세요."}])
        return
    key_paths = result.get("key_output_paths", {})
    if not isinstance(key_paths, dict) or kind not in key_paths:
        _set_messages([{"kind": "err", "text": f"결과 항목을 찾을 수 없습니다: {kind}"}])
        return
    _open_path(str(key_paths[kind]))
    _set_messages([{"kind": "ok", "text": f"{kind} 을(를) 열었습니다."}])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", ""}:
            try:
                body = _render_page().encode("utf-8")
            except Exception as exc:
                body = (
                    "<!doctype html><html lang='ko'><body><pre>"
                    + html.escape(f"페이지 렌더링 중 오류가 발생했습니다.\n{exc}")
                    + "</pre></body></html>"
                ).encode("utf-8")
                self.send_response(500)
            else:
                self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        data = {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}

        if parsed.path == "/action":
            try:
                _handle_action(data)
            except Exception as exc:
                _set_messages([{"kind": "err", "text": f"요청 처리 중 오류가 발생했습니다.\n{exc}"}])
            self._redirect("/")
            return

        if parsed.path.startswith("/open/"):
            kind = parsed.path.split("/open/", 1)[1]
            try:
                _open_output(kind)
            except Exception as exc:
                _set_messages([{"kind": "err", "text": f"결과를 여는 중 오류가 발생했습니다.\n{exc}"}])
            self._redirect("/")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def _redirect(self, target: str) -> None:
        self.send_response(303)
        self.send_header("Location", target)
        self.end_headers()


def main() -> int:
    if os.environ.get("MAUND_OPEN_BROWSER", "1") == "1":
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    with ThreadingHTTPServer((HOST, PORT), Handler) as server:
        print(f"MAUND Local Web App running at http://{HOST}:{PORT}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
