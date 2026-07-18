[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$compose = @("-p", "pocr-proof", "-f", "docker-compose.cpu.yml", "--profile", "structured")
$subscriptionId = $null
$documentId = $null
$eventId = $null
$workerWasRunning = $false
$originalWebhookAllowedHosts = $null
$webhookAllowlistChanged = $false

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $Arguments failed"
    }
}

function Invoke-DatabaseScalar {
    param([string]$Sql)
    $result = @(& docker compose @compose exec -T postgres psql -U pocr -d pocr -At -F "|" -c $Sql)
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL query failed"
    }
    return @($result | Where-Object { $_ -and $_.Trim() })
}

function Test-ServiceRunning {
    param([string]$Service)
    $runningServices = @(& docker compose @compose ps --status running --services)
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose ps failed"
    }
    return $runningServices -contains $Service
}

function Remove-DocumentArtifacts {
    param([string]$Id)
    if (-not $Id) {
        return
    }
    & docker compose @compose run --rm --no-deps --entrypoint /bin/sh minio-init -ec @"
mc alias set local http://minio:9000 "`$MINIO_ROOT_USER" "`$MINIO_ROOT_PASSWORD" >/dev/null
mc rm --recursive --force "local/`${STORAGE_S3_BUCKET}/documents/$Id" >/dev/null 2>&1 || true
"@
    if ($LASTEXITCODE -ne 0) {
        throw "MinIO cleanup failed for document $Id"
    }
}

function Get-Delivery {
    if (-not $subscriptionId) {
        return $null
    }
    $rows = Invoke-DatabaseScalar @"
SELECT delivery.event_id,
       delivery.status,
       delivery.attempts,
       COALESCE(delivery.response_code::TEXT, ''),
       COALESCE(delivery.error, '')
FROM invoice_webhook_deliveries AS delivery
WHERE delivery.subscription_id = '$subscriptionId'
ORDER BY delivery.created_at DESC
LIMIT 1;
"@
    if ($rows.Count -ne 1) {
        return $null
    }
    $values = @($rows)[0].Split("|", 5)
    return @{
        event_id = $values[0]
        status = $values[1]
        attempts = [int]$values[2]
        response_code = $values[3]
        error = $values[4]
    }
}

try {
    # The external receiver is intentionally real HTTPS; the URL switches only
    # after the durable failed-delivery state has been observed.
    $workerWasRunning = Test-ServiceRunning "invoice-outbox-worker"
    $originalWebhookAllowedHosts = @(
        & docker compose @compose exec -T ocr-api-cpu /bin/sh -c 'printf %s "${WEBHOOK_ALLOWED_HOSTS-}"'
    ) -join ""
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot read WEBHOOK_ALLOWED_HOSTS from ocr-api-cpu"
    }
    & docker compose @compose exec -T ocr-api-cpu /bin/sh -ec '[ "$WEBHOOK_ALLOWED_HOSTS" = "httpbin.org" ]'
    $apiAllowsHttpbin = $LASTEXITCODE -eq 0
    if (-not $apiAllowsHttpbin) {
        $env:WEBHOOK_ALLOWED_HOSTS = "httpbin.org"
        Invoke-Compose up -d --no-deps --force-recreate ocr-api-cpu invoice-outbox-worker
        $webhookAllowlistChanged = $true
    }
    if (-not $workerWasRunning) {
        Invoke-Compose start invoice-outbox-worker
    }

    $apiPort = @(& docker compose @compose port ocr-api-cpu 8000)[0]
    if (-not $apiPort) {
        throw "Cannot determine the published API port"
    }
    $apiPort = $apiPort.Trim()
    $portMatch = [regex]::Match($apiPort, ":(\d+)$")
    if (-not $portMatch.Success) {
        throw "Unexpected API port mapping: $apiPort"
    }
    $baseUrl = "http://127.0.0.1:$($portMatch.Groups[1].Value)"
    $healthDeadline = (Get-Date).AddSeconds(60)
    do {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/health/live" -TimeoutSec 5 | Out-Null
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $healthDeadline)
    Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/health/live" -TimeoutSec 5 | Out-Null

    $headers = @{ Authorization = "Bearer tenant-a-token" }
    $subscription = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/v1/webhooks" `
        -Headers $headers `
        -ContentType "application/json" `
        -Body (@{
            url = "https://httpbin.org/status/500"
            events = @("document.extraction_completed")
        } | ConvertTo-Json -Compress)
    $subscriptionId = $subscription.id
    if (-not $subscriptionId) {
        throw "Webhook subscription was not created"
    }

    $fixture = (Resolve-Path "tests/fixtures/invoice-jp/clean/sample_001.png").Path
    $upload = @(
        & curl.exe -sS -w "`n%{http_code}" `
            -H "Authorization: Bearer tenant-a-token" `
            -F "file=@$fixture;type=image/png" `
            "$baseUrl/v1/invoice-jp/extract"
    )
    if ($LASTEXITCODE -ne 0 -or $upload.Count -lt 2) {
        throw "Public extraction upload failed"
    }
    $statusCode = [int]$upload[-1]
    if ($statusCode -ne 200) {
        throw "Expected extraction HTTP 200, got ${statusCode}: $($upload[0..($upload.Count - 2)] -join "`n")"
    }
    $extraction = ($upload[0..($upload.Count - 2)] -join "`n") | ConvertFrom-Json
    $documentId = $extraction.document_id
    if (-not $documentId) {
        throw "Extraction response omitted document_id"
    }

    $failureDeadline = (Get-Date).AddSeconds(45)
    $failedDelivery = $null
    do {
        $candidate = Get-Delivery
        if (
            $candidate -and
            $candidate.status -in @("pending", "processing") -and
            (
                $candidate.error -match "HTTP 500" -or
                $candidate.response_code -eq "500"
            ) -and
            $candidate.attempts -ge 2
        ) {
            $failedDelivery = $candidate
            break
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $failureDeadline)
    if (-not $failedDelivery) {
        throw "No durable failed webhook delivery was observed for subscription $subscriptionId"
    }
    $eventId = $failedDelivery.event_id

    Invoke-DatabaseScalar @"
UPDATE invoice_webhook_subscriptions
SET url = 'https://httpbin.org/status/200', updated_at = NOW()
WHERE id = '$subscriptionId';
"@ | Out-Null

    $recoveryDeadline = (Get-Date).AddSeconds(45)
    $recoveredDelivery = $null
    do {
        $candidate = Get-Delivery
        if (
            $candidate -and
            $candidate.event_id -eq $eventId -and
            $candidate.status -eq "delivered" -and
            $candidate.response_code -eq "200" -and
            $candidate.attempts -gt $failedDelivery.attempts
        ) {
            $recoveredDelivery = $candidate
            break
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $recoveryDeadline)
    if (-not $recoveredDelivery) {
        throw "Webhook delivery did not recover after the receiver returned HTTP 200"
    }
    Write-Output (
        "PASS event_id=$eventId initial_http=500 " +
        "recovered_http=200 claims=$($failedDelivery.attempts)->$($recoveredDelivery.attempts)"
    )
}
finally {
    if (Test-ServiceRunning "invoice-outbox-worker") {
        Invoke-Compose stop invoice-outbox-worker
    }
    if ($documentId) {
        Invoke-DatabaseScalar @"
DELETE FROM invoice_webhook_deliveries
WHERE event_id IN (SELECT id FROM invoice_outbox WHERE invoice_id = '$documentId');
DELETE FROM invoice_consumer_receipts
WHERE event_id IN (SELECT id FROM invoice_outbox WHERE invoice_id = '$documentId');
DELETE FROM invoice_outbox WHERE invoice_id = '$documentId';
"@ 2>$null | Out-Null
    } elseif ($eventId) {
        Invoke-DatabaseScalar "DELETE FROM invoice_webhook_deliveries WHERE event_id = '$eventId'; DELETE FROM invoice_consumer_receipts WHERE event_id = '$eventId'; DELETE FROM invoice_outbox WHERE id = '$eventId';" 2>$null | Out-Null
    }
    if ($subscriptionId) {
        Invoke-DatabaseScalar "DELETE FROM invoice_webhook_deliveries WHERE subscription_id = '$subscriptionId';" 2>$null | Out-Null
        Invoke-DatabaseScalar "DELETE FROM invoice_webhook_subscriptions WHERE id = '$subscriptionId';" 2>$null | Out-Null
    }
    if ($documentId) {
        Invoke-DatabaseScalar "DELETE FROM invoice_search_chunks WHERE invoice_id = '$documentId'; DELETE FROM invoice_audit_logs WHERE invoice_id = '$documentId'; DELETE FROM invoices WHERE id = '$documentId';" 2>$null | Out-Null
        Remove-DocumentArtifacts $documentId
    }
    if ($webhookAllowlistChanged) {
        if ($null -eq $originalWebhookAllowedHosts) {
            Remove-Item Env:WEBHOOK_ALLOWED_HOSTS -ErrorAction SilentlyContinue
        } else {
            $env:WEBHOOK_ALLOWED_HOSTS = $originalWebhookAllowedHosts
        }
        Invoke-Compose up -d --no-deps --force-recreate ocr-api-cpu invoice-outbox-worker
    }
    if ($workerWasRunning) {
        if (-not (Test-ServiceRunning "invoice-outbox-worker")) {
            Invoke-Compose start invoice-outbox-worker
        }
    } elseif (Test-ServiceRunning "invoice-outbox-worker") {
        Invoke-Compose stop invoice-outbox-worker
    }
}
