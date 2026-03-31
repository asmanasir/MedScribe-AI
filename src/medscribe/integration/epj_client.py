from __future__ import annotations

"""
EPJ Integration Client — sends approved notes to hospital journal systems.

Supports Norwegian EPJ systems:
- DIPS Arena (hospitals) → FHIR R4 REST API
- CGM Journal (fastleger) → FHIR R4 REST API
- Helseplattformen / Epic (Midt-Norge) → FHIR R4 REST API
- Generic FHIR → any FHIR R4 server

All Norwegian EPJ systems are converging on FHIR R4.
The only differences are:
1. Base URL (where to POST)
2. Authentication (OAuth2 / certificate-based)
3. Required extensions (DIPS-specific fields, etc.)

Flow:
  1. Note approved in MedScribe
  2. EPJClient.send_to_journal(visit, note)
  3. Builds FHIR Bundle
  4. POSTs to EPJ's FHIR endpoint
  5. Returns success/failure
  6. On success → purge patient data from MedScribe (GDPR)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import structlog

from medscribe.domain.models import ClinicalNote, Visit
from medscribe.integration.fhir_adapter import FHIRDocumentBuilder

logger = structlog.get_logger()


@dataclass
class EPJTransferResult:
    """Result of sending a note to the EPJ system."""
    success: bool
    epj_system: str
    response_code: int
    response_body: str
    fhir_resource_id: str | None = None


class EPJClient(ABC):
    """Abstract EPJ client — one implementation per EPJ vendor."""

    @abstractmethod
    async def send_to_journal(self, visit: Visit, note: ClinicalNote) -> EPJTransferResult:
        """Send an approved note to the EPJ system."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify connectivity to the EPJ system."""
        ...


class DIPSClient(EPJClient):
    """
    DIPS Arena integration — used by most Norwegian hospitals.

    DIPS exposes a FHIR R4 REST API for document submission.
    Authentication is typically OAuth2 with hospital-issued credentials.

    DIPS FHIR endpoint pattern:
      https://<hospital>.dips.no/fhir/R4/
    """

    def __init__(self, base_url: str, client_id: str, client_secret: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._fhir = FHIRDocumentBuilder(fhir_base_url=base_url)
        self._http = httpx.AsyncClient(timeout=30.0)
        self._token: str | None = None

    async def _authenticate(self) -> str:
        """Get OAuth2 token from DIPS."""
        resp = await self._http.post(
            f"{self._base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "fhir.write",
            },
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    async def send_to_journal(self, visit: Visit, note: ClinicalNote) -> EPJTransferResult:
        if not self._token:
            await self._authenticate()

        bundle = self._fhir.build_bundle(visit, note)

        resp = await self._http.post(
            f"{self._base_url}/fhir/R4/",
            json=bundle,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/fhir+json",
            },
        )

        logger.info(
            "epj.dips.transfer",
            visit_id=str(visit.id),
            status_code=resp.status_code,
            success=resp.is_success,
        )

        return EPJTransferResult(
            success=resp.is_success,
            epj_system="DIPS",
            response_code=resp.status_code,
            response_body=resp.text[:500],
            fhir_resource_id=_extract_resource_id(resp.text) if resp.is_success else None,
        )

    async def health_check(self) -> bool:
        try:
            resp = await self._http.get(f"{self._base_url}/fhir/R4/metadata")
            return resp.status_code == 200
        except Exception:
            return False


class CGMClient(EPJClient):
    """
    CGM Journal integration — used by Norwegian GP clinics (fastleger).

    CGM uses FHIR R4 with certificate-based authentication.
    """

    def __init__(self, base_url: str, cert_path: str, key_path: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._fhir = FHIRDocumentBuilder(fhir_base_url=base_url)
        self._http = httpx.AsyncClient(
            timeout=30.0,
            cert=(cert_path, key_path),
        )

    async def send_to_journal(self, visit: Visit, note: ClinicalNote) -> EPJTransferResult:
        bundle = self._fhir.build_bundle(visit, note)

        resp = await self._http.post(
            f"{self._base_url}/fhir/R4/",
            json=bundle,
            headers={"Content-Type": "application/fhir+json"},
        )

        logger.info(
            "epj.cgm.transfer",
            visit_id=str(visit.id),
            status_code=resp.status_code,
        )

        return EPJTransferResult(
            success=resp.is_success,
            epj_system="CGM",
            response_code=resp.status_code,
            response_body=resp.text[:500],
            fhir_resource_id=_extract_resource_id(resp.text) if resp.is_success else None,
        )

    async def health_check(self) -> bool:
        try:
            resp = await self._http.get(f"{self._base_url}/fhir/R4/metadata")
            return resp.status_code == 200
        except Exception:
            return False


class GenericFHIRClient(EPJClient):
    """
    Generic FHIR R4 client — works with any FHIR-compliant EPJ.

    Use this for:
    - Helseplattformen (Epic)
    - Infodoc
    - Pridok
    - Any FHIR R4 server
    """

    def __init__(self, base_url: str, auth_header: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._fhir = FHIRDocumentBuilder(fhir_base_url=base_url)
        headers = {"Content-Type": "application/fhir+json"}
        if auth_header:
            headers["Authorization"] = auth_header
        self._http = httpx.AsyncClient(timeout=30.0, headers=headers)

    async def send_to_journal(self, visit: Visit, note: ClinicalNote) -> EPJTransferResult:
        bundle = self._fhir.build_bundle(visit, note)

        resp = await self._http.post(
            f"{self._base_url}/fhir/R4/",
            json=bundle,
        )

        logger.info(
            "epj.generic.transfer",
            visit_id=str(visit.id),
            status_code=resp.status_code,
        )

        return EPJTransferResult(
            success=resp.is_success,
            epj_system="GenericFHIR",
            response_code=resp.status_code,
            response_body=resp.text[:500],
            fhir_resource_id=_extract_resource_id(resp.text) if resp.is_success else None,
        )

    async def health_check(self) -> bool:
        try:
            resp = await self._http.get(f"{self._base_url}/fhir/R4/metadata")
            return resp.status_code == 200
        except Exception:
            return False


def _extract_resource_id(response_text: str) -> str | None:
    """Extract the FHIR resource ID from a response."""
    try:
        import json
        data = json.loads(response_text)
        if "id" in data:
            return data["id"]
        if "entry" in data and data["entry"]:
            return data["entry"][0].get("response", {}).get("location", "")
    except Exception:
        pass
    return None
