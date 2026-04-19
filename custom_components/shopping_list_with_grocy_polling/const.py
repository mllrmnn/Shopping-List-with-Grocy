"""Constants for the Shopping List with Grocy integration."""

DOMAIN = "shopping_list_with_grocy_polling"

ENTITY_VERSION = 2

CONF_POLL_INTERVAL_SECONDS = "poll_interval_seconds"
CONF_REQUEST_SPACING_MS = "request_spacing_ms"
CONF_IMAGE_REFRESH_MODE = "image_refresh_mode"
CONF_IMAGE_REFRESH_INTERVAL_HOURS = "image_refresh_interval_hours"
CONF_IMAGE_REFRESH_TIME = "image_refresh_time"

IMAGE_REFRESH_MODE_INTERVAL = "interval"
IMAGE_REFRESH_MODE_DAILY_TIME = "daily_time"

DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_REQUEST_SPACING_MS = 200
DEFAULT_IMAGE_REFRESH_MODE = IMAGE_REFRESH_MODE_INTERVAL
DEFAULT_IMAGE_REFRESH_INTERVAL_HOURS = 24
DEFAULT_IMAGE_REFRESH_TIME = "03:00"

# Configuration options
CONF_ENABLE_PRODUCT_SENSORS = "enable_product_sensors"

STATE_INIT = "init"
STATE_READY = "ready"
STATE_COMPLETED = "completed"

EVENT_STARTED = "shopping_list_with_grocy_polling_started"
SERVICE_REFRESH = "refresh_products"
SERVICE_SEARCH = "search_products"
SERVICE_ADD = "add_product"
SERVICE_REMOVE = "remove_product"
SERVICE_NOTE = "update_note"
SERVICE_ATTR_PRODUCT_ID = "product_id"
SERVICE_ATTR_SHOPPING_LIST_ID = "shopping_list_id"
SERVICE_ATTR_NOTE = "note"
SERVICE_ATTR_AMOUNT = "amount"

# Selection Criteria Configuration Constants
CONF_SELECTION_CRITERIA = "selection_criteria"
CONF_PREFER_GENERIC_PRODUCTS = "prefer_generic_products"
CONF_AUTO_SELECT_FIRST = "auto_select_first"
CONF_SUGGEST_CREATE_ONLY_NO_MATCH = "suggest_create_only_no_match"

DEFAULT_PREFER_GENERIC_PRODUCTS = False
DEFAULT_AUTO_SELECT_FIRST = False
DEFAULT_SUGGEST_CREATE_ONLY_NO_MATCH = False

OTHER_FIELDS = {
    "qu_id_purchase",
    "qu_id_stock",
    "min_stock_amount",
    "default_best_before_days",
    "default_best_before_days_after_open",
    "default_best_before_days_after_freezing",
    "default_best_before_days_after_thawing",
    "parent_product_id",
    "calories",
    "cumulate_min_stock_amount_of_sub_products",
    "due_type",
    "quick_consume_amount",
    "should_not_be_frozen",
    "treat_opened_as_out_of_stock",
    "no_own_stock",
    "move_on_open",
}
