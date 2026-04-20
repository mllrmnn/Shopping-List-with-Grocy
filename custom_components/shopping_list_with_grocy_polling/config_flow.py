import logging
import re
import uuid
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .analysis_const import (
    ANALYSIS_SCHEMA,
    CONF_ANALYSIS_SETTINGS,
    CONF_CONSUMPTION_WEIGHT,
    CONF_FREQUENCY_WEIGHT,
    CONF_SCORE_THRESHOLD,
    CONF_SEASONAL_WEIGHT,
    DEFAULT_CONSUMPTION_WEIGHT,
    DEFAULT_FREQUENCY_WEIGHT,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_SEASONAL_WEIGHT,
)
from .const import (
    CONF_ENABLE_BATTERIES,
    CONF_ENABLE_CHORES,
    CONF_ENABLE_MEAL_PLAN,
    CONF_REFRESH_AFTER_ADD_PRODUCT,
    CONF_REFRESH_AFTER_REMOVE_PRODUCT,
    DOMAIN,
    CONF_ENABLE_PRODUCT_SENSORS,
    CONF_ENABLE_TASKS,
    CONF_IMAGE_REFRESH_INTERVAL_HOURS,
    CONF_IMAGE_REFRESH_MODE,
    CONF_IMAGE_REFRESH_TIME,
    CONF_POLL_INTERVAL_SECONDS,
    CONF_REQUEST_SPACING_MS,
    CONF_SELECTION_CRITERIA,
    CONF_PREFER_GENERIC_PRODUCTS,
    CONF_AUTO_SELECT_FIRST,
    CONF_SUGGEST_CREATE_ONLY_NO_MATCH,
    DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS,
    DEFAULT_IMAGE_REFRESH_MODE,
    DEFAULT_IMAGE_REFRESH_TIME,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_REQUEST_SPACING_MS,
    DEFAULT_PREFER_GENERIC_PRODUCTS,
    DEFAULT_AUTO_SELECT_FIRST,
    DEFAULT_ENABLE_BATTERIES,
    DEFAULT_ENABLE_CHORES,
    DEFAULT_IMAGE_DOWNLOAD_SIZE,
    DEFAULT_ENABLE_MEAL_PLAN,
    DEFAULT_ENABLE_TASKS,
    DEFAULT_REFRESH_AFTER_ADD_PRODUCT,
    DEFAULT_REFRESH_AFTER_REMOVE_PRODUCT,
    DEFAULT_SUGGEST_CREATE_ONLY_NO_MATCH,
    IMAGE_REFRESH_MODE_DAILY_TIME,
    IMAGE_REFRESH_MODE_INTERVAL,
)
from .schema import SELECTION_CRITERIA_SCHEMA

_LOGGER = logging.getLogger(__name__)

IMAGE_DOWNLOAD_SIZE_OPTIONS = [0, 10, 25, 50, 100, 150, 200]


class ShoppingListWithGrocyOptionsConfigFlow(config_entries.OptionsFlow):  # type: ignore
    """Handle option configuration via Integrations page."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._stored_config_entry = config_entry
        self.options = dict(config_entry.options or config_entry.data)

        if CONF_ANALYSIS_SETTINGS not in self.options:
            self.options[CONF_ANALYSIS_SETTINGS] = {
                CONF_CONSUMPTION_WEIGHT: DEFAULT_CONSUMPTION_WEIGHT,
                CONF_FREQUENCY_WEIGHT: DEFAULT_FREQUENCY_WEIGHT,
                CONF_SEASONAL_WEIGHT: DEFAULT_SEASONAL_WEIGHT,
                CONF_SCORE_THRESHOLD: DEFAULT_SCORE_THRESHOLD,
            }

        if CONF_SELECTION_CRITERIA not in self.options:
            self.options[CONF_SELECTION_CRITERIA] = {
                CONF_PREFER_GENERIC_PRODUCTS: DEFAULT_PREFER_GENERIC_PRODUCTS,
                CONF_AUTO_SELECT_FIRST: DEFAULT_AUTO_SELECT_FIRST,
            }
        self._data = {"unique_id": self.options.get("unique_id")}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        self._errors = {}

        if user_input is not None:
            if user_input.get("show_advanced", False):
                if not is_valid_url(user_input.get("api_url", "")):
                    self._errors["base"] = "invalid_api_url"
                elif not is_valid_time_string(
                    user_input.get(
                        CONF_IMAGE_REFRESH_TIME, DEFAULT_IMAGE_REFRESH_TIME
                    )
                ):
                    self._errors["base"] = "invalid_image_refresh_time"
                else:
                    self.options.update(
                        {
                            "api_url": user_input["api_url"],
                            "api_key": user_input["api_key"],
                            "verify_ssl": user_input.get("verify_ssl", True),
                            "disable_timeout": user_input.get("disable_timeout", False),
                            "image_download_size": user_input.get(
                                "image_download_size", DEFAULT_IMAGE_DOWNLOAD_SIZE
                            ),
                            CONF_POLL_INTERVAL_SECONDS: user_input.get(
                                CONF_POLL_INTERVAL_SECONDS,
                                DEFAULT_POLL_INTERVAL_SECONDS,
                            ),
                            CONF_REQUEST_SPACING_MS: user_input.get(
                                CONF_REQUEST_SPACING_MS,
                                DEFAULT_REQUEST_SPACING_MS,
                            ),
                            CONF_IMAGE_REFRESH_MODE: user_input.get(
                                CONF_IMAGE_REFRESH_MODE,
                                DEFAULT_IMAGE_REFRESH_MODE,
                            ),
                            CONF_IMAGE_REFRESH_INTERVAL_HOURS: user_input.get(
                                CONF_IMAGE_REFRESH_INTERVAL_HOURS,
                                DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS,
                            ),
                            CONF_IMAGE_REFRESH_TIME: user_input.get(
                                CONF_IMAGE_REFRESH_TIME,
                                DEFAULT_IMAGE_REFRESH_TIME,
                            ),
                            "enable_bidirectional_sync": user_input.get(
                                "enable_bidirectional_sync", False
                            ),
                            CONF_ENABLE_PRODUCT_SENSORS: user_input.get(
                                CONF_ENABLE_PRODUCT_SENSORS, True
                            ),
                            CONF_ENABLE_CHORES: user_input.get(
                                CONF_ENABLE_CHORES, DEFAULT_ENABLE_CHORES
                            ),
                            CONF_ENABLE_TASKS: user_input.get(
                                CONF_ENABLE_TASKS, DEFAULT_ENABLE_TASKS
                            ),
                            CONF_ENABLE_MEAL_PLAN: user_input.get(
                                CONF_ENABLE_MEAL_PLAN, DEFAULT_ENABLE_MEAL_PLAN
                            ),
                            CONF_ENABLE_BATTERIES: user_input.get(
                                CONF_ENABLE_BATTERIES, DEFAULT_ENABLE_BATTERIES
                            ),
                            CONF_REFRESH_AFTER_ADD_PRODUCT: user_input.get(
                                CONF_REFRESH_AFTER_ADD_PRODUCT,
                                DEFAULT_REFRESH_AFTER_ADD_PRODUCT,
                            ),
                            CONF_REFRESH_AFTER_REMOVE_PRODUCT: user_input.get(
                                CONF_REFRESH_AFTER_REMOVE_PRODUCT,
                                DEFAULT_REFRESH_AFTER_REMOVE_PRODUCT,
                            ),
                        }
                    )
                    return await self.async_step_advanced()
            if user_input.get("show_advanced", False):
                return await self.async_step_advanced()

            if not is_valid_url(user_input.get("api_url", "")):
                self._errors["base"] = "invalid_api_url"
            elif not is_valid_time_string(
                user_input.get(CONF_IMAGE_REFRESH_TIME, DEFAULT_IMAGE_REFRESH_TIME)
            ):
                self._errors["base"] = "invalid_image_refresh_time"

            if not self._errors:
                updated_data = {
                    "api_url": user_input["api_url"],
                    "api_key": user_input["api_key"],
                    "verify_ssl": user_input.get("verify_ssl", True),
                    "disable_timeout": user_input.get("disable_timeout", False),
                    "image_download_size": user_input.get(
                        "image_download_size", DEFAULT_IMAGE_DOWNLOAD_SIZE
                    ),
                    CONF_POLL_INTERVAL_SECONDS: user_input.get(
                        CONF_POLL_INTERVAL_SECONDS,
                        DEFAULT_POLL_INTERVAL_SECONDS,
                    ),
                    CONF_REQUEST_SPACING_MS: user_input.get(
                        CONF_REQUEST_SPACING_MS,
                        DEFAULT_REQUEST_SPACING_MS,
                    ),
                    CONF_IMAGE_REFRESH_MODE: user_input.get(
                        CONF_IMAGE_REFRESH_MODE,
                        DEFAULT_IMAGE_REFRESH_MODE,
                    ),
                    CONF_IMAGE_REFRESH_INTERVAL_HOURS: user_input.get(
                        CONF_IMAGE_REFRESH_INTERVAL_HOURS,
                        DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS,
                    ),
                    CONF_IMAGE_REFRESH_TIME: user_input.get(
                        CONF_IMAGE_REFRESH_TIME,
                        DEFAULT_IMAGE_REFRESH_TIME,
                    ),
                    "enable_bidirectional_sync": user_input.get(
                        "enable_bidirectional_sync", False
                    ),
                    CONF_ENABLE_PRODUCT_SENSORS: user_input.get(
                        CONF_ENABLE_PRODUCT_SENSORS, True
                    ),
                    CONF_ENABLE_CHORES: user_input.get(
                        CONF_ENABLE_CHORES, DEFAULT_ENABLE_CHORES
                    ),
                    CONF_ENABLE_TASKS: user_input.get(
                        CONF_ENABLE_TASKS, DEFAULT_ENABLE_TASKS
                    ),
                    CONF_ENABLE_MEAL_PLAN: user_input.get(
                        CONF_ENABLE_MEAL_PLAN, DEFAULT_ENABLE_MEAL_PLAN
                    ),
                    CONF_ENABLE_BATTERIES: user_input.get(
                        CONF_ENABLE_BATTERIES, DEFAULT_ENABLE_BATTERIES
                    ),
                    CONF_REFRESH_AFTER_ADD_PRODUCT: user_input.get(
                        CONF_REFRESH_AFTER_ADD_PRODUCT,
                        DEFAULT_REFRESH_AFTER_ADD_PRODUCT,
                    ),
                    CONF_REFRESH_AFTER_REMOVE_PRODUCT: user_input.get(
                        CONF_REFRESH_AFTER_REMOVE_PRODUCT,
                        DEFAULT_REFRESH_AFTER_REMOVE_PRODUCT,
                    ),
                    "unique_id": self.options.get("unique_id"),
                    CONF_ANALYSIS_SETTINGS: self.options.get(
                        CONF_ANALYSIS_SETTINGS,
                        {
                            CONF_CONSUMPTION_WEIGHT: DEFAULT_CONSUMPTION_WEIGHT,
                            CONF_FREQUENCY_WEIGHT: DEFAULT_FREQUENCY_WEIGHT,
                            CONF_SEASONAL_WEIGHT: DEFAULT_SEASONAL_WEIGHT,
                            CONF_SCORE_THRESHOLD: DEFAULT_SCORE_THRESHOLD,
                        },
                    ),
                    "disable_notifications": user_input.get(
                        "disable_notifications", False
                    ),
                    CONF_SELECTION_CRITERIA: self.options.get(
                        CONF_SELECTION_CRITERIA,
                        {
                            CONF_PREFER_GENERIC_PRODUCTS: DEFAULT_PREFER_GENERIC_PRODUCTS,
                            CONF_AUTO_SELECT_FIRST: DEFAULT_AUTO_SELECT_FIRST,
                            CONF_SUGGEST_CREATE_ONLY_NO_MATCH: DEFAULT_SUGGEST_CREATE_ONLY_NO_MATCH,
                        },
                    ),
                }

                old_api_url = self.options.get("api_url")
                old_api_key = self.options.get("api_key")
                old_bidirectional_sync = self.options.get(
                    "enable_bidirectional_sync", False
                )
                old_disable_timeout = self.options.get("disable_timeout", False)
                old_image_size = self.options.get(
                    "image_download_size", DEFAULT_IMAGE_DOWNLOAD_SIZE
                )
                old_poll_interval = self.options.get(
                    CONF_POLL_INTERVAL_SECONDS, DEFAULT_POLL_INTERVAL_SECONDS
                )
                old_request_spacing_ms = self.options.get(
                    CONF_REQUEST_SPACING_MS, DEFAULT_REQUEST_SPACING_MS
                )
                old_image_refresh_mode = self.options.get(
                    CONF_IMAGE_REFRESH_MODE, DEFAULT_IMAGE_REFRESH_MODE
                )
                old_image_refresh_interval = self.options.get(
                    CONF_IMAGE_REFRESH_INTERVAL_HOURS,
                    DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS,
                )
                old_image_refresh_time = self.options.get(
                    CONF_IMAGE_REFRESH_TIME, DEFAULT_IMAGE_REFRESH_TIME
                )
                old_product_sensors = self.options.get(
                    CONF_ENABLE_PRODUCT_SENSORS, True
                )
                old_enable_chores = self.options.get(
                    CONF_ENABLE_CHORES, DEFAULT_ENABLE_CHORES
                )
                old_enable_tasks = self.options.get(
                    CONF_ENABLE_TASKS, DEFAULT_ENABLE_TASKS
                )
                old_enable_meal_plan = self.options.get(
                    CONF_ENABLE_MEAL_PLAN, DEFAULT_ENABLE_MEAL_PLAN
                )
                old_enable_batteries = self.options.get(
                    CONF_ENABLE_BATTERIES, DEFAULT_ENABLE_BATTERIES
                )
                old_refresh_after_add = self.options.get(
                    CONF_REFRESH_AFTER_ADD_PRODUCT,
                    DEFAULT_REFRESH_AFTER_ADD_PRODUCT,
                )
                old_refresh_after_remove = self.options.get(
                    CONF_REFRESH_AFTER_REMOVE_PRODUCT,
                    DEFAULT_REFRESH_AFTER_REMOVE_PRODUCT,
                )

                settings_changed = (
                    old_api_url
                    and old_api_key
                    and (
                        old_api_url != user_input["api_url"]
                        or old_api_key != user_input["api_key"]
                        or old_bidirectional_sync
                        != user_input.get("enable_bidirectional_sync", False)
                        or old_disable_timeout
                        != user_input.get("disable_timeout", False)
                        or old_image_size
                        != user_input.get(
                            "image_download_size", DEFAULT_IMAGE_DOWNLOAD_SIZE
                        )
                        or old_poll_interval
                        != user_input.get(
                            CONF_POLL_INTERVAL_SECONDS,
                            DEFAULT_POLL_INTERVAL_SECONDS,
                        )
                        or old_request_spacing_ms
                        != user_input.get(
                            CONF_REQUEST_SPACING_MS,
                            DEFAULT_REQUEST_SPACING_MS,
                        )
                        or old_image_refresh_mode
                        != user_input.get(
                            CONF_IMAGE_REFRESH_MODE, DEFAULT_IMAGE_REFRESH_MODE
                        )
                        or old_image_refresh_interval
                        != user_input.get(
                            CONF_IMAGE_REFRESH_INTERVAL_HOURS,
                            DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS,
                        )
                        or old_image_refresh_time
                        != user_input.get(
                            CONF_IMAGE_REFRESH_TIME, DEFAULT_IMAGE_REFRESH_TIME
                        )
                        or old_product_sensors
                        != user_input.get(CONF_ENABLE_PRODUCT_SENSORS, True)
                        or old_enable_chores
                        != user_input.get(CONF_ENABLE_CHORES, DEFAULT_ENABLE_CHORES)
                        or old_enable_tasks
                        != user_input.get(CONF_ENABLE_TASKS, DEFAULT_ENABLE_TASKS)
                        or old_enable_meal_plan
                        != user_input.get(
                            CONF_ENABLE_MEAL_PLAN, DEFAULT_ENABLE_MEAL_PLAN
                        )
                        or old_enable_batteries
                        != user_input.get(
                            CONF_ENABLE_BATTERIES, DEFAULT_ENABLE_BATTERIES
                        )
                        or old_refresh_after_add
                        != user_input.get(
                            CONF_REFRESH_AFTER_ADD_PRODUCT,
                            DEFAULT_REFRESH_AFTER_ADD_PRODUCT,
                        )
                        or old_refresh_after_remove
                        != user_input.get(
                            CONF_REFRESH_AFTER_REMOVE_PRODUCT,
                            DEFAULT_REFRESH_AFTER_REMOVE_PRODUCT,
                        )
                    )
                )
                first_time_setup = not (old_api_url and old_api_key)

                return self.async_create_entry(title="", data=updated_data)

        # Create base schema
        base_schema = {
            vol.Required("api_url", default=self.options.get("api_url", "")): str,
            vol.Required(
                "verify_ssl", default=self.options.get("verify_ssl", True)
            ): bool,
            vol.Required("api_key", default=self.options.get("api_key", "")): str,
            vol.Optional(
                "disable_timeout",
                default=self.options.get("disable_timeout", False),
            ): bool,
            vol.Optional(
                "image_download_size",
                default=self.options.get(
                    "image_download_size", DEFAULT_IMAGE_DOWNLOAD_SIZE
                ),
            ): vol.All(vol.Coerce(int), vol.In(IMAGE_DOWNLOAD_SIZE_OPTIONS)),
            vol.Optional(
                CONF_POLL_INTERVAL_SECONDS,
                default=self.options.get(
                    CONF_POLL_INTERVAL_SECONDS, DEFAULT_POLL_INTERVAL_SECONDS
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=86400)),
            vol.Optional(
                CONF_REQUEST_SPACING_MS,
                default=self.options.get(
                    CONF_REQUEST_SPACING_MS, DEFAULT_REQUEST_SPACING_MS
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=60000)),
            vol.Optional(
                CONF_IMAGE_REFRESH_MODE,
                default=self.options.get(
                    CONF_IMAGE_REFRESH_MODE, DEFAULT_IMAGE_REFRESH_MODE
                ),
            ): vol.In(
                {
                    IMAGE_REFRESH_MODE_INTERVAL: "Interval",
                    IMAGE_REFRESH_MODE_DAILY_TIME: "Daily time",
                }
            ),
            vol.Optional(
                CONF_IMAGE_REFRESH_INTERVAL_HOURS,
                default=self.options.get(
                    CONF_IMAGE_REFRESH_INTERVAL_HOURS,
                    DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS,
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
            vol.Optional(
                CONF_IMAGE_REFRESH_TIME,
                default=self.options.get(
                    CONF_IMAGE_REFRESH_TIME, DEFAULT_IMAGE_REFRESH_TIME
                ),
            ): str,
            vol.Optional(
                "enable_bidirectional_sync",
                default=self.options.get("enable_bidirectional_sync", False),
            ): bool,
            vol.Optional(
                CONF_ENABLE_PRODUCT_SENSORS,
                default=self.options.get(CONF_ENABLE_PRODUCT_SENSORS, True),
            ): bool,
            vol.Optional(
                CONF_ENABLE_CHORES,
                default=self.options.get(
                    CONF_ENABLE_CHORES, DEFAULT_ENABLE_CHORES
                ),
            ): bool,
            vol.Optional(
                CONF_ENABLE_TASKS,
                default=self.options.get(CONF_ENABLE_TASKS, DEFAULT_ENABLE_TASKS),
            ): bool,
            vol.Optional(
                CONF_ENABLE_MEAL_PLAN,
                default=self.options.get(
                    CONF_ENABLE_MEAL_PLAN, DEFAULT_ENABLE_MEAL_PLAN
                ),
            ): bool,
            vol.Optional(
                CONF_ENABLE_BATTERIES,
                default=self.options.get(
                    CONF_ENABLE_BATTERIES, DEFAULT_ENABLE_BATTERIES
                ),
            ): bool,
            vol.Optional(
                CONF_REFRESH_AFTER_ADD_PRODUCT,
                default=self.options.get(
                    CONF_REFRESH_AFTER_ADD_PRODUCT,
                    DEFAULT_REFRESH_AFTER_ADD_PRODUCT,
                ),
            ): bool,
            vol.Optional(
                CONF_REFRESH_AFTER_REMOVE_PRODUCT,
                default=self.options.get(
                    CONF_REFRESH_AFTER_REMOVE_PRODUCT,
                    DEFAULT_REFRESH_AFTER_REMOVE_PRODUCT,
                ),
            ): bool,
            vol.Optional("show_advanced", default=False): bool,
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(base_schema),
            errors=self._errors,
            description_placeholders={
                "disclaimer": "ℹ️ The shopping suggestions work great with default settings. Only access advanced settings if you need to fine-tune the algorithm.",
            },
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle advanced settings with disclaimer."""
        self._errors = {}
        current_analysis_settings = self.options.get(CONF_ANALYSIS_SETTINGS, {})
        current_selection_criteria = self.options.get(CONF_SELECTION_CRITERIA, {})

        if user_input is not None:
            try:
                # Extract analysis settings
                analysis_settings = {
                    CONF_CONSUMPTION_WEIGHT: user_input.get(
                        CONF_CONSUMPTION_WEIGHT, DEFAULT_CONSUMPTION_WEIGHT
                    ),
                    CONF_FREQUENCY_WEIGHT: user_input.get(
                        CONF_FREQUENCY_WEIGHT, DEFAULT_FREQUENCY_WEIGHT
                    ),
                    CONF_SEASONAL_WEIGHT: user_input.get(
                        CONF_SEASONAL_WEIGHT, DEFAULT_SEASONAL_WEIGHT
                    ),
                    CONF_SCORE_THRESHOLD: user_input.get(
                        CONF_SCORE_THRESHOLD, DEFAULT_SCORE_THRESHOLD
                    ),
                }

                # Extract selection criteria
                selection_criteria = {
                    CONF_PREFER_GENERIC_PRODUCTS: user_input.get(
                        CONF_PREFER_GENERIC_PRODUCTS, DEFAULT_PREFER_GENERIC_PRODUCTS
                    ),
                    CONF_AUTO_SELECT_FIRST: user_input.get(
                        CONF_AUTO_SELECT_FIRST, DEFAULT_AUTO_SELECT_FIRST
                    ),
                    CONF_SUGGEST_CREATE_ONLY_NO_MATCH: user_input.get(
                        CONF_SUGGEST_CREATE_ONLY_NO_MATCH,
                        DEFAULT_SUGGEST_CREATE_ONLY_NO_MATCH,
                    ),
                }

                analysis_settings = ANALYSIS_SCHEMA(analysis_settings)
                try:
                    selection_criteria = SELECTION_CRITERIA_SCHEMA(selection_criteria)
                except vol.Invalid:
                    self._errors["base"] = "invalid_selection_criteria"

                total_weight = (
                    analysis_settings[CONF_CONSUMPTION_WEIGHT]
                    + analysis_settings[CONF_FREQUENCY_WEIGHT]
                    + analysis_settings[CONF_SEASONAL_WEIGHT]
                )
                if not 0.99 <= total_weight <= 1.01:
                    self._errors["base"] = "weight_sum_error"
            except vol.Invalid:
                self._errors["base"] = "invalid_analysis_settings"

            if not self._errors:
                updated_data = dict(self.options)
                updated_data[CONF_ANALYSIS_SETTINGS] = analysis_settings
                updated_data[CONF_SELECTION_CRITERIA] = selection_criteria

                old_analysis_settings = self.options.get(CONF_ANALYSIS_SETTINGS, {})
                old_selection_criteria = self.options.get(CONF_SELECTION_CRITERIA, {})

                return self.async_create_entry(title="", data=updated_data)

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    # Analysis Settings
                    vol.Required(
                        CONF_SCORE_THRESHOLD,
                        default=current_analysis_settings.get(
                            CONF_SCORE_THRESHOLD, DEFAULT_SCORE_THRESHOLD
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                    vol.Required(
                        CONF_CONSUMPTION_WEIGHT,
                        default=current_analysis_settings.get(
                            CONF_CONSUMPTION_WEIGHT, DEFAULT_CONSUMPTION_WEIGHT
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                    vol.Required(
                        CONF_FREQUENCY_WEIGHT,
                        default=current_analysis_settings.get(
                            CONF_FREQUENCY_WEIGHT, DEFAULT_FREQUENCY_WEIGHT
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                    vol.Required(
                        CONF_SEASONAL_WEIGHT,
                        default=current_analysis_settings.get(
                            CONF_SEASONAL_WEIGHT, DEFAULT_SEASONAL_WEIGHT
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                    # Selection Criteria
                    vol.Optional(
                        CONF_PREFER_GENERIC_PRODUCTS,
                        default=current_selection_criteria.get(
                            CONF_PREFER_GENERIC_PRODUCTS,
                            DEFAULT_PREFER_GENERIC_PRODUCTS,
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_AUTO_SELECT_FIRST,
                        default=current_selection_criteria.get(
                            CONF_AUTO_SELECT_FIRST, DEFAULT_AUTO_SELECT_FIRST
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SUGGEST_CREATE_ONLY_NO_MATCH,
                        default=current_selection_criteria.get(
                            CONF_SUGGEST_CREATE_ONLY_NO_MATCH,
                            DEFAULT_SUGGEST_CREATE_ONLY_NO_MATCH,
                        ),
                    ): bool,
                }
            ),
            errors=self._errors,
            description_placeholders={
                "warning": "⚠️ Analysis settings control how shopping suggestions are calculated. Selection criteria work only with bidirectional sync enabled. All weights must sum to 1.0."
            },
        )


@config_entries.HANDLERS.register(DOMAIN)
class ShoppingListWithGrocyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 10
    DOMAIN = DOMAIN
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        self._errors = {}
        self._data = {"unique_id": str(uuid.uuid4())}

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ):
        return ShoppingListWithGrocyOptionsConfigFlow(config_entry)

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return logging.getLogger(__name__)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            if not is_valid_url(user_input["api_url"]):
                self._errors["base"] = "invalid_api_url"
            elif not is_valid_time_string(
                user_input.get(CONF_IMAGE_REFRESH_TIME, DEFAULT_IMAGE_REFRESH_TIME)
            ):
                self._errors["base"] = "invalid_image_refresh_time"
            if not self._errors:
                self._data.update(user_input)

                return self.async_create_entry(
                    title="Shopping List with Grocy Polling", data=self._data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("api_url"): cv.string,
                    vol.Required("verify_ssl", default=True): cv.boolean,
                    vol.Required("api_key"): cv.string,
                    vol.Optional("disable_timeout", default=False): cv.boolean,
                    vol.Optional(
                        "image_download_size", default=DEFAULT_IMAGE_DOWNLOAD_SIZE
                    ): vol.All(
                        vol.Coerce(int), vol.In(IMAGE_DOWNLOAD_SIZE_OPTIONS)
                    ),
                    vol.Optional(
                        CONF_POLL_INTERVAL_SECONDS,
                        default=DEFAULT_POLL_INTERVAL_SECONDS,
                    ): vol.All(cv.positive_int, vol.Range(min=5, max=86400)),
                    vol.Optional(
                        CONF_REQUEST_SPACING_MS,
                        default=DEFAULT_REQUEST_SPACING_MS,
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=60000)),
                    vol.Optional(
                        CONF_IMAGE_REFRESH_MODE,
                        default=DEFAULT_IMAGE_REFRESH_MODE,
                    ): vol.In(
                        {
                            IMAGE_REFRESH_MODE_INTERVAL: "Interval",
                            IMAGE_REFRESH_MODE_DAILY_TIME: "Daily time",
                        }
                    ),
                    vol.Optional(
                        CONF_IMAGE_REFRESH_INTERVAL_HOURS,
                        default=DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS,
                    ): vol.All(cv.positive_int, vol.Range(min=1, max=168)),
                    vol.Optional(
                        CONF_IMAGE_REFRESH_TIME,
                        default=DEFAULT_IMAGE_REFRESH_TIME,
                    ): cv.string,
                    vol.Optional(
                        CONF_ENABLE_CHORES,
                        default=DEFAULT_ENABLE_CHORES,
                    ): cv.boolean,
                    vol.Optional(
                        CONF_ENABLE_TASKS,
                        default=DEFAULT_ENABLE_TASKS,
                    ): cv.boolean,
                    vol.Optional(
                        CONF_ENABLE_MEAL_PLAN,
                        default=DEFAULT_ENABLE_MEAL_PLAN,
                    ): cv.boolean,
                    vol.Optional(
                        CONF_ENABLE_BATTERIES,
                        default=DEFAULT_ENABLE_BATTERIES,
                    ): cv.boolean,
                    vol.Optional(
                        CONF_REFRESH_AFTER_ADD_PRODUCT,
                        default=DEFAULT_REFRESH_AFTER_ADD_PRODUCT,
                    ): cv.boolean,
                    vol.Optional(
                        CONF_REFRESH_AFTER_REMOVE_PRODUCT,
                        default=DEFAULT_REFRESH_AFTER_REMOVE_PRODUCT,
                    ): cv.boolean,
                }
            ),
            errors=self._errors,
        )


def is_valid_url(url):
    regex = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,}(?:\.[A-Z]{2,})?|"
        r"localhost|"  # localhost
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # IP address
        r"(?::\d+)?"  # Optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )
    return url is not None and regex.search(url)


def is_valid_time_string(value: str | None) -> bool:
    """Return True when the string matches HH:MM."""
    if not value or not isinstance(value, str):
        return False

    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value.strip())
    return match is not None
