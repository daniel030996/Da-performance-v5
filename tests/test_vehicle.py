"""DVLA registration lookup. The live call is stubbed; no API key is stored here."""

import io
import json
import logging
import urllib.error
from email.message import Message

from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


class _Response:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(status: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
        status,
        "error",
        Message(),
        io.BytesIO(body.encode("utf-8")),
    )


def test_rejects_registrations_that_are_not_uk_plates(monkeypatch):
    monkeypatch.delenv("DVLA_API_KEY", raising=False)
    for payload in (
        {},
        {"registration": ""},
        {"registration": "   "},
        {"registration": "AB12-CDE"},
        {"registration": "AB12CDEFG"},
        {"registration": "AB12 CDÉ"},
        {"registration": 123},
        {"registration": None},
    ):
        response = client.post("/api/vehicle", json=payload)
        assert response.status_code == 400
        assert response.json() == {"error": "Please provide a valid UK registration."}


def test_missing_key_is_a_config_error_and_does_not_call_dvla(monkeypatch):
    monkeypatch.delenv("DVLA_API_KEY", raising=False)
    called = {"count": 0}

    def urlopen(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("DVLA must not be called without a key")

    monkeypatch.setattr(main.urllib.request, "urlopen", urlopen)
    response = client.post("/api/vehicle", json={"registration": " ab12 cde "})
    assert response.status_code == 500
    assert response.json() == {"error": "DVLA_API_KEY is not configured."}
    assert called["count"] == 0


def test_success_maps_the_dvla_payload(monkeypatch):
    monkeypatch.setenv("DVLA_API_KEY", "test-key")
    monkeypatch.delenv("DVLA_API_URL", raising=False)
    captured = {}

    def urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["data"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        return _Response(
            200,
            json.dumps(
                {
                    "registrationNumber": "AB12CDE",
                    "make": "FORD",
                    "yearOfManufacture": 2012,
                    "fuelType": "PETROL",
                    "engineCapacity": 999,
                    "colour": "BLUE",
                }
            ),
        )

    monkeypatch.setattr(main.urllib.request, "urlopen", urlopen)
    response = client.post("/api/vehicle", json={"registration": "ab12 cde"})
    assert response.status_code == 200
    assert response.json() == {
        "registration": "AB12CDE",
        "make": "FORD",
        "model": None,
        "year": 2012,
        "fuel": "PETROL",
        "engineSize": "999cc",
        "colour": "BLUE",
    }
    assert captured["url"] == "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"
    assert captured["timeout"] == 15
    assert captured["data"] == {"registrationNumber": "AB12CDE"}
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["headers"]["accept"] == "application/json"


def test_null_engine_capacity_stays_null(monkeypatch):
    monkeypatch.setenv("DVLA_API_KEY", "test-key")

    def urlopen(request, timeout):
        return _Response(200, json.dumps({"make": "NISSAN", "engineCapacity": None, "colour": "RED"}))

    monkeypatch.setattr(main.urllib.request, "urlopen", urlopen)
    response = client.post("/api/vehicle", json={"registration": "A1"})
    assert response.status_code == 200
    body = response.json()
    assert body["engineSize"] is None
    assert body["model"] is None
    assert body["registration"] == "A1"
    assert body["make"] == "NISSAN"
    assert body["colour"] == "RED"


def test_dvla_404_is_vehicle_not_found(monkeypatch):
    monkeypatch.setenv("DVLA_API_KEY", "test-key")

    def urlopen(request, timeout):
        raise _http_error(404, '{"message":"Vehicle not found"}')

    monkeypatch.setattr(main.urllib.request, "urlopen", urlopen)
    response = client.post("/api/vehicle", json={"registration": "AB12CDE"})
    assert response.status_code == 404
    assert response.json() == {"error": "Vehicle not found."}


def test_other_dvla_errors_are_logged_and_returned_as_502(monkeypatch, caplog):
    monkeypatch.setenv("DVLA_API_KEY", "test-key")

    def urlopen(request, timeout):
        raise _http_error(403, "forbidden-body")

    monkeypatch.setattr(main.urllib.request, "urlopen", urlopen)
    with caplog.at_level(logging.ERROR):
        response = client.post("/api/vehicle", json={"registration": "AB12CDE"})
    assert response.status_code == 502
    assert response.json() == {"error": "Vehicle lookup failed. Please try again."}
    assert "403" in caplog.text
    assert "forbidden-body" in caplog.text
    assert "test-key" not in caplog.text


def test_transport_errors_are_500(monkeypatch):
    monkeypatch.setenv("DVLA_API_KEY", "test-key")

    def urlopen(request, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(main.urllib.request, "urlopen", urlopen)
    response = client.post("/api/vehicle", json={"registration": "AB12CDE"})
    assert response.status_code == 500
    assert response.json() == {"error": "Vehicle lookup failed. Please try again."}


def test_custom_dvla_url_is_read_per_request(monkeypatch):
    monkeypatch.setenv("DVLA_API_KEY", "test-key")
    monkeypatch.setenv("DVLA_API_URL", "https://example.test/vehicles")
    captured = {}

    def urlopen(request, timeout):
        captured["url"] = request.full_url
        return _Response(200, json.dumps({"make": "VAUXHALL"}))

    monkeypatch.setattr(main.urllib.request, "urlopen", urlopen)
    response = client.post("/api/vehicle", json={"registration": "KY64ABC"})
    assert response.status_code == 200
    assert captured["url"] == "https://example.test/vehicles"
    assert response.json()["make"] == "VAUXHALL"
