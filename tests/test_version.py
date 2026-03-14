from __future__ import annotations

import unittest

from maund_local_app.version import get_version


class VersionTest(unittest.TestCase):
    def test_version_looks_like_semver(self) -> None:
        version = get_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
