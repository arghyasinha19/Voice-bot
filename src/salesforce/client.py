"""
salesforce/client.py
--------------------
Async Salesforce REST API client with OAuth 2.0 auto-auth.

Auth strategy (Username-Password flow):
  - On first API call, mints a fresh access token via Connected App credentials.
  - Caches the token in memory for the lifetime of the process.
  - On a 401/403 response, automatically re-authenticates once and retries.
  - No manual token rotation required — token will never silently expire mid-session.

Required .env variables:
  SF_INSTANCE_URL    – e.g. https://orgfarm-xxx.develop.my.salesforce.com
  SF_CLIENT_ID       – Connected App Consumer Key
  SF_CLIENT_SECRET   – Connected App Consumer Secret
  SF_USERNAME        – Salesforce login username
  SF_PASSWORD        – Password + Security Token concatenated (e.g. MyPassword8xToken)
  SF_API_VERSION     – (optional) defaults to v59.0
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from loguru import logger


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------

class SalesforceAuthError(Exception):
    """Raised when OAuth token minting fails or credentials are rejected."""


class SalesforceAPIError(Exception):
    """Raised when Salesforce returns a non-transient error response."""

    def __init__(self, status_code: int, error_code: str, message: str):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(f"[{status_code}] {error_code}: {message}")


class SalesforceNetworkError(Exception):
    """Raised when all retry attempts are exhausted due to connectivity issues."""


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class CreateRecordResponse:
    record_id: str
    success: bool
    errors: list[str]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class SalesforceClient:
    """
    Async Salesforce REST API client with OAuth 2.0 auto-authentication.

    Authenticates via the Username-Password flow using a Connected App.
    Tokens are cached in memory and transparently refreshed on expiry.

    Usage:
        client = SalesforceClient()
        response = await client.create_record("Lead", payload)
    """

    # Retry configuration
    MAX_RETRIES: int = 3
    RETRY_BASE_DELAY: float = 1.0
    RETRY_MAX_DELAY: float = 8.0
    TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    # Salesforce OAuth token endpoint (production + Developer Orgs)
    _TOKEN_ENDPOINT: str = "https://orgfarm-18008c4bb2-dev-ed.develop.my.salesforce.com/services/oauth2/token"

    def __init__(self) -> None:
        self._instance_url: str = self._require_env("SF_INSTANCE_URL").rstrip("/")
        self._client_id: str = self._require_env("SF_CLIENT_ID")
        self._client_secret: str = self._require_env("SF_CLIENT_SECRET")
        # self._username: str = self._require_env("SF_USERNAME")
        # self._password: str = self._require_env("SF_PASSWORD")
        self._api_version: str = os.getenv("SF_API_VERSION", "v59.0")
        self._base_url: str = f"{self._instance_url}/services/data/{self._api_version}/sobjects"

        # In-memory token cache — refreshed on 401 automatically
        self._access_token: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_record(
        self,
        sobject: str,
        payload: Dict[str, Any],
        *,
        timeout: float = 15.0,
    ) -> CreateRecordResponse:
        """
        POST a new record to /sobjects/<SObject>/.

        Automatically mints a token on first call and retries once with a
        fresh token on 401/403 before raising SalesforceAuthError.

        Args:
            sobject:  Salesforce object API name (e.g. "Lead").
            payload:  Field-value dict to set on the record.
            timeout:  Per-request HTTP timeout in seconds.

        Returns:
            CreateRecordResponse with the new record ID.

        Raises:
            SalesforceAuthError    – OAuth failed or credentials rejected.
            SalesforceAPIError     – Non-retryable Salesforce error.
            SalesforceNetworkError – All retries exhausted.
        """
        # Ensure we have a token before the first attempt
        if not self._access_token:
            await self._authenticate()

        url = f"{self._base_url}/{sobject}/"
        last_exc: Optional[Exception] = None

        async with httpx.AsyncClient(timeout=timeout) as http:
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    logger.debug(
                        f"Salesforce: POST {sobject} — attempt {attempt}/{self.MAX_RETRIES}"
                    )
                    headers = self._build_headers()
                    response = await http.post(url, json=payload, headers=headers)

                    # Token expired mid-session → re-auth once, then retry
                    if response.status_code in (401, 403):
                        logger.warning(
                            f"Salesforce: Token rejected (HTTP {response.status_code}) "
                            f"on attempt {attempt} — refreshing token and retrying..."
                        )
                        await self._authenticate(force=True)
                        headers = self._build_headers()
                        response = await http.post(url, json=payload, headers=headers)

                    return self._handle_response(response, sobject)

                except (SalesforceAuthError, SalesforceAPIError):
                    raise   # Non-retryable

                except httpx.TimeoutException as exc:
                    last_exc = exc
                    logger.warning(f"Salesforce: Timeout on attempt {attempt} — {exc}")

                except httpx.RequestError as exc:
                    last_exc = exc
                    logger.warning(f"Salesforce: Network error on attempt {attempt} — {exc}")

                if attempt < self.MAX_RETRIES:
                    delay = min(
                        self.RETRY_BASE_DELAY * (2 ** (attempt - 1)),
                        self.RETRY_MAX_DELAY,
                    )
                    logger.info(f"Salesforce: Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)

        raise SalesforceNetworkError(
            f"Salesforce: All {self.MAX_RETRIES} attempts failed. Last error: {last_exc}"
        )

    # ------------------------------------------------------------------
    # OAuth 2.0 Username-Password Flow
    # ------------------------------------------------------------------

    async def _authenticate(self, *, force: bool = False) -> None:
        """
        Mint a fresh OAuth token via the Connected App Username-Password flow.

        Args:
            force: If True, always re-authenticate even if a token is cached.

        Raises:
            SalesforceAuthError: If the OAuth request fails.
        """
        if self._access_token and not force:
            return

        logger.info("Salesforce: Authenticating via OAuth 2.0 Client Credentials flow...")

        payload = {
            "grant_type":    "client_credentials",
            "client_id":     self._client_id,
            "client_secret": self._client_secret,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                response = await http.post(
                    self._TOKEN_ENDPOINT,
                    data=payload,
                    headers={"Accept": "application/json"},
                )

            if response.status_code != 200:
                try:
                    body = response.json()
                    error = body.get("error", "unknown")
                    desc  = body.get("error_description", response.text)
                except Exception:
                    error, desc = "parse_error", response.text

                raise SalesforceAuthError(
                    f"OAuth token request failed (HTTP {response.status_code}): "
                    f"{error} — {desc}"
                )

            body = response.json()
            self._access_token = body.get("access_token")
            # The token endpoint can also return a fresh instance_url — honour it
            returned_instance = body.get("instance_url", "").rstrip("/")
            if returned_instance:
                self._instance_url = returned_instance
                self._base_url = (
                    f"{self._instance_url}/services/data/{self._api_version}/sobjects"
                )

            logger.success(
                f"Salesforce: Authenticated successfully. "
                f"Instance: {self._instance_url}"
            )

        except SalesforceAuthError:
            raise
        except Exception as exc:
            raise SalesforceAuthError(
                f"OAuth token request raised an unexpected error: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    def _handle_response(
        self, response: httpx.Response, sobject: str
    ) -> CreateRecordResponse:
        """Parse and validate the Salesforce REST response."""

        # Auth failures after re-auth attempt → hard stop
        if response.status_code in (401, 403):
            raise SalesforceAuthError(
                f"Salesforce rejected the access token even after refresh "
                f"(HTTP {response.status_code}). "
                "Check SF_CLIENT_ID, SF_CLIENT_SECRET, SF_USERNAME, SF_PASSWORD in .env."
            )

        # Transient server errors (handled by retry loop)
        if response.status_code in self.TRANSIENT_STATUS_CODES:
            response.raise_for_status()

        # Successful creation
        if response.status_code == 201:
            body = response.json()
            record_id: str  = body.get("id", "")
            success: bool   = body.get("success", False)
            errors: list[str] = [str(e) for e in body.get("errors", [])]

            if not success or not record_id:
                raise SalesforceAPIError(
                    response.status_code,
                    "UNEXPECTED_RESPONSE",
                    f"Salesforce returned 201 but reported failure: {body}",
                )

            logger.success(f"Salesforce: {sobject} created — ID: {record_id}")
            return CreateRecordResponse(record_id=record_id, success=True, errors=errors)

        # Any other non-2xx
        try:
            error_body = response.json()
            if isinstance(error_body, list) and error_body:
                error_code = error_body[0].get("errorCode", "UNKNOWN")
                message    = error_body[0].get("message", response.text)
            else:
                error_code = "UNKNOWN"
                message    = str(error_body)
        except Exception:
            error_code = "PARSE_ERROR"
            message    = response.text

        raise SalesforceAPIError(response.status_code, error_code, message)

    @staticmethod
    def _require_env(key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise SalesforceAuthError(
                f"Missing required environment variable: {key}. "
                "Check your .env file."
            )
        return value
