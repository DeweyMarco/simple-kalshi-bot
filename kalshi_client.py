#!/usr/bin/env python3
"""
Shared Kalshi API client with RSA-PSS authentication.

Extracted from consensus.py for reuse across the project.
"""

import base64
import os
import time
import uuid

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv

load_dotenv()


def get_api_base():
    """Return API base URL based on KALSHI_USE_DEMO env var."""
    use_demo = os.getenv("KALSHI_USE_DEMO", "true").lower() == "true"
    if use_demo:
        return "https://demo-api.kalshi.co/trade-api/v2"
    return "https://api.elections.kalshi.com/trade-api/v2"


def load_private_key():
    """Load RSA private key from file."""
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    if not key_path:
        raise ValueError("KALSHI_PRIVATE_KEY_PATH environment variable required")

    key_path = os.path.expanduser(key_path)
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    return private_key


class KalshiClient:
    """Authenticated Kalshi API client using RSA key signing."""

    def __init__(self):
        self.api_base = get_api_base()
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
        if not self.api_key_id:
            raise ValueError("KALSHI_API_KEY_ID environment variable required")

        self.private_key = load_private_key()
        self.session = requests.Session()

    def _sign_request(self, method: str, path: str, timestamp: str) -> str:
        """Generate RSA-PSS signature for request."""
        path_without_query = path.split("?")[0]
        message = f"{timestamp}{method}/trade-api/v2{path_without_query}"
        signature = self.private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _request(self, method: str, path: str, **kwargs):
        """Make authenticated request to Kalshi API."""
        url = f"{self.api_base}{path}"
        timestamp = str(int(time.time() * 1000))
        signature = self._sign_request(method.upper(), path, timestamp)

        headers = kwargs.pop("headers", {})
        headers.update({
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        })

        resp = self.session.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get_balance(self):
        """Get account balance."""
        return self._request("GET", "/portfolio/balance", timeout=20)

    def get_markets(self, series_ticker=None, status="open", limit=200, cursor=None):
        """Get markets, optionally filtered by series."""
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/markets", params=params, timeout=30)

    def get_market(self, ticker):
        """Get a specific market."""
        resp = self._request("GET", f"/markets/{ticker}", timeout=20)
        return resp.get("market", {})

    def get_events(self, status="open", limit=200, cursor=None):
        """Get events with optional filtering."""
        params = {"status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/events", params=params, timeout=30)

    def place_order(self, ticker, side, contracts, price_cents, dry_run=False):
        """Place a limit order."""
        if dry_run:
            return {
                "order": {
                    "order_id": f"DRY-RUN-{uuid.uuid4()}",
                    "status": "simulated",
                    "ticker": ticker,
                    "side": side,
                    "count": contracts,
                }
            }

        order = {
            "ticker": ticker,
            "client_order_id": str(uuid.uuid4()),
            "type": "limit",
            "action": "buy",
            "side": side,
            "count": contracts,
        }

        if side == "yes":
            order["yes_price"] = price_cents
        else:
            order["no_price"] = price_cents

        return self._request("POST", "/portfolio/orders", json=order, timeout=30)
