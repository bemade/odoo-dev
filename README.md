# odoo-dev

A CLI tool for managing Odoo development environments. Handles local Python setup, Docker containers, database operations, and more.

It is the successor to the older `odoo-deploy` shell scripts — if you have notes for `odoo-deploy`, the rough mapping is: `odoo-dev docker start/stop/build` replaces the old `odoo-dev.sh start/stop/build`, and `odoo-dev run`/`test`/`shell` give you a local (venv-based) workflow that `odoo-deploy` didn't.

## Installation

```bash
# Install with uv (recommended) — installs the published package from PyPI
uv tool install odoo-dev

# Or with pip
pip install odoo-dev
```

Then make sure the install location is on your `PATH` (uv prints the path; usually `~/.local/bin`):

```bash
uv tool update-shell   # or: export PATH="$HOME/.local/bin:$PATH"
```

## Quick Start

```bash
# In your Odoo project directory
cd my-odoo-project

# Full setup: clone Odoo repos, create venv, install deps, configure VSCode
odoo-dev setup

# Or for community edition only
odoo-dev setup --community
```

`setup` reads `ODOO_VERSION` / `PYTHON_VERSION` from a `.env` in the project root (or
prompts for them and offers to save). It then clones the Odoo repos, builds a `.venv`,
installs system dependencies, and generates `conf/odoo.conf`. It will offer to set up
Docker at the end — answer "no" if you only want the local venv workflow.

## Database setup (read this before your first `run`/`test`)

The generated `conf/odoo.conf` connects as PostgreSQL user **`odoo`** over the local
socket. **A running PostgreSQL server is a prerequisite you provide yourself** — on
every platform. `setup` installs only the PostgreSQL *client* and build dependencies
(macOS: `libpq`; Linux: `postgresql-client` + `libpq-dev`); it never installs, starts,
or configures a server, and never creates the `odoo` role. So on a fresh machine,
install a server, start it, and create the role once:

**macOS (Homebrew):**

```bash
brew install postgresql@18                  # install a server (pick your version)
brew services start postgresql@18           # start it
createuser -s odoo                          # create the role odoo.conf expects
# Homebrew's versioned postgres is keg-only; add its bin to PATH if psql/createuser aren't found:
#   export PATH="$(brew --prefix postgresql@18)/bin:$PATH"
```

**Debian/Ubuntu:**

```bash
sudo apt-get install postgresql     # install a server if you don't already have one
sudo systemctl start postgresql
sudo -u postgres createuser -s odoo
```

**Using a different / remote / Docker PostgreSQL:** set `DB_HOST`, `DB_PORT`,
`DB_USER`, `DB_PASSWORD` in `.env` before running `setup` (it writes them into
`conf/odoo.conf`), or edit `conf/odoo.conf` directly. With no `DB_HOST`, odoo-dev
connects over the local socket as the `odoo` role.

Before launching, `run`/`test`/`shell`/`update` run a quick connection preflight: if
the server is unreachable, the role is missing, or authentication fails, you get a
specific one-line fix instead of a stack trace.

## Commands

### Local Development (default)

```bash
odoo-dev run                          # Start Odoo locally (default port 8069)
odoo-dev run -d mydb -p 8070          # Pick a database and HTTP port
odoo-dev run -d mydb -i base          # Initialize module(s) on start
odoo-dev run -d mydb --dev reload     # With hot reload
odoo-dev run --debug                  # With debugpy (VSCode attach on 5678)
odoo-dev shell mydb                   # Open an Odoo shell
odoo-dev update base -d mydb          # Update modules
odoo-dev test my_module               # Run a module's tests (coverage on by default)
odoo-dev test my_module --test-tags my_module --no-coverage
odoo-dev test                         # Auto-discover & test all addons in addons/
odoo-dev scaffold my_module           # Create a new module
```

> Note: the HTTP port flag is `-p` / `--port` (not `--http-port`).

### Database Operations

```bash
odoo-dev db list                      # List databases
odoo-dev db restore backup.zip        # Restore from backup (neutralized by default)
odoo-dev db restore backup.zip mydb --no-neutralize
odoo-dev db drop mydb                  # Drop database
odoo-dev db neutralize mydb            # Disable emails/crons
```

### Docker (optional)

```bash
odoo-dev docker start                 # Start containers
odoo-dev docker stop                  # Stop containers
odoo-dev docker restart               # Restart containers
odoo-dev docker logs                  # View logs
odoo-dev docker build                 # Rebuild image
odoo-dev docker shell mydb            # Shell in container
odoo-dev docker psql                  # PostgreSQL shell
```

### Setup Commands

```bash
odoo-dev setup                        # Full setup
odoo-dev setup --community            # Community edition only
odoo-dev setup-venv                   # Just create the venv (no repo clone)
odoo-dev vscode                       # Configure VSCode debugging
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
ODOO_VERSION=19.0
PYTHON_VERSION=3.12

# Optional — DB connection, written into conf/odoo.conf by `setup`.
# Omit DB_HOST/DB_PORT to use the local socket (the default). Set these to
# point at a remote / Docker / non-default PostgreSQL:
# DB_HOST=localhost
# DB_PORT=5432
# DB_USER=odoo
# DB_PASSWORD=odoo
```

## Requirements

- Python 3.12+
- uv (recommended) or pip
- Git
- PostgreSQL (for local development — server + an `odoo` role; see "Database setup")
- Docker (optional, for containerized development)

## Development

```bash
# Clone and install for development
git clone git@github.com:bemade/odoo-dev.git
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
