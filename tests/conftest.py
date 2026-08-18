"""Shared pytest hooks.

Guards against the failure mode where every T.261 test is silently
`pytest.skipif`-ped because BWC binaries aren't present in the test
environment. When ``COMPBENCH_REQUIRE_T261=1`` is set (typically on the
CI job that intentionally builds BWC), we assert at end-of-session that
at least one test with `t261` in its nodeid actually ran.
"""

from __future__ import annotations

import os
from typing import Any


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: Any) -> None:
    if not os.environ.get("COMPBENCH_REQUIRE_T261"):
        return
    stats = terminalreporter.stats
    passed = stats.get("passed", [])
    ran = [r for r in passed if "t261" in str(r.nodeid).lower()]
    if not ran:
        terminalreporter.write_sep("=", "COMPBENCH_REQUIRE_T261 FAILURE")
        terminalreporter.write_line(
            "COMPBENCH_REQUIRE_T261=1 but no `t261`-marked tests passed. "
            "T.261 tests are being silently skipped — BWC binaries missing?",
            red=True,
        )
        # Make the run non-zero even if pytest's own report thought it passed.
        raise SystemExit(2)
