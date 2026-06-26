# Changelog

## [1.1.0](https://github.com/bemade/odoo-dev/compare/v1.0.0...v1.1.0) (2026-06-26)


### Features

* add `bump` command for series-agnostic manifest version bumps ([#7](https://github.com/bemade/odoo-dev/issues/7)) ([992c8aa](https://github.com/bemade/odoo-dev/commit/992c8aa3731d262803a6f329209275462d88d80a))

## [1.0.0](https://github.com/bemade/odoo-dev/compare/v0.4.0...v1.0.0) (2026-06-11)


### ⚠ BREAKING CHANGES

* macOS `setup` no longer installs PostgreSQL. Fresh macOS setups must install a server themselves (or point DB_HOST/DB_PORT at a remote/Docker server).

### Features

* treat PostgreSQL as an external prerequisite on all platforms ([#5](https://github.com/bemade/odoo-dev/issues/5)) ([e817107](https://github.com/bemade/odoo-dev/commit/e817107ac434a5b23dd2675d59a95d1a6f8d1e71))

## [0.4.0](https://github.com/bemade/odoo-dev/compare/v0.3.3...v0.4.0) (2026-06-11)


### Features

* configurable DB connection + connectivity preflight ([#3](https://github.com/bemade/odoo-dev/issues/3)) ([632738e](https://github.com/bemade/odoo-dev/commit/632738e37c1d22d79ec4a03cba72a28ca580f7c8))
