# Changelog

All notable changes to this fork will be documented in this file.

## [1.0.1] - 2026-04-19

### Added

- Optional full-refresh toggles after `add_product` and `remove_product`
- Coalesced post-action refresh behavior to reduce refresh storms during bursty scripts

### Fixed

- Product sensor setup now completes reliably during initial setup
- Sensor lifecycle across reloads is more stable
- Product/list entity names are normalized without the `Grocy Products` prefix
- Added a `Force Refresh` button on the `Grocy` device

## [1.0.0] - 2026-04-19

Initial release of the `shopping_list_with_grocy_polling` fork.

### Added

- Parallel-installable Home Assistant integration with its own domain: `shopping_list_with_grocy_polling`
- Fixed-interval polling configurable in seconds
- Separate image refresh scheduling by interval or daily time
- Configurable request spacing in milliseconds between Grocy API requests
- Auto-reload when integration options are changed
- Optional Grocy aggregate device/entities for:
  - shopping list
  - stock
  - chores
  - tasks
  - meal plan
  - batteries
  - related overdue/expired/missing binary sensors
- Optional toggles in the config flow so chores, tasks, meal plan and batteries only fetch data when enabled
- Dedicated `Grocy` and `Grocy Products` devices
- `Force Refresh` button on the `Grocy` device

### Changed

- Removed the original `db-changed-time` driven refresh behavior in favor of explicit polling
- Separated image refreshes from the normal data polling cycle
- Kept product entities on a dedicated device without forcing the device name into the product friendly name

### Fixed

- HACS compatibility for the fork layout
- Config flow compatibility issues that prevented the integration from showing up correctly
- Python 3.14 dataclass/import issues in aggregate entities
- Product sensor creation during initial setup
- Sensor setup lifecycle issues across reloads
- Product entity name normalization for already existing registry entries
- Missing product image handling so stale image references do not spam 404 errors

[1.0.1]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.1
[1.0.0]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.0
