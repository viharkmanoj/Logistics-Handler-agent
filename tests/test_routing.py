"""
Tests for Google Maps Routes API integration and routing estimation.
Uses unittest.mock to simulate live Google Maps Routes API responses and failures,
ensuring tests do not require real API keys or incur billing.
"""

import pytest
from unittest.mock import patch, MagicMock
from logistics.routing import (
    estimate_delivery,
    verify_google_maps_connection,
    sanitize_secret,
    GOOGLE_ROUTES_API_URL,
)


def test_routing_input_validation(temp_db):
    """Verify input validation for empty or identical origin/destination."""
    # Empty origin
    res_empty_orig = estimate_delivery("", "Bengaluru", db_path=temp_db)
    assert res_empty_orig["success"] is False
    assert res_empty_orig["error_code"] == "INVALID_ORIGIN"

    # Empty destination
    res_empty_dest = estimate_delivery("Chennai", "", db_path=temp_db)
    assert res_empty_dest["success"] is False
    assert res_empty_dest["error_code"] == "INVALID_DESTINATION"

    # Identical origin and destination
    res_same = estimate_delivery("Chennai", "Chennai", db_path=temp_db)
    assert res_same["success"] is False
    assert res_same["error_code"] == "SAME_ORIGIN_DESTINATION"


def test_routing_simulated_fallback_when_unconfigured(temp_db, monkeypatch):
    """When GOOGLE_MAPS_API_KEY is not configured, returns clearly labeled simulated matrix."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("ROUTING_API_KEY", raising=False)

    res = estimate_delivery("Chennai", "Bengaluru", db_path=temp_db)
    assert res["success"] is True
    assert res["data"]["is_simulated"] is True
    assert "Simulated Logistics Estimation Engine" in res["data"]["provider"]
    assert res["data"]["estimated_distance_km"] == 346
    assert "[SIMULATED]" in res["message"]


def test_routing_mocked_google_maps_routes_success(temp_db, monkeypatch):
    """Test Google Maps Routes API integration with mocked HTTP 200 response."""
    test_key = "AIzaSyFakeValidKeyForTesting12345678"
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", test_key)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "routes": [
            {
                "distanceMeters": 348500,
                "duration": "24300s",  # ~6.75 hours
                "description": "via AH45 / NH48",
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = estimate_delivery("Chennai", "Bengaluru", db_path=temp_db)

        assert mock_post.called
        call_headers = mock_post.call_args[1]["headers"]
        assert call_headers["X-Goog-Api-Key"] == test_key
        assert "routes.distanceMeters" in call_headers["X-Goog-FieldMask"]

        assert res["success"] is True
        assert res["data"]["is_simulated"] is False
        assert "Google Maps Routes API (Live v2 ComputeRoutes)" in res["data"]["provider"]
        assert res["data"]["estimated_distance_km"] == 348.5
        assert res["data"]["estimated_transit_hours"] == 6.8
        assert res["data"]["route_description"] == "via AH45 / NH48"
        assert "[LIVE GOOGLE MAPS]" in res["message"]


def test_routing_mocked_google_maps_failure_graceful_fallback(temp_db, monkeypatch):
    """When Google Maps API returns HTTP 403 or network error, falls back safely to simulation."""
    test_key = "AIzaSyExpiredKey987654321"
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", test_key)

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = '{"error": {"code": 403, "message": "Method doesn\'t allow unregistered callers."}}'

    with patch("requests.post", return_value=mock_resp):
        res = estimate_delivery("Chennai", "Bengaluru", db_path=temp_db)

        # Must fall back gracefully to simulation without raising an exception
        assert res["success"] is True
        assert res["data"]["is_simulated"] is True
        assert "Simulated Logistics Estimation Engine" in res["data"]["provider"]
        assert res["data"]["estimated_distance_km"] == 346


def test_secret_sanitization_in_routing():
    """Verify API keys are never leaked into log strings or error messages."""
    secret_key = "AIzaSyTopSecretKeyXYZ123"
    leaked_str = f"Error calling {GOOGLE_ROUTES_API_URL} with key {secret_key} on request."
    sanitized = sanitize_secret(leaked_str, secret_key)

    assert secret_key not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized


def test_verify_google_maps_connection_not_configured(monkeypatch):
    """Verify connection check returns NOT CONFIGURED when key is absent."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("ROUTING_API_KEY", raising=False)

    check = verify_google_maps_connection()
    assert check["status"] == "NOT CONFIGURED"
    assert check["is_connected"] is False


def test_verify_google_maps_connection_mocked_connected(monkeypatch):
    """Verify connection check returns CONNECTED when live check succeeds."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp):
        check = verify_google_maps_connection(api_key="AIzaSyTestingKey123")
        assert check["status"] == "CONNECTED"
        assert check["is_connected"] is True
