from __future__ import annotations

"""
CLI tool — test and interact with MedScribe without the API.

Usage:
    python -m medscribe.cli token --user DR001
    python -m medscribe.cli create-visit --patient P001 --clinician DR001
    python -m medscribe.cli process --visit-id <uuid> --audio path/to/audio.wav
    python -m medscribe.cli status --visit-id <uuid>

Why a CLI?
1. Fast testing during development (no Swagger, no curl)
2. Scripting and automation
3. Demonstrates the system works end-to-end
4. Useful for demos and presentations
"""

import argparse
import json
import sys

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"


class MedScribeCLI:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=120.0)

    def get_token(self, client_id: str, client_secret: str, role: str = "clinician") -> str:
        """Get a JWT token from the auth endpoint."""
        response = self._client.post(
            "/api/v1/auth/token",
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "role": role,
            },
        )
        response.raise_for_status()
        data = response.json()
        token = data["access_token"]
        # Update client with new token
        self._client.headers["Authorization"] = f"Bearer {token}"
        return token

    def health(self) -> dict:
        """Check service health."""
        response = self._client.get("/health")
        response.raise_for_status()
        return response.json()

    def create_visit(self, patient_id: str, clinician_id: str, metadata: dict | None = None) -> dict:
        """Create a new visit."""
        response = self._client.post(
            "/api/v1/visits",
            json={
                "patient_id": patient_id,
                "clinician_id": clinician_id,
                "metadata": metadata or {},
            },
        )
        response.raise_for_status()
        return response.json()

    def get_visit(self, visit_id: str) -> dict:
        """Get visit details."""
        response = self._client.get(f"/api/v1/visits/{visit_id}")
        response.raise_for_status()
        return response.json()

    def get_status(self, visit_id: str) -> dict:
        """Get visit status."""
        response = self._client.get(f"/api/v1/visits/{visit_id}/status")
        response.raise_for_status()
        return response.json()

    def transcribe(self, visit_id: str, audio_path: str) -> dict:
        """Upload audio and transcribe."""
        with open(audio_path, "rb") as f:
            # Remove content-type for multipart
            headers = dict(self._client.headers)
            headers.pop("Content-Type", None)
            response = self._client.post(
                f"/api/v1/visits/{visit_id}/transcribe",
                files={"audio": (audio_path, f, "audio/wav")},
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def structure(self, visit_id: str) -> dict:
        """Structure an existing transcript into a clinical note."""
        response = self._client.post(f"/api/v1/visits/{visit_id}/structure")
        response.raise_for_status()
        return response.json()

    def process(self, visit_id: str, audio_path: str) -> dict:
        """Full pipeline: audio → transcript → note."""
        with open(audio_path, "rb") as f:
            headers = dict(self._client.headers)
            headers.pop("Content-Type", None)
            response = self._client.post(
                f"/api/v1/visits/{visit_id}/process",
                files={"audio": (audio_path, f, "audio/wav")},
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def approve(self, visit_id: str, approved_by: str) -> dict:
        """Approve a clinical note."""
        response = self._client.post(
            f"/api/v1/visits/{visit_id}/approve",
            json={"approved_by": approved_by},
        )
        response.raise_for_status()
        return response.json()

    def audit(self, visit_id: str) -> list:
        """Get audit trail."""
        response = self._client.get(f"/api/v1/visits/{visit_id}/audit")
        response.raise_for_status()
        return response.json()


def _print_json(data):
    """Pretty-print JSON output."""
    print(json.dumps(data, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(
        description="MedScribe AI CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check health
  %(prog)s health

  # Get a token
  %(prog)s token --user DR001 --secret CHANGE-ME-IN-PRODUCTION

  # Create a visit and process audio
  %(prog)s create-visit --patient P001 --clinician DR001 --token <jwt>
  %(prog)s process --visit-id <uuid> --audio recording.wav --token <jwt>
  %(prog)s approve --visit-id <uuid> --approved-by DR001 --token <jwt>
  %(prog)s audit --visit-id <uuid> --token <jwt>
        """,
    )
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--token", help="JWT bearer token")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # health
    subparsers.add_parser("health", help="Check service health")

    # token
    token_parser = subparsers.add_parser("token", help="Get a JWT token")
    token_parser.add_argument("--user", required=True, help="User/client ID")
    token_parser.add_argument("--secret", required=True, help="Client secret")
    token_parser.add_argument("--role", default="clinician", help="Role (clinician/admin)")

    # create-visit
    cv_parser = subparsers.add_parser("create-visit", help="Create a new visit")
    cv_parser.add_argument("--patient", required=True, help="Patient ID")
    cv_parser.add_argument("--clinician", required=True, help="Clinician ID")

    # get-visit
    gv_parser = subparsers.add_parser("get-visit", help="Get visit details")
    gv_parser.add_argument("--visit-id", required=True, help="Visit UUID")

    # status
    st_parser = subparsers.add_parser("status", help="Get visit status")
    st_parser.add_argument("--visit-id", required=True, help="Visit UUID")

    # transcribe
    tr_parser = subparsers.add_parser("transcribe", help="Transcribe audio")
    tr_parser.add_argument("--visit-id", required=True, help="Visit UUID")
    tr_parser.add_argument("--audio", required=True, help="Path to audio file")

    # structure
    sr_parser = subparsers.add_parser("structure", help="Structure transcript into note")
    sr_parser.add_argument("--visit-id", required=True, help="Visit UUID")

    # process (full pipeline)
    pr_parser = subparsers.add_parser("process", help="Full pipeline: audio → note")
    pr_parser.add_argument("--visit-id", required=True, help="Visit UUID")
    pr_parser.add_argument("--audio", required=True, help="Path to audio file")

    # approve
    ap_parser = subparsers.add_parser("approve", help="Approve a clinical note")
    ap_parser.add_argument("--visit-id", required=True, help="Visit UUID")
    ap_parser.add_argument("--approved-by", required=True, help="Who is approving")

    # audit
    au_parser = subparsers.add_parser("audit", help="Get audit trail")
    au_parser.add_argument("--visit-id", required=True, help="Visit UUID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cli = MedScribeCLI(base_url=args.url, token=args.token)

    try:
        cmd = args.command
        if cmd == "health":
            _print_json(cli.health())
        elif cmd == "token":
            token = cli.get_token(args.user, args.secret, args.role)
            print(f"Token: {token}")
        elif cmd == "create-visit":
            _print_json(cli.create_visit(args.patient, args.clinician))
        elif cmd == "get-visit":
            _print_json(cli.get_visit(args.visit_id))
        elif cmd == "status":
            _print_json(cli.get_status(args.visit_id))
        elif cmd == "transcribe":
            _print_json(cli.transcribe(args.visit_id, args.audio))
        elif cmd == "structure":
            _print_json(cli.structure(args.visit_id))
        elif cmd == "process":
            _print_json(cli.process(args.visit_id, args.audio))
        elif cmd == "approve":
            _print_json(cli.approve(args.visit_id, args.approved_by))
        elif cmd == "audit":
            _print_json(cli.audit(args.visit_id))

    except httpx.HTTPStatusError as e:
        print(f"Error {e.response.status_code}: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except httpx.ConnectError:
        print(f"Cannot connect to {args.url}. Is the server running?", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
