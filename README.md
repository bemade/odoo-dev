# odoo-dev

A CLI tool for managing Odoo development environments. Handles local Python setup, Docker containers, database operations, and more.

## Installation

```bash
# Install with uv (recommended)
uv tool install odoo-dev

# Or with pip
pip install odoo-dev
```

## Quick Start

```bash
# In your Odoo project directory
cd my-odoo-project

# Full setup: clone Odoo repos, create venv, configure VSCode
odoo-dev setup

# Or for community edition only
odoo-dev setup --community
```

## Commands

### Local Development (default)

```bash
odoo-dev run                      # Start Odoo locally
odoo-dev run -d mydb --dev reload # With hot reload
odoo-dev run --debug              # With debugpy (VSCode attach)
odoo-dev shell mydb               # Open Odoo shell
odoo-dev update base -d mydb      # Update modules
odoo-dev test my_module           # Run tests with coverage
odoo-dev scaffold my_module       # Create new module
```

### Database Operations

```bash
odoo-dev db list                  # List databases
odoo-dev db restore backup.zip    # Restore from backup
odoo-dev db restore backup.zip mydb --no-neutralize
odoo-dev db drop mydb             # Drop database
odoo-dev db neutralize mydb       # Disable emails/crons
```

### Docker (optional)

```bash
odoo-dev docker start             # Start containers
odoo-dev docker stop              # Stop containers
odoo-dev docker logs              # View logs
odoo-dev docker build             # Rebuild image
odoo-dev docker shell mydb        # Shell in container
odoo-dev docker psql              # PostgreSQL shell
```

### Setup Commands

```bash
odoo-dev setup                    # Full setup
odoo-dev setup --community        # Community edition only
odoo-dev setup-venv               # Just create venv
odoo-dev vscode                   # Configure VSCode debugging
```

## Project Structure

odoo-dev expects this project structure:

```
my-odoo-project/
├── .env                 # Optional: ODOO_VERSION, PYTHON_VERSION
├── addons/              # Your custom addons
├── requirements.txt     # Project-specific Python deps
├── odoo/                # Cloned by setup
├── enterprise/          # Cloned by setup (unless --community)
├── design-themes/       # Cloned by setup
├── .venv/               # Created by setup
└── conf/
    └── odoo.conf        # Created by setup
```

## Configuration

Create a `.env` file in your project root:

```bash
ODOO_VERSION=18.0
PYTHON_VERSION=3.12
```

## Requirements

- Python 3.12+
- uv (recommended) or pip
- Git
- PostgreSQL (for local development)
- Docker (optional, for containerized development)

## Development

```bash
# Clone and install for development
git clone git@git.bemade.org:bemade/odoo-dev.git
cd odoo-dev
uv sync

# Run tests
uv run pytest                 # All tests
uv run pytest -m "not slow"   # Fast tests only

# Build
uv build
```

## License

LGPL-3. For complete license terms, visit https://www.gnu.org/licenses/lgpl-3.0.en.html
