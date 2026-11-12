"""Runs last (file name): after every other test has written events, the chain must still verify."""
from app.core import audit


def test_audit_chain_intact_after_whole_suite(db):
    r = audit.verify(db)
    assert r.ok, (r.broken_at_id, r.problem)
    assert r.events > 100
