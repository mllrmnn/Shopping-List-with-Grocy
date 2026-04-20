# Changelog

All notable changes to this fork will be documented in this file.

## [1.0.11] - 2026-04-20

### Added

- Added API-backed Grocy-style aggregate sensors for locations and shopping-list locations

### Changed

- Display product image size options as `px` in the configuration UI while keeping the stored values unchanged

## [1.0.10] - 2026-04-20

### Fixed

- Product entity friendly names now follow Grocy product names on every product update, with Grocy treated as the source of truth

## [1.0.9] - 2026-04-20

### Fixed

- Changed product image size selection to an explicit Home Assistant list selector instead of `vol.In`, avoiding dropdown rendering

## [1.0.8] - 2026-04-20

### Fixed

- Restored the product image size option to the previous list-style selector while keeping the new 10% and 25% values

## [1.0.7] - 2026-04-20

### Changed

- Removed the redundant `product_image` Base64 attribute from product entities while keeping `entity_picture` for UI cards
- Existing `product_image` attributes are removed on the next product image update

## [1.0.6] - 2026-04-20

### Fixed

- Tracked and cancelled background image refresh tasks during reload/delete
- Cancelled pending To-do retry handles during unload
- Avoided hard reloads when options saving only adds benign default/runtime fields
- Made integration unload cleanup more defensive before deleting the integration entry

## [1.0.5] - 2026-04-20

### Changed

- Changed defaults to poll data every 600 seconds with 75 ms request spacing
- Changed the default image refresh schedule to daily at 03:47
- Changed the default image download size to 25% and added 10% and 25% image options
- Enabled post-`add_product` and post-`remove_product` product/shopping-list refreshes by default

## [1.0.4] - 2026-04-20

### Fixed

- Saving the options form without changes no longer reloads the integration
- Lightweight runtime options such as poll interval, request spacing and image refresh schedule are applied live instead of forcing a full unload/setup cycle

## [1.0.3] - 2026-04-19

### Fixed

- Restored Grocy-compatible `missing_products` unit metadata so Lovelace templates can safely read `default_quantity_unit_purchase.name` and `name_plural`
- Removed slow per-product dispatcher sleeps that could stall startup while dynamic product sensors were being refreshed
- Delayed the initial product image refresh so Home Assistant startup is no longer held open by image downloads
- Stopped large image/list attributes from being written into Recorder for product and aggregate entities while keeping them available at runtime
- Hardened refresh-status and frontend unload handling during reload/shutdown to avoid unload-time errors
- Avoided un-awaited entity add callbacks in To-do setup paths

## [1.0.2] - 2026-04-19

### Changed

- Action-triggered refreshes after `add_product` and `remove_product` now update only the affected product entities plus the shopping list instead of doing a full refresh
- Burst handling for action-triggered refreshes still coalesces rapid sequences to avoid refresh storms

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

[1.0.11]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.11
[1.0.10]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.10
[1.0.9]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.9
[1.0.8]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.8
[1.0.7]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.7
[1.0.6]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.6
[1.0.5]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.5
[1.0.4]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.4
[1.0.3]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.3
[1.0.2]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.2
[1.0.1]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.1
[1.0.0]: https://github.com/mllrmnn/Shopping-List-with-Grocy/releases/tag/v1.0.0
