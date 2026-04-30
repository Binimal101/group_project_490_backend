import pytest
import os
from sqlmodel import select

from src.database.payment.models import Invoice, Subscription, BillingCycle, PricingPlan

def test_payment_flows_e2e(test_client, create_client, coach_auth_header, admin_auth_header, db_session):
    """
    Test the full payment flow from coach request, to relationship formation,
    to refreshing payments, and verifying the new endpoints.
    """
    
    # 1. Get Coach ID
    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    assert coach_me.status_code == 200
    coach_id = coach_me.json()["coach_account"]["id"]

    # 2. Create distinct Client and Request Coach
    client_auth_header, client_id = create_client(email_prefix="payment_client")
    req_resp = test_client.post(f"/roles/client/request_coach/{coach_id}", headers=client_auth_header)
    assert req_resp.status_code == 200
    request_id = req_resp.json()["request_id"]

    # 3. Coach Accepts Client (this triggers subscription/invoice creation)
    acc_resp = test_client.post(f"/roles/coach/accept_client/{request_id}", headers=coach_auth_header)
    assert acc_resp.status_code == 200

    # 4. Check Client Invoices and Billing Cycles
    invoices_resp = test_client.get("/roles/client/invoices?skip=0&limit=10", headers=client_auth_header)
    assert invoices_resp.status_code == 200
    invoices_data = invoices_resp.json()["invoices"]
    assert len(invoices_data) == 1
    assert "invoice_id" in invoices_data[0]
    assert invoices_data[0]["amount"] == 30.0
    assert invoices_data[0]["outstanding_balance"] == 30.0

    billing_resp = test_client.get("/roles/client/current_billing_cycles", headers=client_auth_header)
    assert billing_resp.status_code == 200
    billing_data = billing_resp.json()["cycles"]
    assert len(billing_data) == 1
    assert "coach_name" in billing_data[0]
    assert billing_data[0]["active"] is True
    assert billing_data[0]["coach_name"] is not None

    # 5. Check Coach Earnings (should be 0 since outstanding balance == amount)
    earnings_resp = test_client.get("/roles/coach/earnings", headers=coach_auth_header)
    assert earnings_resp.status_code == 200
    assert earnings_resp.json()["total_earnings"] == 0.0

    # 6. Check Admin Transactions (should be 0)
    admin_resp = test_client.get("/roles/admin/total_transactions", headers=admin_auth_header)
    assert admin_resp.status_code == 200
    assert admin_resp.json()["total_transacted"] == 0.0

    # 7. Run /refresh_payments cron job to simulate payment
    os.environ["CRON_SECRET"] = "test-cron-secret"
    refresh_resp = test_client.post("/refresh_payments", json={"cron_secret": "test-cron-secret"})
    assert refresh_resp.status_code == 200

    # 8. Check Invoices again (outstanding balance should be 0 now)
    invoices_resp_after = test_client.get("/roles/client/invoices", headers=client_auth_header)
    assert invoices_resp_after.status_code == 200
    assert invoices_resp_after.json()["invoices"][0]["outstanding_balance"] == 0.0

    # 9. Check Coach Earnings again (should be 50.00 since 5000 cents / 100)
    earnings_resp_after = test_client.get("/roles/coach/earnings", headers=coach_auth_header)
    assert earnings_resp_after.status_code == 200
    
    assert abs(earnings_resp_after.json()["total_earnings"] - 60.0) < 0.1

    # 10. Check Admin Transactions again
    admin_resp_after = test_client.get("/roles/admin/total_transactions", headers=admin_auth_header)
    assert admin_resp_after.status_code == 200
    assert abs(admin_resp_after.json()["total_transacted"] - 60.0) < 0.1
