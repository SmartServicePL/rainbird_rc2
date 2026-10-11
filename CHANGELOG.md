# Changelog

## 1.1.1

- `pyrainbird` requirement changed from `==6.5.0` to `>=6.6.0`. 6.6.0 is the version used by the Home Assistant core Rain Bird integration since 2026.10, and Home Assistant does not allow custom integrations to pin a package it depends on, so the integration now uses the version installed with Home Assistant. The local RC2 commands and encryption used by this integration are unchanged between 6.5.0 and 6.6.0.
- Minimum Home Assistant version raised to 2026.4.0. `pyrainbird` 6.5.0 and newer require `aiohttp` 3.13.5, which older Home Assistant releases do not allow, so the integration could not install its requirements there (this already applied to 1.0.1 and 1.1.0).
- Validation workflow uses `actions/checkout@v5` and also runs every Monday and on demand, so a new Home Assistant or `pyrainbird` release that breaks validation is noticed without a new commit.

## 1.1.0

- Fixed PIN renewal: reauthentication now removes the old address/PIN copy from the integration options, so the new PIN is actually used after the reload.
- Changing the default manual duration (number entity or options) no longer reloads the integration, so it no longer stops a running station. Only address, PIN, SSL or polling interval changes reload the entry.
- `rainbird_rc2.start_zone` and `rainbird_rc2.stop_zone` resolve the station through the entity registry, so a stop command also works while the station entity is temporarily unavailable.
- A run started by the controller program or the Rain Bird app no longer inherits the planned duration of an older Home Assistant start. After a reload only runs started by Home Assistant get their stop timer back, so a controller program is not stopped early. Runs that were in progress while updating from 1.0.x are left to the controller's own runtime.
- A PIN rejected during polling now starts the Home Assistant reauthentication flow.
- Station switches report command failures as readable Home Assistant errors.
- Relative timing uses a monotonic clock, so daylight saving time changes do not affect the start grace period.
- The self-signed certificate warning is silenced only for the configured controller instead of the whole Home Assistant process.
- Entity names come from translations (English and Polish); Polish texts use Polish characters. The `start_zone` duration field no longer defaults to 10 minutes in the UI, so an empty field uses the configured default duration as described.
- Manifest: `loggers` points to `pyrainbird`, keys are sorted, `CONFIG_SCHEMA` added; hassfest and HACS validation workflow added.

## 1.0.1

- Updated `pyrainbird` from `6.0.1` to `6.5.0`.
- Added upstream Rain Bird 2.x controller compatibility fixes.
- Added upstream encryption and LNK2 firmware communication fixes.
- Preserved the existing LAN-only entities, services and run-history format.

## 1.0.0

- Initial public local-only Rain Bird RC2 integration.
