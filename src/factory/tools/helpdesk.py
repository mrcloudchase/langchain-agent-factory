"""Helpdesk tools: stand-ins for a Zendesk-style integration backed by data/helpdesk.json."""

from __future__ import annotations

from langchain_core.tools import tool

from factory.tools._data import load_json


@tool
def lookup_ticket(ticket_id: str) -> str:
    """Fetch a support ticket by ID: subject, customer, status, and the message thread."""
    t = load_json("helpdesk.json").get("tickets", {}).get(ticket_id)
    if not t:
        return f"Ticket {ticket_id} not found."
    thread = "\n".join(f"  {m['from']}: {m['text']}" for m in t["messages"])
    return (
        f"Ticket {ticket_id} | {t['subject']} | status={t['status']} | customer={t['customer']}"
        f" | order={t.get('order_id', '-')}\n{thread}"
    )


@tool
def lookup_customer(email: str) -> str:
    """Fetch a customer profile by email: plan, tenure, lifetime value, and open tickets."""
    c = load_json("helpdesk.json").get("customers", {}).get(email)
    if not c:
        return f"No customer with email {email}."
    return (
        f"{email}: plan={c['plan']} tenure_months={c['tenure_months']} ltv_usd={c['ltv_usd']}"
        f" open_tickets={c['open_tickets']}"
    )


@tool
def lookup_order(order_id: str) -> str:
    """Fetch an order: items, amount, shipping status, and refund eligibility."""
    o = load_json("helpdesk.json").get("orders", {}).get(order_id)
    if not o:
        return f"Order {order_id} not found."
    return (
        f"Order {order_id}: amount_usd={o['amount_usd']} status={o['status']}"
        f" refund_eligible={o['refund_eligible']} items={', '.join(o['items'])}"
    )


@tool
def draft_reply(ticket_id: str, body: str) -> str:
    """Save a draft reply on a ticket for a human agent to review and send. Does not send."""
    return (
        f"Draft saved on {ticket_id} ({len(body)} chars). A human agent will review before sending."
    )


@tool
def escalate_ticket(ticket_id: str, reason: str) -> str:
    """Escalate a ticket to a senior support engineer with a reason."""
    return f"Ticket {ticket_id} escalated to tier 2. Reason: {reason}"


@tool
def issue_refund(order_id: str, amount_usd: float) -> str:
    """Issue a refund against an order. This moves money and always requires human approval."""
    o = load_json("helpdesk.json").get("orders", {}).get(order_id)
    if not o:
        return f"Order {order_id} not found; no refund issued."
    if amount_usd > o["amount_usd"]:
        return f"Refused: {amount_usd} exceeds order amount {o['amount_usd']}."
    return (
        f"Refund of ${amount_usd:.2f} issued on order {order_id}. Confirmation RF-{order_id[-4:]}."
    )
