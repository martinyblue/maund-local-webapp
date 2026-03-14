from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from maund_local_app.web_app import (
    _build_macos_picker_command,
    _build_windows_picker_command,
    _run_picker_command,
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


if __name__ == "__main__":
    unittest.main()
