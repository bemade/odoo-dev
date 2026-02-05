"""Tests for run command utilities."""

from odoo_dev.commands.run import _find_available_port, _get_addons_path
from pathlib import Path


class TestFindAvailablePort:
    def test_returns_port_in_range(self):
        port = _find_available_port(8069)
        assert 8069 <= port < 8169 or 49152 <= port <= 65535

    def test_finds_different_port_if_busy(self):
        import socket

        # Bind to 8069
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 8069))
            s.listen(1)

            port = _find_available_port(8069)
            assert port != 8069


class TestGetAddonsPath:
    def test_extracts_addons_path(self, tmp_path: Path):
        config_file = tmp_path / "odoo.conf"
        config_file.write_text(
            """[options]
addons_path = /opt/odoo/addons,/opt/odoo/enterprise
admin_passwd = admin
"""
        )

        result = _get_addons_path(config_file)
        assert result == "/opt/odoo/addons,/opt/odoo/enterprise"

    def test_returns_empty_if_not_found(self, tmp_path: Path):
        config_file = tmp_path / "odoo.conf"
        config_file.write_text("[options]\nadmin_passwd = admin\n")

        result = _get_addons_path(config_file)
        assert result == ""
