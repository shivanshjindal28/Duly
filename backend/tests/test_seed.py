from sqlalchemy import func, select

from app.core.crypto import decrypt_str, encrypt_str, mask_account
from app.models import Organisation, Supplier, User
from app.core.enums import Role
from app.validation.gstin import is_valid_gstin


def test_seed_counts_and_roles(db):
    assert db.scalar(select(func.count()).select_from(Organisation)) == 1
    assert db.scalar(select(func.count()).select_from(Supplier)) == 6
    roles = set(db.scalars(select(User.role)).all())
    assert roles == {r.value for r in Role}


def test_seed_data_is_synthetic_with_valid_gstins(db):
    for s in db.scalars(select(Supplier)):
        assert s.is_synthetic
        assert is_valid_gstin(s.gstin)
        assert s.gstin[2:12] == s.pan


def test_bank_accounts_encrypted_at_rest(db):
    s = db.scalars(select(Supplier)).first()
    plain = decrypt_str(s.bank_account_enc)
    assert plain.isdigit() and plain.endswith(s.bank_account_last4)
    assert plain not in s.bank_account_enc


def test_crypto_roundtrip_and_mask():
    assert decrypt_str(encrypt_str("123456789012")) == "123456789012"
    assert mask_account("123456784417") == "XXXXXXXX4417"


def test_approvers_have_mfa_and_levels(db):
    approvers = db.scalars(select(User).where(User.role == Role.APPROVER)).all()
    assert sorted(a.approver_level for a in approvers) == [1, 2, 3]
    assert all(a.mfa_enabled and a.mfa_secret_enc for a in approvers)
