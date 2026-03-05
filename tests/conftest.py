def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (require DIGITALOCEAN_TOKEN)",
    )
    # Register dashboard reporter on controller only (not xdist workers)
    import os
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        try:
            from tests.dash_plugin import DashboardReporter
            config.pluginmanager.register(DashboardReporter(), "dashboard_reporter")
        except Exception:
            pass
