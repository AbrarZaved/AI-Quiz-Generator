# subscriptions/dimepay.py
import logging
import jwt
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

import json  # add near the top with the other imports
class DimePayError(Exception):
    """Raised when a DimePay API call fails."""


class DimePayClient:
    def __init__(self):
        self.base_url = settings.DIMEPAY_API_URL.rstrip("/")
        self.client_key = settings.DIMEPAY_CLIENT_KEY
        self.signing_secret = settings.DIMEPAY_SIGNING_SECRET

        # Fail fast with a clear message if config is missing.
        if not self.client_key or not self.signing_secret:
            raise DimePayError(
                "DimePay is not configured: set DIMEPAY_CLIENT_KEY and "
                "DIMEPAY_SIGNING_SECRET in your environment/.env"
            )

    def _headers(self):
        return {
            "client_key": self.client_key,
            "Content-Type": "application/json",
        }
    def _sign(self, payload) -> str:
        # PyJWT serializes to JSON itself, so it MUST receive a dict — never a string/set.
        if isinstance(payload, (str, bytes)):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise DimePayError(
                f"JWT payload must be a dict, got {type(payload).__name__}"
            )
        token = jwt.encode(payload, self.signing_secret, algorithm="HS256")
        return token.decode() if isinstance(token, bytes) else token

    def create_hosted_page(self, *, order_id, amount, email, item_name,
                           item_description="", currency="USD"):
        payload = {
            "webhookUrl": f"{settings.BACKEND_URL}/api/billing/webhook/dimepay/",
            "redirectUrl": f"{settings.FRONTEND_URL}/payment/success?order_id={order_id}",
            "checkoutUrl": f"{settings.FRONTEND_URL}/payment/checkout",
            "tokenize": False,
            "currency": currency,
            "id": order_id,
            "referenceTransactionId": order_id,
            "subtotal": float(amount),
            "total": float(amount),
            "tax": 0,
            "email": email,
            "items": [
                {
                    "id": "premium-monthly",
                    "price": float(amount),
                    "sku": "PREMIUM-1M",
                    "quantity": 1,
                    "name": item_name,
                    "shortDescription": item_description,
                }
            ],
        }

        # NOTE: move _sign INSIDE the try so an empty/invalid key doesn't
        # escape as an uncaught 500.
        try:
            signed = self._sign(payload)      # now inside the try
            res = requests.post(
                f"{self.base_url}/payments/hosted-page",
                json={"lang": "en", "data": signed},
                headers=self._headers(),
                timeout=30,
            )
            res.raise_for_status()
        except requests.HTTPError as exc:
            body = getattr(exc.response, "text", "")
            logger.error("DimePay rejected hosted-page (%s): %s",
                        getattr(exc.response, "status_code", "?"), body)
            raise DimePayError(f"DimePay returned {exc.response.status_code}: {body}") from exc
        except requests.RequestException as exc:
            logger.exception("DimePay hosted-page request failed")
            raise DimePayError(f"DimePay hosted-page request failed: {exc}") from exc
        return res.json()