"""Tests for DELETE /api/users/{uid}/hard cascade endpoint."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: read from frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"

ADMIN_LOGIN = "Igor"
ADMIN_PASS = "02578491"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"login": ADMIN_LOGIN, "password": ADMIN_PASS})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    s.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    s.admin_id = data["id"]
    return s


@pytest.fixture
def temp_employee(admin_session):
    ts = int(time.time() * 1000)
    login = f"qa_delete_{ts}"
    password = "QaPass@2026"
    r = admin_session.post(f"{API}/users", json={
        "login": login, "password": password, "name": f"QA Delete {ts}",
        "role": "vendedor", "active": True,
    })
    assert r.status_code == 200, r.text
    u = r.json()
    u["password"] = password
    return u


def _login_as(login, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


# ---------- Core cascade ----------
def test_cascade_delete_employee_with_sales_and_vales(admin_session, temp_employee):
    uid = temp_employee["id"]
    emp_sess = _login_as(temp_employee["login"], temp_employee["password"])

    # Create a sale as the employee
    sale_payload = {
        "customer_name": f"TEST_Cust_{uid[:6]}",
        "customer_phone": f"5500000{uid[:6]}",
        "items": [{"product_id": "p1", "product_name": "Item QA", "quantity": 1,
                    "unit_price": 10.0, "subtotal": 10.0}],
        "total": 10.0, "paid": 0,
    }
    r = emp_sess.post(f"{API}/sales", json=sale_payload)
    assert r.status_code == 200, r.text
    sale_id = r.json()["id"]

    # Create a vale for this employee (as admin)
    r = admin_session.post(f"{API}/vales", json={"user_id": uid, "amount": 25.0, "notes": "TEST"})
    assert r.status_code == 200, r.text
    vale_id = r.json()["id"]

    # Snapshot other users count & other sales count
    users_before = admin_session.get(f"{API}/users").json()
    sales_before = admin_session.get(f"{API}/sales").json()
    other_users_before = [u for u in users_before if u["id"] != uid]
    other_sales_before = [s for s in sales_before if s["id"] != sale_id]

    # Cascade delete
    r = admin_session.delete(f"{API}/users/{uid}/hard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["deleted_sales"] >= 1
    assert body["deleted_vales"] >= 1
    assert "deleted_shopee_orders" in body

    # Verify employee is gone
    users_after = admin_session.get(f"{API}/users").json()
    assert all(u["id"] != uid for u in users_after)

    # Verify sale is gone
    sales_after = admin_session.get(f"{API}/sales").json()
    assert all(s["id"] != sale_id for s in sales_after)

    # Verify vales for user are gone
    r = admin_session.get(f"{API}/vales", params={"user_id": uid})
    assert r.status_code == 200
    assert r.json() == []

    # Verify other users/sales untouched
    other_users_after_ids = {u["id"] for u in users_after}
    for u in other_users_before:
        assert u["id"] in other_users_after_ids, f"Lost user {u['id']}"
    other_sales_after_ids = {s["id"] for s in sales_after}
    for s in other_sales_before:
        assert s["id"] in other_sales_after_ids, f"Lost sale {s['id']}"


# ---------- Security ----------
def test_non_admin_cannot_cascade_delete(admin_session, temp_employee):
    emp_sess = _login_as(temp_employee["login"], temp_employee["password"])
    # Try to delete admin
    r = emp_sess.delete(f"{API}/users/{admin_session.admin_id}/hard")
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
    # cleanup temp employee
    admin_session.delete(f"{API}/users/{temp_employee['id']}/hard")


def test_unauthenticated_cannot_cascade_delete(admin_session, temp_employee):
    r = requests.delete(f"{API}/users/{temp_employee['id']}/hard")
    assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
    admin_session.delete(f"{API}/users/{temp_employee['id']}/hard")


def test_admin_cannot_delete_self(admin_session):
    r = admin_session.delete(f"{API}/users/{admin_session.admin_id}/hard")
    assert r.status_code == 400, r.text
    assert "próprio" in r.text.lower() or "own" in r.text.lower()


def test_missing_uid_returns_404(admin_session):
    r = admin_session.delete(f"{API}/users/nonexistent-id-xyz/hard")
    assert r.status_code == 404


# ---------- Regression ----------
def test_regression_users_and_login_still_work(admin_session, temp_employee):
    # list users
    r = admin_session.get(f"{API}/users")
    assert r.status_code == 200
    # update user
    r = admin_session.put(f"{API}/users/{temp_employee['id']}", json={"name": "QA Updated"})
    assert r.status_code == 200
    assert r.json()["name"] == "QA Updated"
    # delete temp user
    r = admin_session.delete(f"{API}/users/{temp_employee['id']}/hard")
    assert r.status_code == 200
    # admin login still works
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"login": ADMIN_LOGIN, "password": ADMIN_PASS})
    assert r.status_code == 200
