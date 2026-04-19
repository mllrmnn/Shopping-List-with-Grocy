"""Coordinator for the Shopping List with Grocy integration."""

import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_IMAGE_REFRESH_INTERVAL_HOURS,
    CONF_IMAGE_REFRESH_MODE,
    CONF_IMAGE_REFRESH_TIME,
    CONF_POLL_INTERVAL_SECONDS,
    CONF_REFRESH_AFTER_ADD_PRODUCT,
    CONF_REFRESH_AFTER_REMOVE_PRODUCT,
    DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS,
    DEFAULT_IMAGE_REFRESH_MODE,
    DEFAULT_IMAGE_REFRESH_TIME,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_REFRESH_AFTER_ADD_PRODUCT,
    DEFAULT_REFRESH_AFTER_REMOVE_PRODUCT,
    DOMAIN,
    IMAGE_REFRESH_MODE_DAILY_TIME,
)
from .utils import is_update_paused

LOGGER = logging.getLogger(__name__)

# TTL for ephemeral voice/choice entries before they are garbage-collected.
_CHOICE_TTL_SECONDS = 2 * 60  # 2 minutes
_ACTION_REFRESH_INTERVAL_SECONDS = 0.1


def _purge_stale_keys(mapping: dict, threshold: float) -> bool:
    """Remove entries whose 'timestamp' is older than *threshold* seconds ago.

    Returns True if anything was removed.
    """
    now = time.time()
    stale = [k for k, v in mapping.items() if now - v.get("timestamp", 0) > threshold]
    for k in stale:
        del mapping[k]
    return bool(stale)


class ShoppingListWithGrocyCoordinator(DataUpdateCoordinator):
    """Coordinator to manage fetching data from Grocy API."""

    def __init__(self, hass, session, entry, api):
        """Initialize the coordinator."""
        config = {**entry.data, **(entry.options or {})}
        self._config = config
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(
                seconds=config.get(
                    CONF_POLL_INTERVAL_SECONDS, DEFAULT_POLL_INTERVAL_SECONDS
                )
            ),
        )
        self.hass = hass
        self.session = session
        self.entry = entry
        self.api = api
        self.last_successful_fetch = None
        self.entities = []

        self.data = hass.data.setdefault(DOMAIN, {}).setdefault("products", {})
        self._parsed_data = {}
        self._image_refresh_unsub = None
        self._action_refresh_task = None
        self._action_refresh_pending = False
        self._next_action_refresh_time = 0.0

        homeassistant_products = self.data.get("homeassistant_products", {})
        if not isinstance(homeassistant_products, dict):
            LOGGER.error("❌ homeassistant_products is not a dictionary! Resetting.")
            homeassistant_products = {}
        self._parsed_data.update(homeassistant_products)

    async def _async_update_data(self):
        await self.retrieve_data()
        return self.data

    async def add_product(self, product_id, shopping_list_id, note, quantity=1):
        return await self.api.manage_product(
            product_id, shopping_list_id, note, False, quantity
        )

    async def remove_product(self, product_id, shopping_list_id):
        return await self.api.manage_product(product_id, shopping_list_id, "", True)

    async def update_note(self, product_id, shopping_list_id, note):
        return await self.api.update_note(product_id, shopping_list_id, note)

    async def request_update(self):
        await self.retrieve_data(True)
        return self.data

    async def request_update_after_action(self) -> None:
        """Coalesce bursts of post-action refresh requests."""
        self._action_refresh_pending = True
        if self._action_refresh_task and not self._action_refresh_task.done():
            return
        self._action_refresh_task = self.hass.async_create_task(
            self._async_process_action_refresh_queue()
        )

    async def _async_process_action_refresh_queue(self) -> None:
        """Run a leading refresh plus at most one trailing refresh per burst."""
        try:
            while True:
                self._action_refresh_pending = False
                wait_time = self._next_action_refresh_time - self.hass.loop.time()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

                await self.request_update()
                self._next_action_refresh_time = (
                    self.hass.loop.time() + _ACTION_REFRESH_INTERVAL_SECONDS
                )

                if not self._action_refresh_pending:
                    break
        finally:
            self._action_refresh_task = None

    def should_refresh_after_add(self) -> bool:
        """Return whether add actions should trigger a coalesced refresh."""
        return self._config.get(
            CONF_REFRESH_AFTER_ADD_PRODUCT, DEFAULT_REFRESH_AFTER_ADD_PRODUCT
        )

    def should_refresh_after_remove(self) -> bool:
        """Return whether remove actions should trigger a coalesced refresh."""
        return self._config.get(
            CONF_REFRESH_AFTER_REMOVE_PRODUCT, DEFAULT_REFRESH_AFTER_REMOVE_PRODUCT
        )

    async def cleanup_orphaned_choices(self) -> None:
        """Garbage-collect ephemeral voice/choice data older than TTL.

        Single authoritative implementation — services.py delegates here
        instead of duplicating the logic.
        """
        if DOMAIN not in self.hass.data:
            return

        domain = self.hass.data[DOMAIN]
        changed = False

        for bucket in ("product_choices", "recent_multiple_choices", "voice_responses"):
            mapping = domain.get(bucket, {})
            if mapping:
                changed |= _purge_stale_keys(mapping, _CHOICE_TTL_SECONDS)

        if changed:
            async_dispatcher_send(self.hass, "grocy_multiple_choices_updated")

    # Keep the old private name as an alias so existing callers inside this
    # file don't break while we migrate them.
    _cleanup_orphaned_choices = cleanup_orphaned_choices

    async def retrieve_data(self, force=False):
        """Fetch fresh data from Grocy if the DB has changed."""
        await self.cleanup_orphaned_choices()

        try:
            paused = is_update_paused(self.hass)

            if not paused:
                data = await self.api.retrieve_data(force)

                if data is not None:
                    self.last_successful_fetch = self.hass.loop.time()
                    self.data = data
                    homeassistant_products = self.data.get("homeassistant_products", {})
                    if not isinstance(homeassistant_products, dict):
                        LOGGER.error(
                            "❌ homeassistant_products is not a dictionary! Resetting."
                        )
                        homeassistant_products = {}
                    for product_id, product_data in homeassistant_products.items():
                        if product_id in self._parsed_data:
                            self._parsed_data[product_id]["qty_in_shopping_lists"] = (
                                product_data["qty_in_shopping_lists"]
                            )

                            existing_attributes = self._parsed_data[product_id][
                                "attributes"
                            ]
                            new_attributes = product_data.get("attributes", {})

                            existing_shopping_keys = {
                                key
                                for key in existing_attributes
                                if key.startswith("list_")
                            }
                            new_shopping_keys = {
                                key for key in new_attributes if key.startswith("list_")
                            }
                            keys_to_remove = existing_shopping_keys - new_shopping_keys

                            for key in keys_to_remove:
                                existing_attributes.pop(key, None)

                            existing_attributes.update(new_attributes)

                        else:
                            self._parsed_data[product_id] = product_data

                else:
                    LOGGER.warning("Received empty or invalid data from API.")
        except Exception as e:
            LOGGER.exception(
                "Unexpected error while fetching data from Grocy API: %s", e
            )

    async def async_refresh_images(self, initial: bool = False) -> None:
        """Refresh product images using the separate image scheduler."""
        if is_update_paused(self.hass):
            return

        try:
            await self.api.refresh_product_images()
            if initial:
                LOGGER.debug("Initial product image refresh completed")
        except Exception:
            LOGGER.debug("Product image refresh failed", exc_info=True)

    async def async_setup_image_schedule(self) -> None:
        """Set up image refresh scheduling independent from data polling."""
        if self._image_refresh_unsub is not None:
            self._image_refresh_unsub()
            self._image_refresh_unsub = None

        if self.api.image_size <= 0:
            return

        image_mode = self._config.get(
            CONF_IMAGE_REFRESH_MODE, DEFAULT_IMAGE_REFRESH_MODE
        )

        if image_mode == IMAGE_REFRESH_MODE_DAILY_TIME:
            raw_time = self._config.get(
                CONF_IMAGE_REFRESH_TIME, DEFAULT_IMAGE_REFRESH_TIME
            )
            hour_str, minute_str = raw_time.split(":", maxsplit=1)
            self._image_refresh_unsub = async_track_time_change(
                self.hass,
                self._handle_scheduled_image_refresh,
                hour=int(hour_str),
                minute=int(minute_str),
                second=0,
            )
        else:
            refresh_hours = self._config.get(
                CONF_IMAGE_REFRESH_INTERVAL_HOURS,
                DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS,
            )
            self._image_refresh_unsub = async_track_time_interval(
                self.hass,
                self._handle_scheduled_image_refresh,
                timedelta(hours=refresh_hours),
            )

        self.hass.async_create_task(self.async_refresh_images(initial=True))

    async def _handle_scheduled_image_refresh(self, _now) -> None:
        """Run image refreshes on the configured schedule."""
        await self.async_refresh_images()

    async def async_shutdown(self) -> None:
        """Cancel scheduled callbacks when the entry unloads."""
        if self._image_refresh_unsub is not None:
            self._image_refresh_unsub()
            self._image_refresh_unsub = None
        if self._action_refresh_task and not self._action_refresh_task.done():
            self._action_refresh_task.cancel()
            self._action_refresh_task = None
