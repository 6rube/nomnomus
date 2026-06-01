import unittest

from nutrients.barcodes import (
    BarcodeLookupError,
    ProductNotFoundError,
    normalize_barcode,
    product_from_response,
    products_from_search_response,
)


class BarcodeTest(unittest.TestCase):
    def test_serving_values_are_preferred_when_available(self):
        food = product_from_response(
            "3017620422003",
            {
                "status": 1,
                "product": {
                    "product_name": "Hazelnut spread",
                    "serving_size": "15 g",
                    "serving_quantity": 15,
                    "nutriments": {
                        "proteins_serving": 0.945,
                        "carbohydrates_serving": 8.64,
                        "fat_serving": 4.635,
                        "proteins_100g": 6.3,
                        "carbohydrates_100g": 57.6,
                        "fat_100g": 30.9,
                    },
                },
            },
        )

        self.assertEqual(food.name, "Hazelnut spread")
        self.assertEqual(food.basis, "15 g")
        self.assertEqual(food.basis_quantity, 15)
        self.assertEqual(food.protein, 0.945)
        self.assertEqual(food.carbs, 8.64)
        self.assertEqual(food.fat, 4.635)
        self.assertEqual(food.macros_for_amount(30), (1.89, 17.28, 9.27))

    def test_100g_values_are_used_without_a_serving(self):
        food = product_from_response(
            "12345678",
            {
                "status": 1,
                "product": {
                    "brands": "Example",
                    "nutriments": {
                        "proteins_100g": 10,
                        "carbohydrates_100g": 20,
                        "fat_100g": 3,
                    },
                },
            },
        )

        self.assertEqual(food.name, "Example")
        self.assertEqual(food.basis, "100 g")
        self.assertEqual(food.basis_quantity, 100)
        self.assertEqual(food.protein, 10)
        self.assertEqual(food.carbs, 20)
        self.assertEqual(food.fat, 3)
        self.assertEqual(food.macros_for_amount(250), (25, 50, 7.5))

    def test_unknown_products_are_reported(self):
        with self.assertRaises(ProductNotFoundError):
            product_from_response("12345678", {"status": 0})

    def test_non_numeric_qr_codes_are_rejected(self):
        with self.assertRaises(BarcodeLookupError):
            normalize_barcode("https://example.com")

    def test_search_results_are_parsed_and_invalid_products_are_skipped(self):
        foods = products_from_search_response(
            {
                "hits": [
                    {
                        "code": "12345678",
                        "product_name": "Example",
                        "nutriments": {
                            "proteins_100g": 10,
                            "carbohydrates_100g": 20,
                            "fat_100g": 3,
                        },
                    },
                    {"code": "not-a-barcode", "product_name": "Invalid"},
                ]
            }
        )

        self.assertEqual(len(foods), 1)
        self.assertEqual(foods[0].name, "Example")
        self.assertEqual(foods[0].basis_quantity, 100)

    def test_invalid_search_responses_are_reported(self):
        with self.assertRaises(BarcodeLookupError):
            products_from_search_response({"hits": None})


if __name__ == "__main__":
    unittest.main()
