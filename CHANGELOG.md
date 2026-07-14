# Changelog

## [1.2.1](https://github.com/bemade/odoo-dev/compare/v1.2.0...v1.2.1) (2026-07-14)


### Bug Fixes

* **test:** make full-suite runs work under a dev odoo.conf ([2a1b752](https://github.com/bemade/odoo-dev/commit/2a1b7527d29b3bf8bb776e41ce739b4864543b73))
* **vendor:** bump clears stale version when pinning to a commit ([19544ba](https://github.com/bemade/odoo-dev/commit/19544bac55a3dded4b912cc9f2ac7226f5d72d61))
* **vendor:** constrain `vendor update` to the pin's own major series ([5b58e26](https://github.com/bemade/odoo-dev/commit/5b58e2676de6c1b63a678d1dd365efca9e4c8b99))
* **vendor:** migrate sets version only when the tag resolves to the pin ([ea59b1d](https://github.com/bemade/odoo-dev/commit/ea59b1d62c9844fb831925d9973b4ec179b803e6))

## [1.2.0](https://github.com/bemade/odoo-dev/compare/v1.1.0...v1.2.0) (2026-07-07)


### Features

* add 'vendor' command for per-addon vendoring ([7dfe8cb](https://github.com/bemade/odoo-dev/commit/7dfe8cbbf20031b012bc3326485f9aa3b634146c))
* **setup:** add --no-docker and --yes for headless agentic setup ([daa62c4](https://github.com/bemade/odoo-dev/commit/daa62c496ceb923152305091c5f94958014f1a51))
* **setup:** skip submodule init for fully-vendored repos ([83b7818](https://github.com/bemade/odoo-dev/commit/83b78186a0a23b3d33eb12a5364d312794315158))
* **vendor:** add `vendor develop` local dev-loop for vendored addons ([89325f8](https://github.com/bemade/odoo-dev/commit/89325f88a9a51bfc4d4cb4ea755381c55e62989a))
* **vendor:** add `vendor update` — the pull side of vendoring ([fb88c1e](https://github.com/bemade/odoo-dev/commit/fb88c1e3b62604f59932811b772cd5e420eb5152))
* **vendor:** add vendored/ to the addons_path when present ([0fdc512](https://github.com/bemade/odoo-dev/commit/0fdc512a9c9df2541028a8743d1afb33240ac6de))
* **vendor:** assert-no-hybrid guard in `vendor check --no-hybrid` ([d424eca](https://github.com/bemade/odoo-dev/commit/d424eca69fac72f27a44e24ea3ca68fe9e7b37af))
* **vendor:** test and cover vendored/ addons alongside local ones ([a989d17](https://github.com/bemade/odoo-dev/commit/a989d174cc6cc84da5cae7fad327c017cbaf8030))


### Bug Fixes

* **vendor:** compare python-dep package NAMES, not full spec strings ([6903fa3](https://github.com/bemade/odoo-dev/commit/6903fa307dfab977cb40b9d7dfee2d017f67a0ff))


### Documentation

* document the vendor command + agentic setup flag ([523ac05](https://github.com/bemade/odoo-dev/commit/523ac050bcd103d18b99abc8cc3a50ab0c6886c4))

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
