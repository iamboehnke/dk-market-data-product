"""Kør: python manage.py test   (kræver en lokal kørsel af pipelinen først)."""
import json
from pathlib import Path

from django.test import Client, SimpleTestCase, override_settings

LOCAL = Path(__file__).resolve().parents[2] / "pipeline" / "_local" / "public" / "kroner-og-renter" / "v1"


@override_settings(DATA_BASE_URL=str(LOCAL), ALLOWED_HOSTS=["testserver"])
class CatalogTests(SimpleTestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()

    def test_index_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Valutakurser, daglige")

    def test_product_page_shows_contract_and_lineage(self):
        response = self.client.get("/produkter/fx_daily/")
        self.assertContains(response, "ERM II")
        self.assertContains(response, "Bronze")

    def test_unknown_product_is_404(self):
        self.assertEqual(self.client.get("/api/v1/products/nope/").status_code, 404)

    def test_data_filtering(self):
        response = self.client.get("/api/v1/products/fx_daily/data/?code=eur&from=2026-10-01&limit=3")
        body = json.loads(response.content)
        self.assertEqual(body["count"], 3)
        self.assertTrue(all(r["currency"] == "EUR" for r in body["rows"]))
        self.assertEqual(body["rows"][0]["rate_date"], "2026-10-08")

    def test_bad_date_is_400(self):
        response = self.client.get("/api/v1/products/fx_daily/data/?from=igår")
        self.assertEqual(response.status_code, 400)

    def test_cors_only_for_allowed_origin(self):
        ok = self.client.get("/api/v1/latest/", HTTP_ORIGIN="https://mikkelbohnke.com")
        self.assertEqual(ok["Access-Control-Allow-Origin"], "https://mikkelbohnke.com")
        other = self.client.get("/api/v1/latest/", HTTP_ORIGIN="https://example.com")
        self.assertNotIn("Access-Control-Allow-Origin", other)

    @override_settings(DATA_BASE_URL="/findes/ikke")
    def test_missing_data_returns_503(self):
        self.assertEqual(self.client.get("/api/v1/latest/").status_code, 503)
