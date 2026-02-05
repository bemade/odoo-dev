"""Smoke tests for CLI commands."""

from typer.testing import CliRunner

from odoo_dev import __version__
from odoo_dev.cli import app

runner = CliRunner()


class TestVersion:
    """Test version flag."""

    def test_version_long(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_short(self):
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert "odoo-dev" in result.output


class TestCliHelp:
    """Verify all commands respond to --help without crashing."""

    def test_main_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Odoo Development Environment Helper" in result.output

    def test_run_help(self):
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "Run Odoo locally" in result.output

    def test_shell_help(self):
        result = runner.invoke(app, ["shell", "--help"])
        assert result.exit_code == 0

    def test_test_help(self):
        result = runner.invoke(app, ["test", "--help"])
        assert result.exit_code == 0

    def test_update_help(self):
        result = runner.invoke(app, ["update", "--help"])
        assert result.exit_code == 0

    def test_scaffold_help(self):
        result = runner.invoke(app, ["scaffold", "--help"])
        assert result.exit_code == 0

    def test_setup_help(self):
        result = runner.invoke(app, ["setup", "--help"])
        assert result.exit_code == 0

    def test_setup_venv_help(self):
        result = runner.invoke(app, ["setup-venv", "--help"])
        assert result.exit_code == 0

    def test_db_help(self):
        result = runner.invoke(app, ["db", "--help"])
        assert result.exit_code == 0
        assert "restore" in result.output
        assert "drop" in result.output

    def test_db_restore_help(self):
        result = runner.invoke(app, ["db", "restore", "--help"])
        assert result.exit_code == 0

    def test_docker_help(self):
        result = runner.invoke(app, ["docker", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "stop" in result.output

    def test_docker_start_help(self):
        result = runner.invoke(app, ["docker", "start", "--help"])
        assert result.exit_code == 0
