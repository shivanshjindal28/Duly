def test_health_reports_db_and_policy(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok"
    assert body["policy_version"] == 1
    assert body["ai_mode"] == "offline"


def test_security_headers_present(client):
    r = client.get("/api/health")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
