import json
import math
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
SEARCH_URL = "https://search.openfoodfacts.org/search"
USER_AGENT = "NomNomus/1.0 (local GTK nutrient tracker)"


class BarcodeLookupError(Exception):
    pass


class ProductNotFoundError(BarcodeLookupError):
    pass


@dataclass(frozen=True)
class ScannedFood:
    barcode: str
    name: str
    protein: float
    carbs: float
    fat: float
    basis: str
    basis_quantity: float

    def macros_for_amount(self, amount):
        factor = _number(amount) / self.basis_quantity
        return (
            self.protein * factor,
            self.carbs * factor,
            self.fat * factor,
        )


def normalize_barcode(barcode):
    barcode = str(barcode).strip()
    if not barcode.isdigit() or not 4 <= len(barcode) <= 24:
        raise BarcodeLookupError("Scan a numeric food barcode or enter one below.")
    return barcode


def product_from_response(barcode, response):
    barcode = normalize_barcode(barcode)
    if not isinstance(response, dict):
        raise BarcodeLookupError("Open Food Facts returned an unreadable response.")

    product = response.get("product")
    if response.get("status") != 1 or not isinstance(product, dict):
        raise ProductNotFoundError("This barcode was not found in Open Food Facts.")

    return food_from_product(barcode, product)


def food_from_product(barcode, product):
    barcode = normalize_barcode(barcode)
    nutriments = product.get("nutriments", {})
    if not isinstance(nutriments, dict):
        nutriments = {}
    serving_quantity = _number(product.get("serving_quantity"))
    has_serving_values = serving_quantity > 0 and any(
        _has_number(nutriments.get(f"{key}_serving"))
        for key in ("proteins", "carbohydrates", "fat")
    )

    if has_serving_values:
        suffix = "_serving"
        basis = product.get("serving_size") or f"{serving_quantity:g} g serving"
        basis_quantity = serving_quantity
    else:
        suffix = "_100g"
        basis = "100 g"
        basis_quantity = 100.0

    name = product.get("product_name") or product.get("brands") or f"Product {barcode}"
    if isinstance(name, list):
        name = ", ".join(name)

    return ScannedFood(
        barcode=barcode,
        name=name,
        protein=_number(nutriments.get(f"proteins{suffix}")),
        carbs=_number(nutriments.get(f"carbohydrates{suffix}")),
        fat=_number(nutriments.get(f"fat{suffix}")),
        basis=basis,
        basis_quantity=basis_quantity,
    )


def products_from_search_response(response):
    if not isinstance(response, dict) or not isinstance(response.get("hits"), list):
        raise BarcodeLookupError("Open Food Facts returned an unreadable response.")

    foods = []
    for product in response["hits"]:
        if not isinstance(product, dict):
            continue
        try:
            foods.append(food_from_product(product.get("code"), product))
        except BarcodeLookupError:
            continue
    return foods


def fetch_product(barcode, timeout=8):
    barcode = normalize_barcode(barcode)
    fields = "product_name,brands,serving_size,serving_quantity,nutriments"
    url = f"{API_URL.format(barcode=quote(barcode))}?fields={fields}"
    request = Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            raise ProductNotFoundError("This barcode was not found in Open Food Facts.") from error
        raise BarcodeLookupError("Open Food Facts could not look up this barcode.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise BarcodeLookupError("Could not connect to Open Food Facts. Check your connection.") from error
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise BarcodeLookupError("Open Food Facts returned an unreadable response.") from error

    return product_from_response(barcode, payload)


def search_products(query, timeout=8, page_size=5):
    query = str(query).strip()
    if len(query) < 3:
        return []

    parameters = urlencode(
        {
            "q": query,
            "page_size": page_size,
        }
    )
    request = Request(f"{SEARCH_URL}?{parameters}", headers={"User-Agent": USER_AGENT})

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise BarcodeLookupError("Open Food Facts could not search for this food.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise BarcodeLookupError("Could not connect to Open Food Facts. Check your connection.") from error
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise BarcodeLookupError("Open Food Facts returned an unreadable response.") from error

    return products_from_search_response(payload)


def _number(value):
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number >= 0 else 0.0


def _has_number(value):
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= 0
