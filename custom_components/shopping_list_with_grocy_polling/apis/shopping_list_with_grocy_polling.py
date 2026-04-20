import asyncio
import base64
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urlencode

import aiohttp
from async_timeout import timeout
from homeassistant.components.todo import TodoItemStatus
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from ..const import (
    ATTR_BATTERIES,
    ATTR_CHORES,
    ATTR_EXPIRED_PRODUCTS,
    ATTR_EXPIRING_PRODUCTS,
    ATTR_MEAL_PLAN,
    ATTR_MISSING_PRODUCTS,
    ATTR_OVERDUE_BATTERIES,
    ATTR_OVERDUE_CHORES,
    ATTR_OVERDUE_PRODUCTS,
    ATTR_OVERDUE_TASKS,
    ATTR_SHOPPING_LIST,
    ATTR_STOCK,
    ATTR_TASKS,
    CONF_ENABLE_BATTERIES,
    CONF_ENABLE_CHORES,
    CONF_ENABLE_MEAL_PLAN,
    CONF_ENABLE_TASKS,
    CONF_REQUEST_SPACING_MS,
    DEFAULT_IMAGE_DOWNLOAD_SIZE,
    DEFAULT_ENABLE_BATTERIES,
    DEFAULT_ENABLE_CHORES,
    DEFAULT_ENABLE_MEAL_PLAN,
    DEFAULT_ENABLE_TASKS,
    DEFAULT_REQUEST_SPACING_MS,
    DOMAIN,
    ENTITY_VERSION,
    OTHER_FIELDS,
)
from ..frontend_translations import async_load_frontend_translations, get_voice_response
from ..utils import is_update_paused

LOGGER = logging.getLogger(__name__)


class ShoppingListWithGrocyApi:
    def __init__(self, websession: aiohttp.ClientSession, hass: HomeAssistant, config):
        """Initialize the API client."""
        self.hass = hass
        self.config = config
        self.web_session = websession

        self.api_url = (
            config.get("api_url", "").strip() if config.get("api_url") else None
        )
        if not self.api_url:
            raise ValueError("Grocy API URL is required")

        self.verify_ssl = config.get("verify_ssl", True)
        self.api_key = config.get("api_key")
        if not self.api_key:
            raise ValueError("Grocy API key is required")

        self.image_size = config.get("image_download_size", DEFAULT_IMAGE_DOWNLOAD_SIZE)
        self.ha_products = []
        self.final_data = {}
        self.pagination_limit = 40
        self.disable_timeout = config.get("disable_timeout", False)

        self.current_time = datetime.now(timezone.utc)

        self.bidirectional_sync_enabled = config.get("enable_bidirectional_sync", False)
        self.bidirectional_sync_stopped = False

        concurrency = 8 if self.image_size <= 50 else 5 if self.image_size <= 100 else 3
        self._image_fetch_semaphore = asyncio.Semaphore(concurrency)
        self._image_refresh_lock = asyncio.Lock()
        self._request_spacing_seconds = (
            max(
                0,
                int(
                    config.get(
                        CONF_REQUEST_SPACING_MS,
                        DEFAULT_REQUEST_SPACING_MS,
                    )
                ),
            )
            / 1000
        )
        self._request_lock = asyncio.Lock()
        self._last_request_started = 0.0

    async def get_frontend_translation(self, key: str, **kwargs) -> str:
        """Get translation from frontend translation files."""
        try:
            language = self.hass.config.language or "en"
            frontend_translations = await async_load_frontend_translations(
                self.hass, language
            )
            template = get_voice_response(frontend_translations, key)

            if kwargs:
                try:
                    return template.format(**kwargs)
                except (KeyError, ValueError):
                    return template
            return template
        except Exception as e:
            LOGGER.warning("Failed to get frontend translation for '%s': %s", key, e)
            return key

    def get_entity_in_hass(self, entity_id):
        """Retrieve an entity from Home Assistant."""
        entity = self.hass.states.get(entity_id)
        if entity is None:
            LOGGER.debug("Entity %s not found in Home Assistant.", entity_id)
        return entity

    def encode_base64(self, message):
        """Encode a message in Base64 format."""
        if not isinstance(message, str):
            raise TypeError(
                "encode_base64 expects a string, got %s" % type(message).__name__
            )
        return base64.b64encode(message.encode()).decode()

    def serialize_datetime(self, obj):
        """Serialize a datetime or date object to ISO format."""
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(
            "serialize_datetime expects a datetime or date object, got %s"
            % type(obj).__name__
        )

    def build_item_list(self, data) -> list:
        if data is None or "shopping_lists" not in data:
            return []

        shopping_list_map = {}

        for shopping_list in data["shopping_lists"]:
            shopping_list_id = shopping_list["id"]
            shopping_list_map[shopping_list_id] = {
                "id": shopping_list_id,
                "name": shopping_list["name"],
                "products": [],
            }

        for product in data["products"]:
            product_id = int(product["id"])
            qty_factor = (
                float(product["qu_factor_purchase_to_stock"])
                if "qu_factor_purchase_to_stock" in product
                and product["qu_id_purchase"] != product["qu_id_stock"]
                else 1.0
            )

            for in_shopping_list in data["shopping_list"]:
                raw_pid = in_shopping_list.get("product_id")
                if raw_pid is None:
                    continue
                if product_id != int(raw_pid):
                    continue

                shopping_list_id = in_shopping_list["shopping_list_id"]

                if shopping_list_id in shopping_list_map:
                    in_shop_list = str(
                        round(int(in_shopping_list["amount"]) / qty_factor)
                    )
                    shopping_list_map[shopping_list_id]["products"].append(
                        {
                            "name": f"{product['name']} (x{in_shop_list})",
                            "shop_list_id": in_shopping_list["id"],
                            "status": (
                                TodoItemStatus.NEEDS_ACTION
                                if int(in_shopping_list["done"]) == 0
                                else TodoItemStatus.COMPLETED
                            ),
                        }
                    )

        result = list(shopping_list_map.values())

        return result

    async def request(
        self,
        method: str,
        url: str,
        accept: str,
        payload: dict = None,
        *,
        allow_404: bool = False,
        req_timeout: int | None = None,
        log_level: int = logging.ERROR,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        """Make an asynchronous HTTP request."""
        if not self.api_url:
            raise ValueError("Grocy API URL is not configured")
        if not self.api_key:
            raise ValueError("Grocy API key is not configured")

        method = method.upper()
        is_get = method == "GET"

        headers = {
            **kwargs.get("headers", {}),
            "accept": accept,
            "GROCY-API-KEY": self.api_key,
        }

        if is_get:
            headers["cache-control"] = "no-cache"
        else:
            headers["Content-Type"] = "application/json"

        try:
            base_url = self.api_url.rstrip("/") if self.api_url else ""
            full_url = f"{base_url}/{url}"

            # Serialize outbound Grocy requests and add a small gap between them
            # to avoid CPU spikes caused by bursty parallel request waves.
            async with self._request_lock:
                loop = asyncio.get_running_loop()
                now = loop.time()
                wait_time = self._request_spacing_seconds - (
                    now - self._last_request_started
                )
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                self._last_request_started = loop.time()

                if self.disable_timeout or req_timeout is None:
                    # No timeout wrapper
                    response = await self.web_session.request(
                        method,
                        full_url,
                        headers=headers,
                        json=payload if payload and not is_get else None,
                        ssl=self.verify_ssl,
                        **kwargs,
                    )
                else:
                    # Only apply a timeout when explicitly requested
                    async with timeout(req_timeout):
                        response = await self.web_session.request(
                            method,
                            full_url,
                            headers=headers,
                            json=payload if payload and not is_get else None,
                            ssl=self.verify_ssl,
                            **kwargs,
                        )

            if allow_404 and response.status == 404:
                return response

            if response.status >= 400:
                error_text = await response.text()
                LOGGER.error("Grocy API error: %s - %s", response.status, error_text)
                raise aiohttp.ClientError(
                    f"API request failed: {response.status} - {error_text}"
                )

            return response

        except asyncio.TimeoutError as err:
            LOGGER.log(
                log_level,
                "Timeout connecting to Grocy API at %s: %s",
                self.api_url,
                err,
            )
            raise
        except aiohttp.ClientError as err:
            LOGGER.log(
                log_level, "Error connecting to Grocy API at %s: %s", self.api_url, err
            )
            raise

    async def fetch_products(self, path: str, offset: int):
        """Fetch paginated products or other objects."""
        params = {
            "limit": self.pagination_limit,
            "offset": offset,
        }

        if path == "products":
            params["order"] = "name:asc"

        url = f"api/objects/{path}?{urlencode(params)}"

        return await self.request("get", url, "application/json")

    async def fetch_image(self, image_name: str):
        """Fetch an image from the API."""
        url = f"api/files/productpictures/{image_name}?force_serve_as=picture&best_fit_width={self.image_size}"
        return await self.request(
            "get",
            url,
            "application/octet-stream",
            allow_404=True,
            req_timeout=self.compute_timeout(),
            log_level=logging.DEBUG,
        )

    async def fetch_list(self, path: str, max_pages: int = 1000):
        """Retrieves data."""
        data = []
        offset = 0

        while True:
            response = await self.fetch_products(path, offset)

            new_results = await response.json()

            if not new_results:
                break

            data.extend(new_results)

            offset += self.pagination_limit
            if offset // self.pagination_limit >= max_pages:
                break

        return data

    async def fetch_json_endpoint(self, path: str, accept: str = "application/json"):
        """Fetch a non-paginated JSON endpoint."""
        response = await self.request("get", f"api/{path}", accept)
        return await response.json()

    async def remove_product(self, product):
        if product.endswith("))"):
            product = product[:-2]

        async_dispatcher_send(
            self.hass, f"{DOMAIN}_remove_sensor", product.split("_")[-1]
        )

    async def parse_products(self, data):
        self.current_time = datetime.now(timezone.utc)

        entities = set(self.hass.states.async_entity_ids())
        rex = re.compile(
            rf"sensor.shopping_list_with_grocy_polling_product_v{ENTITY_VERSION}_[^|]+"
        )
        self.ha_products = set(rex.findall("|".join(entities)))

        quantity_units = {q["id"]: q["name"] for q in data["quantity_units"]}
        locations = {loc["id"]: loc["name"] for loc in data["locations"]}
        product_groups = {g["id"]: g["name"] for g in data["product_groups"]}

        current_product_ids = {str(product["id"]) for product in data["products"]}

        to_remove = {
            entity
            for entity in self.ha_products
            if entity.split("_")[-1] not in current_product_ids
        }

        if to_remove:
            LOGGER.info("ðŸ—‘ï¸ Delete %d obsolete product(s)", len(to_remove))
            await asyncio.gather(
                *(self.remove_product(product) for product in to_remove)
            )

        self.ha_products -= to_remove

        parsed_products = []
        for product in data["products"]:
            product_id = int(product["id"])

            userfields = product.get("userfields", {})
            qty_factor = (
                float(product.get("qu_factor_purchase_to_stock", 1.0))
                if product.get("qu_id_purchase") != product.get("qu_id_stock")
                else 1.0
            )

            qty_unit_purchase = quantity_units.get(product.get("qu_id_purchase"), "")
            qty_unit_stock = quantity_units.get(product.get("qu_id_stock"), "")

            location = locations.get(product.get("location_id"), "")
            consume_location = locations.get(
                product.get("default_consume_location_id"), ""
            )
            group = product_groups.get(product.get("product_group_id"), "")

            """
            if self.image_size > 0 and product.get("picture_file_name"):
                try:
                    self.hass.async_create_task(
                        self._fetch_and_update_image(product_id, product["picture_file_name"])
                    )
                except Exception:
                    LOGGER.debug("Failed to schedule image fetch for product %s", product_id, exc_info=True)
            """

            shopping_lists = {}
            qty_in_shopping_lists = 0

            for in_shopping_list in data["shopping_list"]:
                if product_id == int(in_shopping_list["product_id"]):
                    shopping_list_id = int(in_shopping_list["shopping_list_id"])
                    in_shop_list = str(
                        round(int(in_shopping_list["amount"]) / qty_factor)
                    )
                    shopping_lists[f"list_{shopping_list_id}"] = {
                        "shop_list_id": in_shopping_list["id"],
                        "qty": int(in_shop_list),
                        "note": in_shopping_list.get("note", ""),
                    }
                    qty_in_shopping_lists += int(in_shop_list)

            stock_qty = sum(
                float(stock["amount"])
                for stock in data["stock"]
                if str(stock["product_id"]) == str(product_id)
            )
            opened_qty = sum(
                float(stock["amount"]) * int(stock["open"])
                for stock in data["stock"]
                if str(stock["product_id"]) == str(product_id)
            )

            unopened_qty = max(0, stock_qty - opened_qty)

            prod_dict = {
                "product_id": product_id,
                "parent_product_id": product.get("parent_product_id"),
                "qty_in_stock": round(stock_qty, 2),
                "qty_opened": round(opened_qty, 2),
                "qty_unopened": round(unopened_qty, 2),
                "qty_unit_purchase": qty_unit_purchase,
                "qty_unit_stock": qty_unit_stock,
                "qu_factor_purchase_to_stock": float(qty_factor),
                "location": location,
                "consume_location": consume_location,
                "group": group,
                "userfields": userfields,
                "list_count": len(shopping_lists),
            }

            for shop_list, details in shopping_lists.items():
                prod_dict.update(
                    {
                        f"{shop_list}_qty": details["qty"],
                        f"{shop_list}_shop_list_id": int(details["shop_list_id"]),
                        f"{shop_list}_note": details["note"],
                    }
                )

            for field in OTHER_FIELDS:
                if field in product:
                    prod_dict[field] = product[field]

            parsed_product = {
                "name": product["name"],
                "product_id": product_id,
                "qty_in_shopping_lists": qty_in_shopping_lists,
                "attributes": prod_dict,
            }
            parsed_products.append(parsed_product)
            async_dispatcher_send(
                self.hass, f"{DOMAIN}_add_or_update_sensor", parsed_product
            )

        parsed_products_dict = {
            str(product["product_id"]): product for product in parsed_products
        }

        return parsed_products_dict

    async def _kick_off_image_fetches(self, data: dict):
        """Backward-compatible wrapper around the explicit image refresh API."""
        await self.refresh_product_images(data)

    async def refresh_product_images(self, data: dict | None = None) -> None:
        """Refresh product images using the configured image schedule."""
        if self.image_size <= 0:
            return

        source = data if data is not None else self.final_data
        if not source or "products" not in source:
            return

        async with self._image_refresh_lock:
            tasks = []
            for product in source["products"]:
                picture = product.get("picture_file_name")
                if not picture:
                    continue

                product_id = int(product["id"])
                tasks.append(self._fetch_and_update_image(product_id, picture))

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_and_update_image(self, product_id: int, picture_file_name: str):
        """Fetch an image in background and dispatch an update for the product sensor."""
        async with self._image_fetch_semaphore:
            try:
                encoded_name = self.encode_base64(picture_file_name)
                response = await self.fetch_image(encoded_name)
                if response is None:
                    LOGGER.debug(
                        "No response while fetching image for product %s", product_id
                    )
                    return
                if response.status == 404:
                    LOGGER.debug(
                        "Product image %s for product %s does not exist anymore",
                        picture_file_name,
                        product_id,
                    )
                    return

                picture_bytes = await response.read()
                picture = base64.b64encode(picture_bytes).decode("utf-8")

                data_uri = f"data:image/png;base64,{picture}"

                try:
                    if self.final_data and isinstance(self.final_data, dict):
                        hap = self.final_data.get("homeassistant_products")
                        if isinstance(hap, dict):
                            key = str(product_id)
                            if key in hap and "attributes" in hap[key]:
                                hap[key]["attributes"].pop("product_image", None)
                                hap[key]["attributes"]["entity_picture"] = data_uri
                except Exception:
                    LOGGER.debug(
                        "Failed to persist background image into final_data for product %s",
                        product_id,
                        exc_info=True,
                    )

                async_dispatcher_send(
                    self.hass,
                    f"{DOMAIN}_add_or_update_sensor",
                    {
                        "product_id": product_id,
                        "attributes": {
                            "entity_picture": data_uri,
                        },
                        "attributes_to_remove": ["product_image"],
                    },
                )

            except Exception as e:
                LOGGER.debug("Failed to fetch image for product %s: %s", product_id, e)

    async def update_grocy_shoppinglist_product(self, product_id: int, done: bool):
        """Mark a product as done or not in the shopping list."""
        return await self.request(
            "put",
            f"api/objects/shopping_list/{product_id}",
            "*/*",
            {"done": done},
        )

    async def remove_product_from_shopping_list(self, product_id: int):
        """Remove a product from the shopping list."""
        return await self.request(
            "delete",
            f"api/objects/shopping_list/{product_id}",
            "*/*",
            {},
        )

    async def update_grocy_product(
        self,
        product_id,
        qu_factor_purchase_to_stock,
        shopping_list_id,
        product_note,
        remove_product=False,
        quantity=1,
    ):
        """Update or remove a product from the shopping list."""
        endpoint = "remove-product" if remove_product else "add-product"

        grocy_quantity = quantity * float(qu_factor_purchase_to_stock)

        payload = {
            "product_id": int(product_id),
            "list_id": shopping_list_id,
            "product_amount": grocy_quantity,
        }

        if not remove_product:
            payload["note"] = product_note

        return await self.request(
            "post",
            f"api/stock/shoppinglist/{endpoint}",
            "*/*",
            payload,
        )

    async def manage_product(
        self, product_id, shopping_list_id=1, note="", remove_product=False, quantity=1
    ):
        """Add or remove a product from the shopping list."""
        entity = self.get_entity_in_hass(product_id)
        if entity is None:
            return

        state_value = entity.state
        if not state_value.isdigit():
            state_value = "0"

        attributes = entity.attributes.copy()
        if "product_id" in attributes:
            change = -quantity if remove_product else quantity
            total_qty = max(0, int(state_value) + change)
            qty = max(
                0,
                int(attributes.get(f"list_{shopping_list_id}_qty", 0)) + change,
            )
            list_count = max(
                0, attributes.get("list_count", 0) + (1 if not remove_product else -1)
            )

            await self.update_grocy_product(
                attributes.get("product_id"),
                attributes.get("qu_factor_purchase_to_stock", 1),
                str(shopping_list_id),
                note,
                remove_product,
                quantity,
            )

            if qty > 0:
                attributes_to_remove = []
                attributes.update(
                    {
                        "qty_in_shopping_lists": total_qty,
                        f"list_{shopping_list_id}_qty": qty,
                        f"list_{shopping_list_id}_note": note,
                        "list_count": list_count,
                    }
                )
            else:
                attributes_to_remove = [
                    f"list_{shopping_list_id}_qty",
                    f"list_{shopping_list_id}_note",
                    f"list_{shopping_list_id}_shop_list_id",
                ]
                attributes["qty_in_shopping_lists"] = total_qty
                attributes["list_count"] = list_count

            payload = {
                "product_id": attributes.get("product_id"),
                "qty_in_shopping_lists": total_qty,
                "attributes": attributes,
                "attributes_to_remove": attributes_to_remove,
            }

            async_dispatcher_send(
                self.hass,
                f"{DOMAIN}_add_or_update_sensor",
                payload,
            )

            return attributes.get("product_id")

    def _build_updated_product_payload(self, product_id: int) -> dict | None:
        """Rebuild shopping-list-specific product attributes from cached base data."""
        product_key = str(product_id)
        cached_product = (self.final_data.get("homeassistant_products") or {}).get(
            product_key
        )
        if not cached_product:
            return None

        product_meta = next(
            (
                product
                for product in self.final_data.get("products", [])
                if int(product.get("id")) == int(product_id)
            ),
            None,
        )
        if not product_meta:
            return None

        qty_factor = (
            float(product_meta.get("qu_factor_purchase_to_stock", 1.0))
            if product_meta.get("qu_id_purchase") != product_meta.get("qu_id_stock")
            else 1.0
        )

        base_attributes = {
            key: value
            for key, value in cached_product.get("attributes", {}).items()
            if not key.startswith("list_")
        }

        shopping_entries = [
            item
            for item in self.final_data.get("shopping_list", [])
            if str(item.get("product_id")) == product_key
        ]

        total_qty = 0
        for item in shopping_entries:
            shopping_list_id = int(item["shopping_list_id"])
            in_shop_list = int(round(int(item.get("amount", 0)) / qty_factor))
            total_qty += in_shop_list
            base_attributes[f"list_{shopping_list_id}_qty"] = in_shop_list
            base_attributes[f"list_{shopping_list_id}_note"] = item.get("note", "")
            base_attributes[f"list_{shopping_list_id}_shop_list_id"] = int(item["id"])

        base_attributes["qty_in_shopping_lists"] = total_qty
        base_attributes["list_count"] = len(shopping_entries)

        return {
            "name": cached_product.get(
                "name", product_meta.get("name", "Unknown Product")
            ),
            "product_id": int(product_id),
            "qty_in_shopping_lists": total_qty,
            "attributes": base_attributes,
        }

    async def refresh_after_action(self, affected_product_ids: set[int]) -> None:
        """Refresh only shopping list data plus the affected product entities."""
        if not self.final_data:
            await self.retrieve_data(force=True)
            return

        self.final_data["shopping_list"] = await self.fetch_list("shopping_list")
        self.final_data["shopping_lists_data"] = self.build_item_list(self.final_data)
        self.final_data[ATTR_SHOPPING_LIST] = self._build_shopping_list_products_summary(
            self.final_data
        )

        homeassistant_products = self.final_data.setdefault("homeassistant_products", {})

        for product_id in affected_product_ids:
            payload = self._build_updated_product_payload(int(product_id))
            if payload is None:
                continue
            homeassistant_products[str(product_id)] = payload
            async_dispatcher_send(
                self.hass,
                f"{DOMAIN}_add_or_update_sensor",
                payload,
            )

    async def update_note(self, product_id, shopping_list_id, note):
        """Update a note on a product in the shopping list."""
        entity = self.get_entity_in_hass(product_id)
        if entity is None:
            return

        payload = {
            "product_id": entity.attributes.get("product_id"),
            "shopping_list_id": shopping_list_id,
            "amount": entity.attributes.get(f"list_{shopping_list_id}_qty", 0),
            "note": note,
        }

        await self.request(
            "put",
            f"api/objects/shopping_list/{entity.attributes.get(f'list_{shopping_list_id}_shop_list_id')}",
            "*/*",
            payload,
        )

        entity_attributes = entity.attributes.copy()
        entity_attributes[f"list_{shopping_list_id}_note"] = note

        async_dispatcher_send(
            self.hass,
            "shopping_list_with_grocy_polling_add_or_update_sensor",
            {
                "product_id": entity.attributes.get("product_id"),
                "qty_in_shopping_lists": entity.state,
                "attributes": entity_attributes,
            },
        )

    def normalize_text_for_search(self, text: str) -> str:
        """Normalize text for search by removing accents and converting to lowercase."""
        if not text:
            return ""

        normalized = unicodedata.normalize("NFD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")

        return ascii_text.lower().strip()

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts using SequenceMatcher."""
        normalized1 = self.normalize_text_for_search(text1)
        normalized2 = self.normalize_text_for_search(text2)

        if not normalized1 or not normalized2:
            return 0.0

        return SequenceMatcher(None, normalized1, normalized2).ratio()

    def find_similar_products(self, search_name: str, threshold: float = 0.6) -> list:
        """Find products similar to the search term using fuzzy matching."""
        if not search_name or not self.final_data or "products" not in self.final_data:
            return []

        similar_products = []
        products = self.final_data["products"]

        for product in products:
            product_name = product.get("name", "")
            similarity = self.calculate_similarity(search_name, product_name)

            if similarity >= threshold:
                similar_products.append(
                    {
                        "id": product["id"],
                        "name": product_name,
                        "similarity": similarity,
                    }
                )

        similar_products.sort(key=lambda x: x["similarity"], reverse=True)

        return similar_products[:10]

    def is_case_only_difference(self, search_name: str, product_name: str) -> bool:
        """Check if two strings differ only by case (uppercase/lowercase)."""
        return (
            search_name.lower() == product_name.lower() and search_name != product_name
        )

    def extract_product_name_from_ha_item(self, item_name: str) -> tuple[str, int]:
        """Extract product name and quantity from Home Assistant item name."""
        item_name = item_name.strip()

        pattern1 = r"^(.+?)\s*\([xÃ—](\d+)\)\s*$"
        match1 = re.match(pattern1, item_name)
        if match1:
            product_name = match1.group(1).strip()
            quantity = int(match1.group(2))
            LOGGER.error(
                "Extracted from HA item '%s' (pattern 1): name='%s', qty=%d",
                item_name,
                product_name,
                quantity,
            )
            return product_name, quantity

        pattern2 = r"^(\d+)\s+(.+)$"
        match2 = re.match(pattern2, item_name)
        if match2:
            quantity = int(match2.group(1))
            product_name = match2.group(2).strip()
            LOGGER.error(
                "Extracted from HA item '%s' (pattern 2): name='%s', qty=%d",
                item_name,
                product_name,
                quantity,
            )
            return product_name, quantity

        LOGGER.error(
            "No pattern matched for HA item '%s': name='%s', qty=1",
            item_name,
            item_name,
        )
        return item_name, 1

    def apply_selection_criteria(self, matches: list, selection_criteria: dict) -> list:
        """Apply selection criteria to filter matches."""
        if not matches or not selection_criteria:
            return matches

        # Get configuration values
        prefer_generic = selection_criteria.get("prefer_generic_products", False)
        auto_select_first = selection_criteria.get("auto_select_first", False)

        # First criterion: prefer generic products (products without parent)
        if prefer_generic:
            generic_products = [
                match for match in matches if not match.get("parent_product_id")
            ]
            if generic_products:
                matches = generic_products
                LOGGER.debug(
                    "Applied 'prefer generic products' filter: %d generic products found",
                    len(generic_products),
                )

        # Second criterion: auto-select first if enabled and only one match remains
        if auto_select_first and len(matches) == 1:
            LOGGER.debug("Auto-selecting first product: %s", matches[0].get("name"))
            return matches

        # If auto_select_first is enabled but multiple matches remain, select the first one
        if auto_select_first and len(matches) > 1:
            selected_match = matches[0]
            LOGGER.debug(
                "Auto-selecting first product from multiple matches: %s",
                selected_match.get("name"),
            )
            return [selected_match]

        return matches

    async def search_product_in_grocy(self, search_name: str) -> dict:
        """Search for a product in Grocy by name with exact, contains, and fuzzy matching."""
        if not search_name:
            return {"found": False, "matches": [], "search_type": "none"}

        if not self.final_data or "products" not in self.final_data:
            LOGGER.error("No product data available for search")
            return {"found": False, "matches": [], "search_type": "no_data"}

        products = self.final_data["products"]
        normalized_search = self.normalize_text_for_search(search_name)

        case_only_matches = []
        for product in products:
            product_name = product.get("name", "")
            if self.is_case_only_difference(search_name, product_name):
                case_only_matches.append(product)
                LOGGER.debug(
                    "Case-only match found: '%s' -> '%s' (ID: %s)",
                    search_name,
                    product_name,
                    product.get("id"),
                )

        if case_only_matches:
            return {
                "found": True,
                "matches": case_only_matches,
                "search_type": "case_only",
                "search_term": search_name,
            }

        exact_matches = []
        for product in products:
            product_name = product.get("name", "")
            normalized_product = self.normalize_text_for_search(product_name)

            if normalized_product == normalized_search:
                exact_matches.append(product)

        if exact_matches:
            return {
                "found": True,
                "matches": exact_matches,
                "search_type": "exact",
                "search_term": search_name,
            }

        contains_matches = []
        for product in products:
            product_name = product.get("name", "")
            normalized_product = self.normalize_text_for_search(product_name)

            if normalized_search in normalized_product:
                contains_matches.append(product)

        if contains_matches:
            return {
                "found": True,
                "matches": contains_matches,
                "search_type": "contains",
                "search_term": search_name,
            }

        LOGGER.debug("No exact/contains matches, trying fuzzy search...")
        similar_products = self.find_similar_products(search_name, threshold=0.6)

        if similar_products:
            LOGGER.debug(
                "Found %d similar products with fuzzy matching:",
                len(similar_products),
            )

            return {
                "found": True,
                "matches": similar_products,
                "search_type": "fuzzy",
                "search_term": search_name,
            }

        LOGGER.error("No matches found for '%s' (including fuzzy search)", search_name)
        return {
            "found": False,
            "matches": [],
            "search_type": "not_found",
            "search_term": search_name,
        }

    async def create_product_in_grocy(self, product_name: str) -> dict:
        """Create a new product in Grocy with default parameters."""
        if not product_name:
            raise ValueError("Product name is required")

        formatted_name = product_name.strip()
        if formatted_name:
            formatted_name = formatted_name[0].upper() + formatted_name[1:]

        LOGGER.debug("Creating new product in Grocy: '%s'", formatted_name)

        default_location_id = None
        default_qu_id = None

        if self.final_data:
            if "locations" in self.final_data and self.final_data["locations"]:
                default_location_id = self.final_data["locations"][0].get("id")
                LOGGER.debug("Using default location ID: %s", default_location_id)

            if (
                "quantity_units" in self.final_data
                and self.final_data["quantity_units"]
            ):
                default_qu_id = self.final_data["quantity_units"][0].get("id")
                LOGGER.debug("Using default quantity unit ID: %s", default_qu_id)

        if not default_location_id or not default_qu_id:
            raise ValueError(
                "Unable to get default location or quantity unit from Grocy"
            )

        payload = {
            "name": formatted_name,
            "location_id": default_location_id,
            "qu_id_stock": default_qu_id,
            "qu_id_purchase": default_qu_id,
            "qu_id_consume": default_qu_id,
            "qu_id_price": default_qu_id,
        }

        try:
            response = await self.request(
                "post",
                "api/objects/products",
                "application/json",
                payload,
            )

            result = await response.json()
            product_id = result.get("created_object_id")

            LOGGER.debug(
                "Product created successfully: '%s' with ID %s",
                formatted_name,
                product_id,
            )

            voice_mode = self.hass.data.get(DOMAIN, {}).get("voice_mode", False)
            if not voice_mode:
                title = await self.get_frontend_translation(
                    "product_created_notification_title"
                )
                message = await self.get_frontend_translation(
                    "product_created_notification_message",
                    product_name=formatted_name,
                    product_id=product_id,
                )

                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": title,
                        "message": message,
                        "notification_id": f"grocy_product_created_{product_id}",
                    },
                )

            return {
                "success": True,
                "product_id": product_id,
                "product_name": formatted_name,
            }

        except Exception as e:
            LOGGER.error("Failed to create product '%s': %s", formatted_name, e)
            raise

    async def add_product_to_grocy_shopping_list(
        self,
        product_id: int,
        quantity: int = 1,
        shopping_list_id: int = 1,
        note: str = "",
    ):
        """Add a product to Grocy shopping list or increment existing quantity."""
        try:
            existing_entry = None
            if self.final_data and "shopping_list" in self.final_data:
                for item in self.final_data["shopping_list"]:
                    if int(item["product_id"]) == int(product_id) and int(
                        item["shopping_list_id"]
                    ) == int(shopping_list_id):
                        existing_entry = item
                        break

            if existing_entry:
                new_amount = int(existing_entry["amount"]) + quantity

                payload = {
                    "product_id": int(product_id),
                    "shopping_list_id": int(shopping_list_id),
                    "amount": new_amount,
                    "note": note or existing_entry.get("note", ""),
                }

                await self.request(
                    "put",
                    f"api/objects/shopping_list/{existing_entry['id']}",
                    "*/*",
                    payload,
                )

            else:
                payload = {
                    "product_id": int(product_id),
                    "list_id": shopping_list_id,
                    "product_amount": quantity,
                    "note": note,
                }

                await self.request(
                    "post",
                    "api/stock/shoppinglist/add-product",
                    "*/*",
                    payload,
                )

            return True

        except Exception as e:
            LOGGER.error("Failed to add product to Grocy shopping list: %s", e)
            raise

    async def handle_ha_todo_item_creation(
        self,
        item_summary: str,
        shopping_list_id: int = 1,
        selection_criteria: dict | None = None,
    ) -> dict:
        """Handle creation of a todo item from Home Assistant."""
        # Step 1: Perform initial checks
        if not self.bidirectional_sync_enabled or self.bidirectional_sync_stopped:
            LOGGER.error("Bidirectional sync is disabled or stopped")
            return {"success": False, "reason": "sync_disabled"}

        if not self.final_data:
            LOGGER.error("âš ï¸ No data available, refreshing...")
            await self.retrieve_data(force=True)
            if not self.final_data:
                LOGGER.error("Still no data after refresh, stopping for safety")
                self.stop_bidirectional_sync("No data available after refresh")
                return {"success": False, "reason": "no_data_safety_stop"}

        try:
            product_name, quantity = self.extract_product_name_from_ha_item(
                item_summary
            )
            LOGGER.debug(
                "Processing: item_summary='%s' -> product_name='%s', quantity=%d",
                item_summary,
                product_name,
                quantity,
            )

            if not product_name:
                LOGGER.error("Empty product name extracted from '%s'", item_summary)
                return {"success": False, "reason": "empty_name"}

            # Step 2: Search products in Grocy
            search_result = await self.search_product_in_grocy(product_name)
            matches = search_result.get("matches", [])

            # Step 3: Apply selection criteria to filter matches
            if selection_criteria and matches:
                original_count = len(matches)
                matches = self.apply_selection_criteria(matches, selection_criteria)
                if len(matches) != original_count:
                    LOGGER.debug(
                        "Selection criteria applied: %d -> %d matches",
                        original_count,
                        len(matches),
                    )

            # Step 4: Add create option if applicable
            final_options = await self._prepare_final_options(
                matches,
                product_name,
                selection_criteria,
                search_result.get("search_type", "unknown"),
            )

            # Step 5: Execute appropriate action
            return await self._execute_action(
                final_options,
                product_name,
                quantity,
                shopping_list_id,
                search_result.get("search_type", "unknown"),
            )

        except Exception as e:
            LOGGER.error("Error handling HA todo item creation: %s", e)
            return {"success": False, "reason": "error", "error": str(e)}

    async def _prepare_final_options(
        self,
        matches: list,
        product_name: str,
        selection_criteria: dict | None,
        search_type: str | None,
    ) -> list:
        """Prepare the final list of options including create option if needed."""
        final_options = matches.copy()

        # Determine if we should add create option
        should_add_create = True
        if selection_criteria:
            suggest_create_only_no_match = selection_criteria.get(
                "suggest_create_only_no_match", False
            )
            # Don't add create option if we have matches and the criterion is enabled
            if suggest_create_only_no_match and matches:
                should_add_create = False
                LOGGER.debug(
                    "Skipped create option for %d matches (suggest_create_only_no_match=True)",
                    len(matches),
                )

        # Add create option if needed
        if should_add_create:
            create_option_text = await self.get_frontend_translation(
                "create_new_product", product_name=product_name
            )
            final_options.append(
                {
                    "id": "create_new",
                    "name": create_option_text,
                    "similarity": 0.0,
                    "is_create_option": True,
                }
            )
            if matches:  # Only log if we had matches
                LOGGER.debug(
                    "Added create option to %d matches (suggest_create_only_no_match=False)",
                    len(matches),
                )

        return final_options

    async def _execute_action(
        self,
        final_options: list,
        product_name: str,
        quantity: int,
        shopping_list_id: int,
        search_type: str | None,
    ) -> dict:
        """Execute the appropriate action based on the final options."""
        # Auto-add logic for special cases
        if self._should_auto_add(final_options, product_name, search_type):
            return await self._auto_add_product(
                final_options[0], product_name, quantity, shopping_list_id
            )

        # Auto-select if only one non-create option remains
        if len(final_options) == 1 and not final_options[0].get(
            "is_create_option", False
        ):
            return await self._auto_select_product(
                final_options[0], product_name, quantity, shopping_list_id
            )

        # Return multiple options for user selection
        return {
            "success": False,
            "reason": "multiple_matches",
            "matches": final_options,
            "search_term": product_name,
            "quantity": quantity,
            "shopping_list_id": shopping_list_id,
        }

    def _should_auto_add(
        self, final_options: list, product_name: str, search_type: str | None
    ) -> bool:
        """Determine if we should auto-add the product without user intervention."""
        if not final_options or final_options[0].get("is_create_option", False):
            return False

        return (
            search_type == "case_only"
            or (
                search_type == "exact"
                and len(
                    [
                        opt
                        for opt in final_options
                        if not opt.get("is_create_option", False)
                    ]
                )
                == 1
            )
            or (
                len(
                    [
                        opt
                        for opt in final_options
                        if not opt.get("is_create_option", False)
                    ]
                )
                == 1
                and self.is_case_only_difference(product_name, final_options[0]["name"])
            )
        )

    async def _auto_add_product(
        self, product: dict, original_search: str, quantity: int, shopping_list_id: int
    ) -> dict:
        """Auto-add a product that matches special criteria."""
        LOGGER.debug(
            "Auto-adding product: %s (ID: %s)", product.get("name"), product.get("id")
        )

        add_result = await self.add_product_to_grocy_shopping_list(
            product["id"], quantity, shopping_list_id
        )

        if add_result:
            return {
                "success": True,
                "reason": "auto_added_case_match",
                "product_name": product["name"],
                "product_id": product["id"],
                "quantity": quantity,
                "original_search": original_search,
            }
        else:
            return {
                "success": False,
                "reason": "auto_add_failed",
                "error": "Failed to add product to shopping list",
            }

    async def _auto_select_product(
        self, product: dict, original_search: str, quantity: int, shopping_list_id: int
    ) -> dict:
        """Auto-select a product when it's the only option after filtering."""
        LOGGER.debug(
            "Auto-selecting single remaining product after filtering: %s (ID: %s)",
            product.get("name"),
            product.get("id"),
        )

        add_result = await self.add_product_to_grocy_shopping_list(
            product["id"], quantity, shopping_list_id
        )

        if add_result:
            return {
                "success": True,
                "reason": "auto_selected_after_filtering",
                "product_name": product["name"],
                "product_id": product["id"],
                "quantity": quantity,
                "original_search": original_search,
            }
        else:
            return {
                "success": False,
                "reason": "auto_select_failed_after_filtering",
                "error": "Failed to add filtered product to shopping list",
            }

    def stop_bidirectional_sync(self, reason: str = "manual"):
        """Emergency stop for bidirectional sync."""
        self.bidirectional_sync_stopped = True
        LOGGER.error(
            "ðŸ›‘ EMERGENCY STOP: Bidirectional sync has been stopped. Reason: %s", reason
        )

        self.hass.async_create_task(
            self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "âš ï¸ Shopping List Sync Stopped",
                    "message": f"Bidirectional sync has been emergency stopped due to: {reason}. Use the restart service to re-enable.",
                    "notification_id": "grocy_sync_emergency_stop",
                },
            )
        )

    def restart_bidirectional_sync(self):
        """Restart bidirectional sync after emergency stop."""
        self.bidirectional_sync_stopped = False
        LOGGER.error("ðŸ”„ Bidirectional sync has been restarted")

        self.hass.async_create_task(
            self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": "grocy_sync_emergency_stop"},
            )
        )

    def compute_timeout(self) -> int:
        table = {0: 60, 10: 60, 25: 60, 50: 60, 100: 90, 150: 120, 200: 180}
        if self.image_size in table:
            return table[self.image_size]
        nearest = min(table.keys(), key=lambda k: abs(k - int(self.image_size or 0)))
        return table[nearest]

    async def update_refreshing_status(self, refreshing):
        domain_data = self.hass.data.get(DOMAIN)
        if not isinstance(domain_data, dict):
            return False

        entity = (domain_data.get("entities") or {}).get(
            "updating_shopping_list_with_grocy_polling"
        )

        if entity is None:
            return False

        await entity.update_state(refreshing)
        return True

    def _parse_datetime(self, value: str | None) -> datetime | None:
        """Parse Grocy datetime strings into timezone-aware datetimes when possible."""
        if not value:
            return None

        raw = str(value).strip()
        if not raw:
            return None

        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    parsed = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    parsed = None
            if parsed is None:
                return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _parse_date(self, value: str | None) -> date | None:
        """Parse Grocy date strings."""
        if not value:
            return None
        try:
            return date.fromisoformat(str(value).strip()[:10])
        except ValueError:
            return None

    def _build_stock_products_summary(self, data: dict) -> list[dict]:
        """Build stock products summary similar to the standalone Grocy integration."""
        products_by_id = {str(product["id"]): product for product in data.get("products", [])}
        stock_by_product: dict[str, list[dict]] = {}
        for item in data.get("stock", []):
            stock_by_product.setdefault(str(item.get("product_id")), []).append(item)

        result: list[dict] = []
        for product_id, stock_items in stock_by_product.items():
            product = products_by_id.get(product_id)
            if not product:
                continue

            total_amount = sum(float(item.get("amount", 0) or 0) for item in stock_items)
            opened_amount = sum(
                float(item.get("amount", 0) or 0) * int(item.get("open", 0) or 0)
                for item in stock_items
            )
            result.append(
                {
                    "id": int(product_id),
                    "product_id": int(product_id),
                    "name": product.get("name"),
                    "amount": round(total_amount, 2),
                    "opened_amount": round(opened_amount, 2),
                    "unopened_amount": round(max(0.0, total_amount - opened_amount), 2),
                    "min_stock_amount": product.get("min_stock_amount"),
                    "best_before_date": min(
                        (
                            item.get("best_before_date")
                            for item in stock_items
                            if item.get("best_before_date")
                        ),
                        default=None,
                    ),
                    "location_id": product.get("location_id"),
                    "picture_file_name": product.get("picture_file_name"),
                    "picture_url": (
                        f"/api/grocy/productpictures/{self.encode_base64(product['picture_file_name'])}"
                        if product.get("picture_file_name")
                        else None
                    ),
                    "product": product,
                    "stock_entries": stock_items,
                }
            )

        return sorted(result, key=lambda item: (item.get("name") or "").lower())

    def _build_shopping_list_products_summary(self, data: dict) -> list[dict]:
        """Build shopping list details with product names and shopping list names."""
        products_by_id = {str(product["id"]): product for product in data.get("products", [])}
        shopping_lists_by_id = {
            str(item["id"]): item for item in data.get("shopping_lists", [])
        }

        result: list[dict] = []
        for item in data.get("shopping_list", []):
            product = products_by_id.get(str(item.get("product_id")), {})
            shopping_list = shopping_lists_by_id.get(str(item.get("shopping_list_id")), {})
            result.append(
                {
                    **item,
                    "product_name": product.get("name"),
                    "shopping_list_name": shopping_list.get("name"),
                    "product": product,
                    "shopping_list": shopping_list,
                    "picture_url": (
                        f"/api/grocy/productpictures/{self.encode_base64(product['picture_file_name'])}"
                        if product.get("picture_file_name")
                        else None
                    ),
                }
            )

        return result

    def _build_overdue_chores(self, chores: list[dict]) -> list[dict]:
        now = datetime.now(timezone.utc)
        return [
            chore
            for chore in chores
            if (next_execution := self._parse_datetime(chore.get("next_estimated_execution_time")))
            and next_execution < now
        ]

    def _build_overdue_tasks(self, tasks: list[dict]) -> list[dict]:
        today = datetime.now(timezone.utc).date()
        return [
            task
            for task in tasks
            if (due_date := self._parse_date(task.get("due_date"))) and due_date < today
        ]

    def _build_overdue_batteries(self, batteries: list[dict]) -> list[dict]:
        now = datetime.now(timezone.utc)
        return [
            battery
            for battery in batteries
            if (charge_time := self._parse_datetime(battery.get("next_estimated_charge_time")))
            and charge_time < now
        ]

    def _build_meal_plan_summary(self, meal_plan: list[dict]) -> list[dict]:
        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        filtered = [
            item
            for item in meal_plan
            if (meal_day := self._parse_date(item.get("day"))) and meal_day > yesterday
        ]
        return sorted(filtered, key=lambda item: (item.get("day") or "", item.get("id") or 0))

    def _build_quantity_unit_lookup(self, data: dict) -> dict[int, dict]:
        """Map quantity unit ids to a compact unit payload."""
        units: dict[int, dict] = {}
        for unit in data.get("quantity_units", []) or []:
            unit_id = unit.get("id")
            if unit_id is None:
                continue

            name = unit.get("name") or ""
            name_plural = unit.get("name_plural") or name
            units[int(unit_id)] = {
                "id": int(unit_id),
                "name": name,
                "name_plural": name_plural,
            }

        return units

    def _enrich_volatile_product_entries(
        self, entries: list[dict], data: dict
    ) -> list[dict]:
        """Backfill product metadata expected by Grocy-compatible templates."""
        if not entries:
            return []

        products_by_id = {
            int(product["id"]): product
            for product in data.get("products", []) or []
            if product.get("id") is not None
        }
        quantity_units = self._build_quantity_unit_lookup(data)

        enriched_entries: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                enriched_entries.append(entry)
                continue

            enriched = dict(entry)
            raw_product_id = (
                entry.get("product_id")
                if entry.get("product_id") is not None
                else entry.get("id")
            )

            try:
                product_id = int(raw_product_id)
            except (TypeError, ValueError):
                enriched_entries.append(enriched)
                continue

            product = products_by_id.get(product_id, {})
            purchase_unit = quantity_units.get(
                int(product.get("qu_id_purchase"))
            ) if product.get("qu_id_purchase") is not None else None
            stock_unit = quantity_units.get(
                int(product.get("qu_id_stock"))
            ) if product.get("qu_id_stock") is not None else None

            if purchase_unit and "default_quantity_unit_purchase" not in enriched:
                enriched["default_quantity_unit_purchase"] = purchase_unit
            if stock_unit and "default_quantity_unit_stock" not in enriched:
                enriched["default_quantity_unit_stock"] = stock_unit
            if product and "product" not in enriched:
                enriched["product"] = {
                    "id": product_id,
                    "name": product.get("name"),
                }

            enriched_entries.append(enriched)

        return enriched_entries

    def _add_grocy_aggregate_entities(self, data: dict) -> None:
        """Populate Grocy-style aggregate entity datasets from fetched data."""
        volatile_stock = data.get("volatile_stock", {}) or {}
        chores_enabled = self.config.get(CONF_ENABLE_CHORES, DEFAULT_ENABLE_CHORES)
        tasks_enabled = self.config.get(CONF_ENABLE_TASKS, DEFAULT_ENABLE_TASKS)
        meal_plan_enabled = self.config.get(
            CONF_ENABLE_MEAL_PLAN, DEFAULT_ENABLE_MEAL_PLAN
        )
        batteries_enabled = self.config.get(
            CONF_ENABLE_BATTERIES, DEFAULT_ENABLE_BATTERIES
        )

        data[ATTR_CHORES] = (data.get("chores", []) or []) if chores_enabled else []
        data[ATTR_TASKS] = (data.get("tasks", []) or []) if tasks_enabled else []
        data[ATTR_BATTERIES] = (
            (data.get("batteries", []) or []) if batteries_enabled else []
        )
        data[ATTR_MEAL_PLAN] = (
            self._build_meal_plan_summary(data.get("meal_plan", []) or [])
            if meal_plan_enabled
            else []
        )
        data[ATTR_SHOPPING_LIST] = self._build_shopping_list_products_summary(data)
        data[ATTR_STOCK] = self._build_stock_products_summary(data)
        data[ATTR_EXPIRING_PRODUCTS] = self._enrich_volatile_product_entries(
            volatile_stock.get("due_products", []) or [],
            data,
        )
        data[ATTR_EXPIRED_PRODUCTS] = self._enrich_volatile_product_entries(
            volatile_stock.get("expired_products", []) or [],
            data,
        )
        data[ATTR_OVERDUE_PRODUCTS] = self._enrich_volatile_product_entries(
            volatile_stock.get("overdue_products", []) or [],
            data,
        )
        data[ATTR_MISSING_PRODUCTS] = self._enrich_volatile_product_entries(
            volatile_stock.get("missing_products", []) or [],
            data,
        )
        data[ATTR_OVERDUE_CHORES] = (
            self._build_overdue_chores(data[ATTR_CHORES]) if chores_enabled else []
        )
        data[ATTR_OVERDUE_TASKS] = (
            self._build_overdue_tasks(data[ATTR_TASKS]) if tasks_enabled else []
        )
        data[ATTR_OVERDUE_BATTERIES] = (
            self._build_overdue_batteries(data[ATTR_BATTERIES])
            if batteries_enabled
            else []
        )

    async def retrieve_data(self, force=False):
        """Retrieves data and updates if necessary."""
        try:
            paused = is_update_paused(self.hass)
            should_update = force or not paused

            if should_update:
                await self.update_refreshing_status(True)
                titles = [
                    "products",
                    "shopping_lists",
                    "shopping_list",
                    "locations",
                    "stock",
                    "product_groups",
                    "quantity_units",
                ]
                if self.config.get(CONF_ENABLE_CHORES, DEFAULT_ENABLE_CHORES):
                    titles.append("chores")
                if self.config.get(CONF_ENABLE_TASKS, DEFAULT_ENABLE_TASKS):
                    titles.append("tasks")
                if self.config.get(CONF_ENABLE_BATTERIES, DEFAULT_ENABLE_BATTERIES):
                    titles.append("batteries")
                if self.config.get(CONF_ENABLE_MEAL_PLAN, DEFAULT_ENABLE_MEAL_PLAN):
                    titles.append("meal_plan")

                t = self.compute_timeout()

                if self.disable_timeout:
                    results = await asyncio.gather(
                        *(self.fetch_list(path) for path in titles),
                        self.fetch_json_endpoint("stock/volatile"),
                        return_exceptions=True,
                    )
                else:
                    async with timeout(t):
                        results = await asyncio.gather(
                            *(self.fetch_list(path) for path in titles),
                            self.fetch_json_endpoint("stock/volatile"),
                            return_exceptions=True,
                        )

                for idx, r in enumerate(results):
                    label = titles[idx] if idx < len(titles) else "volatile_stock"
                    if isinstance(r, Exception):
                        LOGGER.warning("Fetch %s failed: %s", label, r)

                base_results = results[: len(titles)]
                volatile_stock = results[len(titles)]
                if isinstance(volatile_stock, Exception):
                    LOGGER.warning("Fetch volatile_stock failed: %s", volatile_stock)
                    volatile_stock = {}

                self.final_data = dict(zip(titles, base_results))
                self.final_data["volatile_stock"] = volatile_stock

                if self.disable_timeout:
                    self.final_data[
                        "homeassistant_products"
                    ] = await self.parse_products(self.final_data)
                    self.final_data["shopping_lists_data"] = self.build_item_list(
                        self.final_data
                    )
                    self._add_grocy_aggregate_entities(self.final_data)
                else:
                    async with timeout(t):
                        self.final_data[
                            "homeassistant_products"
                        ] = await self.parse_products(self.final_data)
                        self.final_data["shopping_lists_data"] = self.build_item_list(
                            self.final_data
                        )
                        self._add_grocy_aggregate_entities(self.final_data)

        finally:
            await self.update_refreshing_status(False)

        return self.final_data
