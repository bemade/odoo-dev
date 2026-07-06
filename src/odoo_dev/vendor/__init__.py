"""Per-addon vendoring: materialize shared Odoo addons as committed real files
in a client repo, pinned by an ``addons.lock``.

See the design spec (Bemade Infrastructure task) for the full rationale. The
short version: a submodule pointer is repo-granular, so promoting one approved
change drags the whole submodule's accumulated (possibly cross-client,
non-approved) changes onto prod. Vendoring makes the promotion unit a normal
file diff, pinned per-addon, and deploys as plain committed files (which is what
Odoo.sh needs — it runs no build step and can't install private wheels).
"""
