import json
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_openapi_export_is_valid_and_deterministic() -> None:
    command = [sys.executable, "-m", "app.export_openapi"]
    first = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, check=True, text=True)
    second = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, check=True, text=True)

    assert first.stdout == second.stdout
    schema = json.loads(first.stdout)
    assert {"/api/v1/modules", "/api/v1/users/me", "/api/v1/auth/login"} <= schema["paths"].keys()
    assert "role" in schema["components"]["schemas"]["UserRead"]["properties"]
