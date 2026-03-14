from __future__ import annotations

from .models import EditorPreset


EDITOR_PRESETS: dict[str, EditorPreset] = {
    "taled": EditorPreset(
        key="taled",
        label="TALED",
        allowed_substitutions=frozenset({("A", "G"), ("T", "C")}),
        allowed_rule_text="A>G,T>C (allowed-only, OR)",
        primary_metric_label="A>G or T>C (allowed-only, OR) (%)",
    ),
    "ddcbe": EditorPreset(
        key="ddcbe",
        label="DdCBE",
        allowed_substitutions=frozenset({("C", "T"), ("G", "A")}),
        allowed_rule_text="C>T,G>A (allowed-only, OR)",
        primary_metric_label="C>T or G>A (allowed-only, OR) (%)",
    ),
}


def get_editor_preset(editor_type: str) -> EditorPreset:
    key = editor_type.strip().lower()
    if key not in EDITOR_PRESETS:
        allowed = ", ".join(sorted(EDITOR_PRESETS))
        raise ValueError(f"Unsupported editor_type: {editor_type}. Allowed values: {allowed}")
    return EDITOR_PRESETS[key]
