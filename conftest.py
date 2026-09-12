"""Root conftest. Registers the custom report plugin so its CLI options
(--incl_tests, --excl_tests, --html-report, --no-html-report) and the
step_log fixture are available no matter how pytest is invoked."""

pytest_plugins = ["plugins.report_plugin"]
