from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from maund_local_app.web_app import (
    _build_config_from_form,
    _build_macos_picker_command,
    _build_windows_picker_command,
    _run_picker_command,
    _validation_to_text,
)


class PickerHelpersTest(unittest.TestCase):
    def test_build_macos_picker_command_uses_osascript(self) -> None:
        command = _build_macos_picker_command("directory", "/Users/test/Downloads", "폴더를 선택하세요.")
        rendered = " ".join(command)
        self.assertEqual(command[0], "/usr/bin/osascript")
        self.assertIn("choose folder", rendered)
        self.assertIn("defaultLocation", rendered)

    def test_build_windows_picker_command_uses_powershell(self) -> None:
        command = _build_windows_picker_command("file", r"C:\Users\test\Downloads\seq.xlsx", "파일을 선택하세요.")
        rendered = "\n".join(command)
        self.assertEqual(command[0], "powershell")
        self.assertIn("OpenFileDialog", rendered)
        self.assertIn("Excel files (*.xlsx)", rendered)

    def test_run_picker_command_returns_selected_path(self) -> None:
        completed = subprocess.CompletedProcess(["dummy"], 0, stdout="/tmp/example\n", stderr="")
        with patch("maund_local_app.web_app.subprocess.run", return_value=completed):
            self.assertEqual(_run_picker_command(["dummy"]), "/tmp/example")

    def test_run_picker_command_returns_empty_when_cancelled(self) -> None:
        cancelled = subprocess.CalledProcessError(1, ["dummy"], output="", stderr="User canceled.")
        with patch("maund_local_app.web_app.subprocess.run", side_effect=cancelled):
            self.assertEqual(_run_picker_command(["dummy"]), "")

    def test_run_picker_command_raises_runtime_error_on_failure(self) -> None:
        failed = subprocess.CalledProcessError(1, ["dummy"], output="", stderr="unexpected failure")
        with patch("maund_local_app.web_app.subprocess.run", side_effect=failed):
            with self.assertRaises(RuntimeError):
                _run_picker_command(["dummy"])

    def test_build_config_from_form_supports_block_heatmap_overrides(self) -> None:
        config = _build_config_from_form(
            {
                "fastq_dir": "/tmp/fastq",
                "seq_xlsx": "/tmp/seq.xlsx",
                "sample_tale_xlsx": "",
                "tale_array_xlsx": "",
                "output_base_dir": "/tmp/out",
                "sample_scope": "49-50",
                "exclude_scope": "",
                "target_seq": "",
                "editor_type": "taled",
                "analysis_mode": "block_heatmap",
                "block_name_1": "N234",
                "desired_products_1": "AAATGAATCTGCTGATGAA,AAATGAATCTGCTAGTGAA",
            }
        )
        self.assertEqual(config.analysis_mode, "block_heatmap")
        self.assertEqual(config.sample_ids, (49, 50))
        self.assertEqual(config.block_overrides[0].block_name, "N234")
        self.assertEqual(
            config.block_overrides[0].desired_products,
            ("AAATGAATCTGCTGATGAA", "AAATGAATCTGCTAGTGAA"),
        )

    def test_validation_to_text_lists_detected_blocks(self) -> None:
        validation = {
            "is_valid": True,
            "errors": (),
            "warnings": ("warn one",),
            "selected_sample_ids": (49, 50),
            "available_fastq_ids": (49, 50),
            "available_sequence_ids": (49, 50),
            "missing_fastq_ids": (),
            "missing_sequence_ids": (),
            "invalid_target_sample_ids": (),
            "target_mismatch_sample_ids": (),
            "detected_blocks": [
                {
                    "block_index": 1,
                    "block_name": "N234",
                    "sample_spec": "49~67",
                    "target_window": "AAATGAATCTGCTAATGAA",
                    "desired_products": ["AAATGAATCTGCTGATGAA"],
                    "row_items": [("R1L2", 49), ("Col0(WT)", 67)],
                }
            ],
        }
        text = _validation_to_text(validation)
        self.assertIn("유효 여부: 정상", text)
        self.assertIn("[경고]", text)
        self.assertIn("[감지된 블록]", text)
        self.assertIn("N234", text)


if __name__ == "__main__":
    unittest.main()
