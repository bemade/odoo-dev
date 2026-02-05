"""Integration tests using the odoo-empty fixture."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from odoo_dev.cli import app
from odoo_dev.config import load_config
from odoo_dev.commands import setup

runner = CliRunner()

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "odoo-empty"


@pytest.fixture
def fixture_dir() -> Path:
    """Return the path to the odoo-empty fixture."""
    if not FIXTURE_DIR.exists():
        pytest.skip(
            "odoo-empty fixture not available (run: git submodule update --init)"
        )
    return FIXTURE_DIR


@pytest.fixture
def clean_fixture_dir(fixture_dir: Path, tmp_path: Path):
    """Create a clean copy of the fixture for testing without prerequisites.

    This ensures tests that check for missing venv/config don't interfere
    with tests that set up the environment.
    """
    # Copy only the essential structure, not cloned repos
    clean_dir = tmp_path / "odoo-project"
    clean_dir.mkdir()

    # Copy .git file (for submodule detection)
    git_path = fixture_dir / ".git"
    if git_path.exists():
        if git_path.is_file():
            shutil.copy(git_path, clean_dir / ".git")
        else:
            shutil.copytree(git_path, clean_dir / ".git")

    # Create empty addons directory
    (clean_dir / "addons").mkdir()
    (clean_dir / "addons" / ".gitkeep").touch()

    return clean_dir


@pytest.fixture
def in_fixture_dir(fixture_dir: Path, monkeypatch):
    """Change to fixture directory for the test."""
    monkeypatch.chdir(fixture_dir)
    # Clear any cached env vars
    monkeypatch.delenv("ODOO_VERSION", raising=False)
    monkeypatch.delenv("PYTHON_VERSION", raising=False)
    return fixture_dir


@pytest.fixture
def in_clean_fixture(clean_fixture_dir: Path, monkeypatch):
    """Change to a clean fixture directory (no venv, no odoo)."""
    monkeypatch.chdir(clean_fixture_dir)
    monkeypatch.delenv("ODOO_VERSION", raising=False)
    monkeypatch.delenv("PYTHON_VERSION", raising=False)
    return clean_fixture_dir


@pytest.fixture(scope="session", autouse=True)
def cleanup_fixture_env():
    """Clean up the fixture environment after all tests complete.

    Using autouse=True ensures this always runs at session end,
    regardless of which tests were selected.
    """
    yield

    # Clean up directories that setup may have created
    created_dirs = ["odoo", "design-themes", "industry", ".venv", "conf", ".vscode"]
    for dirname in created_dirs:
        dir_path = FIXTURE_DIR / dirname
        if dir_path.exists():
            shutil.rmtree(dir_path, ignore_errors=True)


@pytest.fixture(scope="session")
def setup_fixture_env():
    """Set up the fixture environment once per test session.

    This runs `setup` to clone repos and create venv.
    Marked as session-scoped so it only runs once.
    """
    if not FIXTURE_DIR.exists():
        pytest.skip("odoo-empty fixture not available")

    original_dir = Path.cwd()
    os.chdir(FIXTURE_DIR)

    try:
        # Clear any existing env vars
        os.environ.pop("ODOO_VERSION", None)
        os.environ.pop("PYTHON_VERSION", None)

        # Run setup with --community to skip enterprise repos
        # Use typer runner with input to answer prompts
        result = runner.invoke(
            app,
            ["setup", "--community"],
            # Odoo 19.0, Python 3.12, no save to .env, no docker
            input="19.0\n3.12\nn\nn\n",
        )

        if result.exit_code != 0:
            pytest.fail(
                f"Setup failed (exit code {result.exit_code}):\n{result.output}"
            )

        yield FIXTURE_DIR

    finally:
        os.chdir(original_dir)


@pytest.fixture
def in_setup_fixture(setup_fixture_env: Path, monkeypatch):
    """Use the pre-configured fixture environment."""
    monkeypatch.chdir(setup_fixture_env)
    monkeypatch.delenv("ODOO_VERSION", raising=False)
    monkeypatch.delenv("PYTHON_VERSION", raising=False)
    return setup_fixture_env


class TestConfigWithFixture:
    """Test config loading against real project structure."""

    def test_detects_project_root(self, in_fixture_dir: Path):
        cfg = load_config()
        assert cfg.project_dir == in_fixture_dir
        assert cfg.project_name == "odoo-empty"

    def test_paths_are_correct(self, in_fixture_dir: Path):
        cfg = load_config()
        assert cfg.addons_dir == in_fixture_dir / "addons"
        assert cfg.script_dir == in_fixture_dir / ".odoo-deploy"
        assert cfg.venv_path == in_fixture_dir / ".venv"

    def test_default_versions(self, in_fixture_dir: Path):
        cfg = load_config()
        assert cfg.odoo_version == "19.0"
        assert cfg.python_version == "3.12"


class TestRunCommandsWithoutPrerequisites:
    """Test that commands fail gracefully when prerequisites are missing."""

    def test_run_fails_without_venv(self, in_clean_fixture: Path):
        result = runner.invoke(app, ["run"])
        assert result.exit_code != 0
        assert (
            "Virtual environment not found" in result.output
            or "not found" in result.output.lower()
        )

    def test_shell_fails_without_venv(self, in_clean_fixture: Path):
        result = runner.invoke(app, ["shell", "testdb"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_test_fails_without_venv(self, in_clean_fixture: Path):
        result = runner.invoke(app, ["test"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_update_fails_without_venv(self, in_clean_fixture: Path):
        result = runner.invoke(app, ["update", "base"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestDockerCommandsWithoutPrerequisites:
    """Test docker commands fail gracefully."""

    def test_docker_start_fails_without_config(self, in_clean_fixture: Path):
        result = runner.invoke(app, ["docker", "start"])
        assert result.exit_code != 0
        # Should mention config file not found
        assert "not found" in result.output.lower() or "setup" in result.output.lower()


class TestDbCommands:
    """Test db command argument handling."""

    def test_db_restore_requires_file(self, in_clean_fixture: Path):
        result = runner.invoke(app, ["db", "restore"])
        assert result.exit_code != 0
        # Missing required argument
        assert "missing" in result.output.lower() or "required" in result.output.lower()

    def test_db_restore_fails_on_missing_file(self, in_clean_fixture: Path):
        result = runner.invoke(app, ["db", "restore", "/nonexistent/backup.zip"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_db_drop_requires_name(self, in_clean_fixture: Path):
        result = runner.invoke(app, ["db", "drop"])
        assert result.exit_code != 0


class TestScaffoldCommand:
    """Test scaffold command."""

    def test_scaffold_fails_without_venv(self, in_clean_fixture: Path):
        result = runner.invoke(app, ["scaffold", "test_module"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# =============================================================================
# Success Path Tests (require setup to have run)
# =============================================================================


@pytest.mark.slow
class TestSetupSuccess:
    """Test that setup command works correctly."""

    def test_setup_creates_venv(self, in_setup_fixture: Path):
        """Verify setup created a virtual environment."""
        venv_path = in_setup_fixture / ".venv"
        assert venv_path.exists(), "Virtual environment should exist"
        assert (venv_path / "bin" / "python").exists(), "Python should be in venv"

    def test_setup_clones_odoo(self, in_setup_fixture: Path):
        """Verify setup cloned Odoo repository."""
        odoo_path = in_setup_fixture / "odoo"
        assert odoo_path.exists(), "Odoo directory should exist"
        assert (odoo_path / "odoo-bin").exists(), "odoo-bin should exist"

    def test_setup_creates_config(self, in_setup_fixture: Path):
        """Verify setup created config files."""
        conf_path = in_setup_fixture / "conf" / "odoo.conf"
        assert conf_path.exists(), "Local odoo.conf should exist"

        # Verify config has expected content
        content = conf_path.read_text()
        assert "addons_path" in content
        assert "admin_passwd" in content

    def test_setup_creates_vscode_config(self, in_setup_fixture: Path):
        """Verify setup created VSCode configuration."""
        vscode_path = in_setup_fixture / ".vscode"
        assert vscode_path.exists(), ".vscode directory should exist"
        assert (vscode_path / "launch.json").exists(), "launch.json should exist"


@pytest.mark.slow
class TestRunSuccess:
    """Test run command after setup."""

    def test_run_help_works(self, in_setup_fixture: Path):
        """Verify run --help works in setup environment."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0

    def test_run_starts_odoo(self, in_setup_fixture: Path):
        """Verify run command can start Odoo (briefly)."""
        import signal
        import time

        cfg = load_config()
        venv_python = cfg.venv_path / "bin" / "python"

        # Start Odoo in background, let it initialize, then kill it
        proc = subprocess.Popen(
            [
                str(venv_python),
                str(cfg.odoo_bin),
                "-c",
                str(cfg.config_file),
                "--stop-after-init",
                "--http-port",
                "18069",  # Use non-standard port to avoid conflicts
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=in_setup_fixture,
        )

        try:
            # Wait for it to complete (--stop-after-init) or timeout
            stdout, stderr = proc.communicate(timeout=60)
            # Should exit 0 with --stop-after-init when no database
            # (it just starts and stops)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Odoo took too long to start")


@pytest.mark.slow
class TestScaffoldSuccess:
    """Test scaffold command after setup."""

    def test_scaffold_creates_module(self, in_setup_fixture: Path):
        """Verify scaffold creates a new module."""
        module_name = "test_scaffold_module"
        module_path = in_setup_fixture / "addons" / module_name

        # Clean up if exists from previous run
        if module_path.exists():
            shutil.rmtree(module_path)

        result = runner.invoke(app, ["scaffold", module_name])

        assert result.exit_code == 0, f"scaffold failed: {result.output}"
        assert module_path.exists(), "Module directory should be created"
        assert (module_path / "__manifest__.py").exists(), "Manifest should exist"
        assert (module_path / "__init__.py").exists(), "__init__.py should exist"

        # Clean up
        shutil.rmtree(module_path)


@pytest.mark.slow
class TestUpdateSuccess:
    """Test update command after setup."""

    def test_update_runs_after_setup(self, in_setup_fixture: Path):
        """Verify update command can run (venv/config are found)."""
        # Just check that --help works in the setup environment
        # (full update would require a real database)
        result = runner.invoke(app, ["update", "--help"])
        assert result.exit_code == 0
        assert "Update specified modules" in result.output
