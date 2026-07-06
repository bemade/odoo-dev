"""Tests for setup command utilities."""

from pathlib import Path
from unittest.mock import patch

from odoo_dev.commands.setup import (
    _clean,
    _setup_docker_files,
    _update_env_file,
    vscode,
)
from odoo_dev.config import ProjectConfig


class TestUpdateEnvFile:
    """Test .env file updating."""

    def test_creates_new_env_file(self, tmp_path: Path):
        env_file = tmp_path / ".env"

        _update_env_file(env_file, {"ODOO_VERSION": "18.0", "PYTHON_VERSION": "3.12"})

        assert env_file.exists()
        content = env_file.read_text()
        assert "ODOO_VERSION=18.0" in content
        assert "PYTHON_VERSION=3.12" in content

    def test_updates_existing_env_file(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_VAR=hello\nODOO_VERSION=17.0\n")

        _update_env_file(env_file, {"ODOO_VERSION": "18.0"})

        content = env_file.read_text()
        assert "ODOO_VERSION=18.0" in content
        assert "EXISTING_VAR=hello" in content
        # Old version should be replaced
        assert "17.0" not in content

    def test_preserves_other_vars(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("DB_HOST=localhost\nDB_PORT=5432\n")

        _update_env_file(env_file, {"ODOO_VERSION": "18.0"})

        content = env_file.read_text()
        assert "DB_HOST=localhost" in content
        assert "DB_PORT=5432" in content
        assert "ODOO_VERSION=18.0" in content

    def test_skips_comments(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nVAR=value\n")

        _update_env_file(env_file, {"NEW_VAR": "new"})

        content = env_file.read_text()
        assert "NEW_VAR=new" in content
        assert "VAR=value" in content
        # Comments are not preserved (simplification)


class TestClean:
    """Test _clean function."""

    def test_clean_removes_directories(self, tmp_path: Path):
        """Verify _clean removes expected directories."""
        # Create directories that _clean should remove
        for name in ["odoo", "enterprise", "design-themes", "industry", ".venv"]:
            (tmp_path / name).mkdir()

        # Mock load_config to return our tmp_path as project_dir
        mock_cfg = type("Config", (), {"project_dir": tmp_path})()
        with patch("odoo_dev.commands.setup.load_config", return_value=mock_cfg):
            _clean()

        # Verify all directories were removed
        for name in ["odoo", "enterprise", "design-themes", "industry", ".venv"]:
            assert not (tmp_path / name).exists(), f"{name} should be removed"

    def test_clean_ignores_missing_directories(self, tmp_path: Path):
        """Verify _clean doesn't fail if directories don't exist."""
        # Only create some directories
        (tmp_path / "odoo").mkdir()

        mock_cfg = type("Config", (), {"project_dir": tmp_path})()
        with patch("odoo_dev.commands.setup.load_config", return_value=mock_cfg):
            _clean()  # Should not raise

        assert not (tmp_path / "odoo").exists()


def _make_cfg(tmp_path: Path) -> ProjectConfig:
    """Create a ProjectConfig pointing at tmp_path."""
    return ProjectConfig(
        project_dir=tmp_path,
        script_dir=tmp_path / ".odoo-deploy",
        odoo_version="19.0",
        python_version="3.12",
        project_name="test-project",
    )


class TestSetupDockerFiles:
    """Test _setup_docker_files copies templates correctly."""

    def test_creates_odoo_deploy_directory(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        _setup_docker_files(cfg)
        assert cfg.script_dir.exists()
        assert cfg.script_dir.is_dir()

    def test_copies_dockerfile(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        _setup_docker_files(cfg)
        dockerfile = cfg.script_dir / "Dockerfile"
        assert dockerfile.exists()
        content = dockerfile.read_text()
        assert "FROM python:" in content
        assert "ENTRYPOINT" in content

    def test_copies_entrypoint(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        _setup_docker_files(cfg)
        entrypoint = cfg.script_dir / "docker-entrypoint.sh"
        assert entrypoint.exists()
        content = entrypoint.read_text()
        assert "#!/bin/bash" in content
        # Should be executable
        assert entrypoint.stat().st_mode & 0o755

    def test_creates_docker_odoo_conf(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        _setup_docker_files(cfg)
        conf = cfg.docker_config_file
        assert conf.exists()
        content = conf.read_text()
        assert "/opt/project/" in content
        assert "db_host = db" in content

    def test_docker_conf_includes_enterprise_by_default(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        _setup_docker_files(cfg)
        content = cfg.docker_config_file.read_text()
        assert "/opt/project/enterprise" in content

    def test_docker_conf_excludes_enterprise_for_community(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        _setup_docker_files(cfg, community_only=True)
        content = cfg.docker_config_file.read_text()
        assert "/opt/project/enterprise" not in content

    def test_does_not_overwrite_existing_docker_conf(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        cfg.script_dir.mkdir(parents=True)
        cfg.docker_config_file.write_text("existing config")
        _setup_docker_files(cfg)
        assert cfg.docker_config_file.read_text() == "existing config"

    def test_docker_conf_omits_vendored_when_absent(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        _setup_docker_files(cfg)
        # No vendored/ dir -> path must not be added (else Odoo warns on boot).
        assert "/opt/project/vendored" not in cfg.docker_config_file.read_text()

    def test_docker_conf_includes_vendored_when_present(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        (tmp_path / "vendored").mkdir()
        _setup_docker_files(cfg)
        assert "/opt/project/vendored" in cfg.docker_config_file.read_text()


class TestLocalOdooConf:
    """Test the local odoo.conf addons_path includes vendored/ only when present."""

    def test_local_conf_omits_vendored_when_absent(self, tmp_path: Path):
        from odoo_dev.commands.setup import _setup_odoo_config

        cfg = _make_cfg(tmp_path)
        (tmp_path / "conf").mkdir()
        _setup_odoo_config(cfg)
        assert "vendored" not in cfg.config_file.read_text()

    def test_local_conf_includes_vendored_when_present(self, tmp_path: Path):
        from odoo_dev.commands.setup import _setup_odoo_config

        cfg = _make_cfg(tmp_path)
        (tmp_path / "conf").mkdir()
        (tmp_path / "vendored").mkdir()
        _setup_odoo_config(cfg)
        assert str(tmp_path / "vendored") in cfg.config_file.read_text()


class TestAgenticSetup:
    """Non-interactive, no-docker setup path for headless/agentic use."""

    def test_prompt_for_versions_non_interactive_uses_defaults(
        self, tmp_path: Path, monkeypatch
    ):
        import os

        from odoo_dev.commands.setup import _prompt_for_versions
        from odoo_dev.config import DEFAULT_ODOO_VERSION

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ODOO_VERSION", raising=False)
        monkeypatch.delenv("PYTHON_VERSION", raising=False)
        with (
            patch("odoo_dev.commands.setup.typer.prompt") as prompt,
            patch("odoo_dev.commands.setup.typer.confirm") as confirm,
        ):
            _prompt_for_versions(non_interactive=True)
        # No interactive calls, defaults applied, recorded to .env silently.
        prompt.assert_not_called()
        confirm.assert_not_called()
        assert os.environ["ODOO_VERSION"] == DEFAULT_ODOO_VERSION
        assert "ODOO_VERSION" in (tmp_path / ".env").read_text()

    def test_setup_no_docker_yes_skips_docker_and_prompts(self, tmp_path: Path):
        from odoo_dev.commands import setup as setup_mod

        cfg = _make_cfg(tmp_path)
        with (
            patch.object(setup_mod, "_prompt_for_versions") as prompt_versions,
            patch.object(setup_mod, "load_config", return_value=cfg),
            patch.object(setup_mod, "_init_submodules"),
            patch.object(setup_mod, "_clone_odoo_repos") as clone,
            patch.object(setup_mod, "vscode"),
            patch.object(setup_mod, "setup_venv") as venv,
            patch.object(setup_mod, "_setup_docker_files") as docker_files,
            patch("odoo_dev.commands.docker.build") as docker_build,
            patch.object(setup_mod.typer, "confirm") as confirm,
        ):
            setup_mod.setup(no_docker=True, yes=True)

        prompt_versions.assert_called_once_with(non_interactive=True)
        clone.assert_called_once()  # core still cloned (headless full setup)
        venv.assert_called_once()
        confirm.assert_not_called()  # no prompts
        docker_files.assert_not_called()  # no docker
        docker_build.assert_not_called()


class TestInitSubmodules:
    """Test _init_submodules is called correctly from setup_venv."""

    def test_setup_venv_calls_init_submodules(self, tmp_path: Path):
        """setup_venv should initialize submodules before setting up the venv."""
        from unittest.mock import call, patch

        cfg = _make_cfg(tmp_path)
        # Create .gitmodules to trigger the submodule check
        (tmp_path / ".gitmodules").write_text("[submodule]\n")

        with (
            patch("odoo_dev.commands.setup.load_config", return_value=cfg),
            patch("odoo_dev.commands.setup._init_submodules") as mock_init,
            patch("odoo_dev.commands.setup._setup_odoo_config"),
            patch("odoo_dev.commands.setup._install_system_dependencies"),
            patch("odoo_dev.commands.setup._update_python_path"),
            patch("subprocess.run", return_value=type("R", (), {"returncode": 0})()),
        ):
            from odoo_dev.commands.setup import setup_venv

            setup_venv()

        mock_init.assert_called_once_with(cfg)

    def test_init_submodules_skips_if_no_gitmodules(self, tmp_path: Path):
        """_init_submodules should do nothing if .gitmodules does not exist."""
        from odoo_dev.commands.setup import _init_submodules

        cfg = _make_cfg(tmp_path)
        with patch("subprocess.run") as mock_run:
            _init_submodules(cfg)
        mock_run.assert_not_called()

    def test_init_submodules_runs_git_command(self, tmp_path: Path):
        """_init_submodules should run git submodule update when .gitmodules exists."""
        from odoo_dev.commands.setup import _init_submodules

        cfg = _make_cfg(tmp_path)
        (tmp_path / ".gitmodules").write_text("[submodule]\n")

        with patch(
            "subprocess.run",
            return_value=type("R", (), {"returncode": 0, "stderr": ""})(),
        ) as mock_run:
            _init_submodules(cfg)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "git" in args
        assert "submodule" in args
        assert "update" in args
        assert "--init" in args
        assert "--recursive" in args


class TestVscodeSetup:
    """Test vscode() copies templates correctly."""

    def test_creates_vscode_directory(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        vscode(cfg)
        assert (tmp_path / ".vscode").exists()

    def test_copies_launch_json(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        vscode(cfg)
        launch = tmp_path / ".vscode" / "launch.json"
        assert launch.exists()
        content = launch.read_text()
        assert "configurations" in content

    def test_copies_tasks_json(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        vscode(cfg)
        tasks = tmp_path / ".vscode" / "tasks.json"
        assert tasks.exists()
        content = tasks.read_text()
        assert "tasks" in content

    def test_copies_settings_json(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        vscode(cfg)
        settings = tmp_path / ".vscode" / "settings.json"
        assert settings.exists()

    def test_does_not_overwrite_existing_settings(self, tmp_path: Path):
        cfg = _make_cfg(tmp_path)
        vscode_dir = tmp_path / ".vscode"
        vscode_dir.mkdir()
        (vscode_dir / "settings.json").write_text("custom settings")
        vscode(cfg)
        assert (vscode_dir / "settings.json").read_text() == "custom settings"
