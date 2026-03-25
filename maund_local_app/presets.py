from __future__ import annotations

from .models import EditorPreset


EDITOR_PRESETS: dict[str, EditorPreset] = {
    "taled": EditorPreset(
        key="taled",
        label="TALED",
        analysis_family="base_editing",
        allowed_substitutions=frozenset({("A", "G"), ("T", "C")}),
        allowed_rule_text="A>G,T>C (allowed-only, OR)",
        primary_metric_label="A>G or T>C (allowed-only, OR) (%)",
    ),
    "ddcbe": EditorPreset(
        key="ddcbe",
        label="DdCBE",
        analysis_family="base_editing",
        allowed_substitutions=frozenset({("C", "T"), ("G", "A")}),
        allowed_rule_text="C>T,G>A (allowed-only, OR)",
        primary_metric_label="C>T or G>A (allowed-only, OR) (%)",
    ),
    "prime": EditorPreset(
        key="prime",
        label="Prime Editing",
        analysis_family="prime_editing",
        allowed_substitutions=frozenset(),
        allowed_rule_text="Exact intended edit / intended+extra / indel / optional scaffold-derived",
        primary_metric_label="Exact intended edit (%)",
    ),
}


def get_editor_preset(editor_type: str) -> EditorPreset:
    key = editor_type.strip().lower()
    if key not in EDITOR_PRESETS:
        allowed = ", ".join(sorted(EDITOR_PRESETS))
        raise ValueError(f"Unsupported editor_type: {editor_type}. Allowed values: {allowed}")
    return EDITOR_PRESETS[key]
