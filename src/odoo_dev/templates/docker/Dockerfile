ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

ARG ODOO_VERSION=17.0

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    dirmngr \
    fonts-noto-cjk \
    gnupg \
    libldap2-dev \
    libpq-dev \
    libsasl2-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    node-less \
    npm \
    python3-num2words \
    python3-pdfminer \
    python3-phonenumbers \
    python3-pyldap \
    python3-qrcode \
    python3-renderpm \
    python3-setuptools \
    python3-slugify \
    python3-vobject \
    python3-watchdog \
    python3-xlrd \
    python3-xlwt \
    xz-utils \
    postgresql-client \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install wkhtmltopdf
RUN curl -o wkhtmltox.deb -sSL https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb \
    && apt-get update && apt-get install -y --no-install-recommends ./wkhtmltox.deb \
    && rm -rf /var/lib/apt/lists/* wkhtmltox.deb

# Install debugpy
RUN uv pip install --system --no-cache debugpy

# Create odoo user and directories
RUN useradd -ms /bin/bash -d /opt/odoo odoo && \
    mkdir -p /var/lib/odoo && \
    mkdir -p /opt/odoo-filestore && \
    mkdir -p /etc/odoo && \
    chown -R odoo:odoo /var/lib/odoo /opt/odoo-filestore /etc/odoo

# Create project directory for mounted project files
RUN mkdir -p /opt/project && chown -R odoo:odoo /opt/project

# Copy requirements files
COPY odoo-requirements.txt /tmp/odoo-requirements.txt
COPY requirements.txt /tmp/requirements.txt

# Install Python dependencies
RUN uv pip install --system --no-cache -r /tmp/odoo-requirements.txt
RUN uv pip install --system --no-cache -r /tmp/requirements.txt

# Copy entrypoint script
COPY ./docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh

# Set default config
COPY ./odoo.conf /etc/odoo/
RUN chown odoo:odoo /etc/odoo/odoo.conf

# Set the default command
USER odoo
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["odoo"]
