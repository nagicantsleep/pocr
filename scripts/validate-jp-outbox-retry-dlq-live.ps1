[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$compose = @("-p", "pocr-proof", "-f", "docker-compose.cpu.yml", "--profile", "structured")
$eventId = "proof-retry-$([guid]::NewGuid().ToString('N'))"
$workerWasRunning = $false

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $Arguments failed"
    }
}

function Test-ServiceRunning {
    param([string]$Service)
    $runningServices = @(& docker compose @compose ps --status running --services)
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose ps failed"
    }
    return $runningServices -contains $Service
}

$workerWasRunning = Test-ServiceRunning "invoice-outbox-worker"
if (-not $workerWasRunning) {
    Invoke-Compose start invoice-outbox-worker
    $deadline = (Get-Date).AddSeconds(30)
    do {
        if (Test-ServiceRunning "invoice-outbox-worker") {
            break
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    if (-not (Test-ServiceRunning "invoice-outbox-worker")) {
        throw "invoice-outbox-worker did not start for retry/DLQ proof"
    }
}

try {
    Invoke-Compose exec -T postgres psql -U pocr -d pocr -c `
        "INSERT INTO invoice_outbox (id, tenant_id, invoice_id, event_type, payload_json, published_at) VALUES ('$eventId', 'tenant-a', NULL, 'proof.retry', '{}'::jsonb, NOW());"

    $envelope = @{
        event_id = $eventId
        event_type = "proof.retry"
        tenant_id = "tenant-a"
        invoice_id = $null
        payload = @{}
    } | ConvertTo-Json -Compress
    $envelope | & docker compose @compose exec -T kafka /bin/sh -ec `
        "/opt/kafka/bin/kafka-console-producer.sh --bootstrap-server kafka:9092 --topic invoice.events >/dev/null"
    if ($LASTEXITCODE -ne 0) {
        throw "Kafka source publish failed"
    }

    $deadline = (Get-Date).AddSeconds(45)
    $dlqLines = @()
    do {
        $messages = @(
            & docker compose @compose exec -T kafka /bin/sh -ec `
                "timeout 3 /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic invoice.events.dlq --from-beginning --timeout-ms 2000 2>/dev/null || true"
        )
        $dlqLines = @($messages | Where-Object { $_ -match [regex]::Escape($eventId) })
        if ($dlqLines.Count -gt 0) {
            break
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    if ($dlqLines.Count -ne 1) {
        throw "No DLQ event observed for $eventId"
    }
    $dlq = $dlqLines[0] | ConvertFrom-Json
    if ($dlq.delivery_attempt -ne 4 -or $dlq.last_error -notmatch "event_id, invoice_id, and tenant_id are required") {
        throw "Unexpected DLQ envelope: $($dlqLines[0])"
    }
    Write-Output "PASS event_id=$eventId retries=3 dlq_attempt=4"
}
finally {
    Invoke-Compose exec -T postgres psql -U pocr -d pocr -c `
        "DELETE FROM invoice_consumer_receipts WHERE event_id = '$eventId'; DELETE FROM invoice_outbox WHERE id = '$eventId';" 2>$null
    if (-not $workerWasRunning -and (Test-ServiceRunning "invoice-outbox-worker")) {
        Invoke-Compose stop invoice-outbox-worker
    }
}
