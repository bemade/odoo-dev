#!/bin/bash

set -e

# Set default config file
CONFIG_FILE=${ODOO_CONFIG_FILE:-"/etc/odoo/odoo.conf"}

# Function to wait for PostgreSQL to be ready
wait_for_db() {
    echo "Waiting for PostgreSQL..."
    while ! pg_isready -h $HOST -p 5432 -U $USER; do
        sleep 1
    done
    echo "PostgreSQL is ready!"
}

# Wait for PostgreSQL if it's the main command
if [ "$1" = 'odoo' ]; then
    wait_for_db

    echo "Starting Odoo with debugpy enabled on port 5678"
    # Run Odoo with debugpy enabled (without waiting for client)
    # Shift to remove the first argument ('odoo') so it's not passed to odoo-bin
    shift
    exec python -m debugpy --listen 0.0.0.0:5678 /opt/project/odoo/odoo-bin -c "$CONFIG_FILE" "$@"
fi

# If we're not running Odoo, just execute the command
exec "$@"
