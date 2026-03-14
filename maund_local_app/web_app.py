from __future__ import annotations

import html
import os
import subprocess
import sys
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from maund_local_app.engine import run_analysis, validate_config
from maund_local_app.models import AnalysisConfig
from maund_local_app.presets import EDITOR_PRESETS
from maund_local_app.version import __version__


HOST = "127.0.0.1"
PORT = 8501

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


def _save_form(data: dict[str, str]) -> None:
    form = _form()
    for key in FIELD_DEFAULTS:
        if key in data:
            form[key] = data[key].strip()
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


def _build_config_from_form(form: dict[str, str]) -> AnalysisConfig:
    return AnalysisConfig(
        fastq_dir=Path(form["fastq_dir"]),
        seq_xlsx=Path(form["seq_xlsx"]),
        sample_tale_xlsx=Path(form["sample_tale_xlsx"]) if form["sample_tale_xlsx"] else None,
        tale_array_xlsx=Path(form["tale_array_xlsx"]) if form["tale_array_xlsx"] else None,
        sample_ids=_parse_scope(form["sample_scope"]),
        exclude_samples=_parse_scope(form["exclude_scope"]),
        target_seq=form["target_seq"].strip().upper(),
        editor_type=form["editor_type"],
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


def _validation_to_text(validation: dict[str, object]) -> str:
    selected = validation.get("selected_sample_ids", [])
    fastq_ids = validation.get("available_fastq_ids", [])
    sequence_ids = validation.get("available_sequence_ids", [])
    errors = validation.get("errors", [])
    warnings = validation.get("warnings", [])

    lines = [
        f"유효 여부: {'정상' if validation.get('is_valid') else '오류 있음'}",
        "선택된 sample IDs: " + (", ".join(map(str, selected)) if selected else "없음"),
        "FASTQ에 있는 sample IDs: " + (", ".join(map(str, fastq_ids)) if fastq_ids else "없음"),
        "Sequence xlsx에 있는 sample IDs: " + (", ".join(map(str, sequence_ids)) if sequence_ids else "없음"),
    ]
    if errors:
        lines.extend(["", "[오류]"])
        lines.extend(f"- {text}" for text in errors)
    if warnings:
        lines.extend(["", "[경고]"])
        lines.extend(f"- {text}" for text in warnings)
    return "\n".join(lines)


def _picker_rows() -> list[dict[str, str]]:
    return [
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
            "hint": "sample ID, sequence, target window가 들어 있는 xlsx 파일을 선택하세요.",
        },
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
        {
            "name": "output_base_dir",
            "label": "결과 저장 폴더",
            "button": "폴더 선택",
            "hint": "분석 결과 폴더 `maund_<날짜>`가 생성될 상위 폴더를 선택하세요.",
        },
    ]


def _esc(text: object) -> str:
    return html.escape(str(text))


def _render_page() -> str:
    form = _form()
    messages = STATE.get("messages", [])
    validation = STATE.get("validation")
    result = STATE.get("result")
    logs = STATE.get("logs", [])

    picker_rows_html = []
    for field in _picker_rows():
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
    if isinstance(validation, dict):
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
            <form method="post" action="/open/run_dir" style="display:inline;"><button type="submit">결과 폴더 열기</button></form>
            <form method="post" action="/open/html_report" style="display:inline;"><button type="submit" class="secondary">HTML 결과 열기</button></form>
            <form method="post" action="/open/analysis_flow" style="display:inline;"><button type="submit" class="ghost">분석 메모 열기</button></form>
          </div>
        </div>
        """

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
    .hint {{ font-size: 12px; color: var(--sub); margin-top: 4px; line-height: 1.5; }}
    .picker {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; }}
    input[type="text"], select {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 11px 12px;
      font-size: 14px;
      background: white;
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
      <div class="version-badge">Version v{_esc(__version__)}</div>
    </div>
    <p class="lead">
      이 페이지는 <b>내 컴퓨터 안에서만</b> 실행되는 로컬 분석 화면입니다.<br />
      브라우저가 자동으로 열리지 않으면 주소창을 한 번 클릭한 뒤 <span class="mono">http://127.0.0.1:8501</span> 를 그대로 붙여넣고 Enter를 누르세요.
    </p>
    <div class="steps">
      <div class="step"><div class="num">STEP 1</div><div class="txt">각 입력칸 오른쪽의 <b>선택</b> 버튼을 누르면 Finder 또는 파일 선택창이 뜹니다. 이때 브라우저가 잠깐 로딩처럼 보여도 정상입니다.</div></div>
      <div class="step"><div class="num">STEP 2</div><div class="txt"><b>입력 확인</b> 버튼을 눌러 오류가 없는지 확인합니다.</div></div>
      <div class="step"><div class="num">STEP 3</div><div class="txt"><b>분석 실행</b> 버튼을 누른 뒤 완료될 때까지 기다립니다. 분석 중에는 브라우저 탭을 닫지 않는 것이 안전합니다.</div></div>
      <div class="step"><div class="num">STEP 4</div><div class="txt">완료되면 <b>결과 폴더 열기</b> 또는 <b>HTML 결과 열기</b> 버튼으로 결과를 바로 확인합니다.</div></div>
    </div>

    <form method="post" action="/action">
      <div class="grid">
        <div class="card">
          <h2>입력 파일과 폴더</h2>
          {''.join(picker_rows_html)}
        </div>
        <div class="card">
          <h2>분석 설정</h2>
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
          <div class="row">
            <label for="target_seq">Target sequence</label>
            <input type="text" id="target_seq" name="target_seq" value="{_esc(form['target_seq'])}" />
            <div class="hint">분석할 target sequence를 그대로 붙여넣으세요. 예: <span class="mono">AAATGAATCTGCTAATGAA</span></div>
          </div>
          <div class="row">
            <label for="editor_type">Editor type</label>
            <select id="editor_type" name="editor_type">
              {''.join(preset_options)}
            </select>
            <div class="hint">TALED는 <span class="mono">A&gt;G, T&gt;C</span>, DdCBE는 <span class="mono">C&gt;T, G&gt;A</span> 규칙을 사용합니다.</div>
          </div>
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

    validation = validate_config(config)
    STATE["validation"] = asdict(validation)

    if action == "validate":
        if validation.is_valid:
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
            body = _render_page().encode("utf-8")
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
            _handle_action(data)
            self._redirect("/")
            return

        if parsed.path.startswith("/open/"):
            kind = parsed.path.split("/open/", 1)[1]
            _open_output(kind)
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
