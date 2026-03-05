"""Pytest plugin that reports test progress to dreamloop-dash in real-time.

Maps test classes to dashboard steps:
  TestConnectivity    → diagnose
  TestDeployment      → fix
  TestSysadminAi      → attack
  TestSecurityHardening → validate

Each individual test result streams as a tool_call event.
Only activates on the controller process (not xdist workers).
"""

import json
import os
import time
import urllib.request
from collections import defaultdict

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8500")

CLASS_TO_STEP = {
    "TestConnectivity": "diagnose",
    "TestDeployment": "fix",
    "TestSysadminAi": "attack",
    "TestSecurityHardening": "validate",
}

OS_TARGETS = [
    "ubuntu-24.04", "ubuntu-22.04", "debian-12",
    "centos-stream-9", "fedora-42", "almalinux-9",
]


def _post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{DASHBOARD_URL}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


class DashboardReporter:
    def __init__(self):
        self.class_totals = defaultdict(int)
        self.class_counts = defaultdict(
            lambda: {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
        )
        self.class_started = set()
        self.class_done = set()
        self.class_start_times = {}
        self.session_start = None
        self.total_passed = 0
        self.total_failed = 0
        self.total_skipped = 0
        self.total_count = 0
        self.enabled = True

    def pytest_collection_modifyitems(self, items):
        for item in items:
            cls = item.cls.__name__ if item.cls else "Unknown"
            self.class_totals[cls] += 1

    def pytest_sessionstart(self, session):
        try:
            req = urllib.request.Request(f"{DASHBOARD_URL}/api/state")
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            self.enabled = False
            return

        self.session_start = time.time()
        servers = {name: {"status": "pending"} for name in OS_TARGETS}
        _post("/api/pipeline/start", {
            "max_iterations": 1,
            "servers": servers,
            "mode": "testing",
            "step_labels": {
                "diagnose": "Connectivity",
                "fix": "Deployment",
                "attack": "SysadminAi",
                "validate": "Security",
            },
        })
        _post("/api/iteration/start", {"number": 1})

    def pytest_runtest_logreport(self, report):
        if not self.enabled:
            return
        # Handle setup errors (fixture failures) and call results
        if report.when == "setup" and not report.failed:
            return
        if report.when == "teardown":
            return

        parts = report.nodeid.split("::")
        cls_name = parts[1] if len(parts) > 1 else "Unknown"
        test_name = parts[2] if len(parts) > 2 else report.nodeid

        os_name = ""
        if "[" in test_name:
            bracket = test_name[test_name.index("[") + 1 : test_name.rindex("]")]
            for target in OS_TARGETS:
                if bracket.startswith(target):
                    os_name = target
                    break

        step = CLASS_TO_STEP.get(cls_name, "diagnose")

        if cls_name not in self.class_started:
            self.class_started.add(cls_name)
            self.class_start_times[cls_name] = time.time()
            _post("/api/step/start", {"step": step})

        if report.passed:
            status = "executed"
            self.total_passed += 1
            self.class_counts[cls_name]["passed"] += 1
        elif report.skipped:
            status = "denied"
            self.total_skipped += 1
            self.class_counts[cls_name]["skipped"] += 1
        else:
            status = "blocked"
            self.total_failed += 1
            self.class_counts[cls_name]["failed"] += 1

        self.total_count += 1
        self.class_counts[cls_name]["total"] += 1

        output = ""
        if hasattr(report, "longreprtext") and report.longreprtext:
            output = report.longreprtext[:200]

        _post("/api/tool_call", {
            "iteration": 1,
            "step": step,
            "finding": test_name.split("[")[0] if "[" in test_name else test_name,
            "tool": os_name or cls_name,
            "args": test_name,
            "status": status,
            "output_preview": output,
            "round": self.class_counts[cls_name]["total"],
            "total_rounds": self.class_totals.get(cls_name, 0),
            "test_stats": {
                "passed": self.total_passed,
                "failed": self.total_failed,
                "skipped": self.total_skipped,
                "total": self.total_count,
            },
        })

        if (
            self.class_counts[cls_name]["total"]
            >= self.class_totals.get(cls_name, 0)
            and cls_name not in self.class_done
        ):
            self.class_done.add(cls_name)
            counts = self.class_counts[cls_name]
            start = self.class_start_times.get(cls_name, self.session_start)
            elapsed = time.time() - start if start else 0
            _post("/api/step/complete", {
                "step": step,
                "result": {
                    "success": counts["failed"] == 0,
                    "summary": (
                        f"{counts['passed']} passed, "
                        f"{counts['failed']} failed, "
                        f"{counts['skipped']} skipped"
                    ),
                    "findings": [],
                },
                "elapsed_seconds": round(elapsed, 1),
            })

    def pytest_sessionfinish(self, session, exitstatus):
        if not self.enabled:
            return
        elapsed = time.time() - self.session_start if self.session_start else 0
        status = "converged" if self.total_failed == 0 else "max_reached"
        _post("/api/pipeline/finish", {
            "status": status,
            "summary": {
                "total": self.total_count,
                "passed": self.total_passed,
                "failed": self.total_failed,
                "skipped": self.total_skipped,
                "elapsed_seconds": round(elapsed, 1),
            },
        })
