import unittest

from sop.rescue_map import AmapMapProvider, FallbackMapProvider, mask_location


class RescueMapTests(unittest.TestCase):
    def test_no_key_uses_manual_location(self):
        provider = AmapMapProvider(api_key="")
        result = provider.geocode("杭州市富阳区银湖街道")
        self.assertEqual(result["mode"], "manual")
        self.assertEqual(result["label"], "杭州市富阳区银湖街道")

    def test_provider_timeout_falls_back(self):
        provider = AmapMapProvider(api_key="demo", request_fn=lambda _: (_ for _ in ()).throw(TimeoutError()))
        result = provider.geocode("银湖街道")
        self.assertEqual(result["mode"], "manual")

    def test_mask_location_is_stable_and_not_exact(self):
        masked = mask_location(30.2, 120.1)
        self.assertNotEqual(masked, (30.2, 120.1))
        self.assertEqual(masked, mask_location(30.2, 120.1))


class FallbackMapProviderTests(unittest.TestCase):
    def test_manual_provider_returns_label_without_coordinates(self):
        result = FallbackMapProvider().reverse_geocode(30.2, 120.1)
        self.assertEqual(result["mode"], "manual")
        self.assertIn("人工", result["label"])


if __name__ == "__main__":
    unittest.main()
