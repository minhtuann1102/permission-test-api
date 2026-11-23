import json
import re

import swagger_spec_validator.validator20
from fastapi.routing import APIRoute

from app import app
from permapp.swagger import build_swagger

EXCLUDED = {"/", "/swagger.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def test_valid_swagger_20():
    spec = build_swagger("example.vercel.app")
    swagger_spec_validator.validator20.validate_spec(spec)
    assert spec["swagger"] == "2.0" and spec["schemes"] == ["https"] and spec["host"] == "example.vercel.app"


def test_every_route_documented():
    spec = build_swagger("h")
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path not in EXCLUDED:
            for m in r.methods - {"HEAD"}:
                assert m.lower() in spec["paths"][r.path], (m, r.path)


def test_no_undocumented_extra_paths():
    spec = build_swagger("h")
    routes = {(r.path, m.lower()) for r in app.routes if isinstance(r, APIRoute) for m in r.methods - {"HEAD"}}
    for path, ops in spec["paths"].items():
        for method in ops:
            assert (path, method) in routes, (method, path)


def test_operation_rules():
    spec = build_swagger("h")
    ids = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            ids.append(op["operationId"])
            assert re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", op["operationId"])
            assert op["summary"] and op["description"] and "200" in op["responses"]
            if path != "/health":
                assert any(p["in"] == "header" and p["name"] == "X-API-Key" and p["required"] for p in op["parameters"])
            for p in op.get("parameters", []):
                if p["in"] == "path":
                    assert p["required"] is True
    assert len(ids) == len(set(ids))
    text = json.dumps(spec)
    for banned in ('"oneOf"', '"anyOf"', '"nullable"'):
        assert banned not in text


def test_endpoint_uses_forwarded_host(client):
    r = client.get("/swagger.json", headers={"x-forwarded-host": "perm.vercel.app"})
    assert r.status_code == 200 and r.json()["host"] == "perm.vercel.app"


def test_endpoint_prefers_public_host_and_strips_scheme(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_HOST", "https://perm.example.com/")
    assert client.get("/swagger.json").json()["host"] == "perm.example.com"
