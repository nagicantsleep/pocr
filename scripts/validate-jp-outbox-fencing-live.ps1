$ErrorActionPreference = "Stop"
$compose = @("-p", "pocr-proof", "-f", "docker-compose.cpu.yml", "--profile", "structured")

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $Arguments failed"
    }
}

function Test-ServiceRunning {
    param([string]$Service)

    $runningServices = @(
        & docker compose @compose ps --status running --services
    )
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose ps failed"
    }
    return $runningServices -contains $Service
}

$workerWasRunning = Test-ServiceRunning "invoice-outbox-worker"

if ($workerWasRunning) {
    Invoke-Compose stop invoice-outbox-worker
}

try {
    @'
from uuid import uuid4

from app.repositories.invoice_repository import InvoiceRepository


repo = InvoiceRepository()
repo.ensure_schema()
event_id = f"proof-fence-{uuid4().hex}"
subscription_id = f"proof-sub-{uuid4().hex}"

try:
    with repo._conn() as conn:
        conn.execute(
            """
            INSERT INTO invoice_outbox (id, tenant_id, invoice_id, event_type, payload_json)
            VALUES (%s, %s, NULL, %s, %s::jsonb)
            """,
            (event_id, "tenant-a", "proof.fence", "{}"),
        )
        conn.execute(
            """
            INSERT INTO invoice_webhook_subscriptions
                (id, tenant_id, url, event_types_json, active)
            VALUES (%s, %s, %s, %s::jsonb, TRUE)
            """,
            (subscription_id, "tenant-a", "https://example.invalid/proof", '["proof.fence"]'),
        )
        conn.execute(
            """
            INSERT INTO invoice_webhook_deliveries (event_id, subscription_id, status)
            VALUES (%s, %s, 'pending')
            """,
            (event_id, subscription_id),
        )

    claimed = next(
        item
        for item in repo.claim_pending_outbox(limit=50, lease_seconds=60)
        if item["id"] == event_id
    )
    first_outbox_lease = claimed["lease_token"]
    with repo._conn() as conn:
        conn.execute(
            "UPDATE invoice_outbox SET claimed_until = NOW() - INTERVAL '1 second' WHERE id = %s",
            (event_id,),
        )
    reclaimed = next(
        item
        for item in repo.claim_pending_outbox(limit=50, lease_seconds=60)
        if item["id"] == event_id
    )
    assert reclaimed["lease_token"] != first_outbox_lease
    assert repo.mark_outbox_published(event_id, first_outbox_lease) is False
    assert repo.mark_outbox_published(event_id, reclaimed["lease_token"]) is True

    first_receipt_lease = repo.claim_consumer_receipt(
        event_id, "proof-consumer", lease_seconds=60
    )
    assert first_receipt_lease
    with repo._conn() as conn:
        conn.execute(
            """
            UPDATE invoice_consumer_receipts
            SET claimed_until = NOW() - INTERVAL '1 second'
            WHERE event_id = %s AND consumer = %s
            """,
            (event_id, "proof-consumer"),
        )
    second_receipt_lease = repo.claim_consumer_receipt(
        event_id, "proof-consumer", lease_seconds=60
    )
    assert second_receipt_lease and second_receipt_lease != first_receipt_lease
    assert repo.complete_consumer_receipt(
        event_id, "proof-consumer", first_receipt_lease
    ) is False
    assert repo.complete_consumer_receipt(
        event_id, "proof-consumer", second_receipt_lease
    ) is True

    first_webhook_lease = repo.claim_webhook_delivery(
        event_id=event_id, subscription_id=subscription_id, lease_seconds=60
    )
    assert first_webhook_lease
    with repo._conn() as conn:
        conn.execute(
            """
            UPDATE invoice_webhook_deliveries
            SET claimed_until = NOW() - INTERVAL '1 second'
            WHERE event_id = %s AND subscription_id = %s
            """,
            (event_id, subscription_id),
        )
    second_webhook_lease = repo.claim_webhook_delivery(
        event_id=event_id, subscription_id=subscription_id, lease_seconds=60
    )
    assert second_webhook_lease and second_webhook_lease != first_webhook_lease
    assert repo.complete_webhook_delivery(
        event_id=event_id,
        subscription_id=subscription_id,
        lease_token=first_webhook_lease,
        response_code=200,
    ) is False
    assert repo.complete_webhook_delivery(
        event_id=event_id,
        subscription_id=subscription_id,
        lease_token=second_webhook_lease,
        response_code=200,
    ) is True
    print(
        f"PASS event_id={event_id} outbox_fence=stale_rejected "
        "consumer_fence=stale_rejected webhook_fence=stale_rejected"
    )
finally:
    with repo._conn() as conn:
        conn.execute("DELETE FROM invoice_webhook_deliveries WHERE event_id = %s", (event_id,))
        conn.execute("DELETE FROM invoice_webhook_subscriptions WHERE id = %s", (subscription_id,))
        conn.execute("DELETE FROM invoice_consumer_receipts WHERE event_id = %s", (event_id,))
        conn.execute("DELETE FROM invoice_outbox WHERE id = %s", (event_id,))
'@ | & docker compose @compose exec -T ocr-api-cpu python -
    if ($LASTEXITCODE -ne 0) {
        throw "Live PostgreSQL fencing proof failed"
    }
} finally {
    if ($workerWasRunning) {
        Invoke-Compose start invoice-outbox-worker
        $deadline = (Get-Date).AddSeconds(30)
        do {
            if (Test-ServiceRunning "invoice-outbox-worker") {
                break
            }
            Start-Sleep -Seconds 1
        } while ((Get-Date) -lt $deadline)
        if (-not (Test-ServiceRunning "invoice-outbox-worker")) {
            throw "invoice-outbox-worker did not return to running state"
        }
    }
}
