[CmdletBinding()]
param(
    [int]$ApiPort = 0
)

$ErrorActionPreference = "Stop"
$compose = @("-p", "pocr-proof", "-f", "docker-compose.cpu.yml", "--profile", "structured")

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    return $port
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $Arguments failed"
    }
}

if ($ApiPort -le 0) {
    $ApiPort = if (Test-NetConnection localhost -Port 8000 -InformationLevel Quiet) {
        Get-FreePort
    } else {
        8000
    }
}

$env:POCR_API_PORT = "$ApiPort"
Invoke-Compose up -d --build --force-recreate
$baseUrl = "http://localhost:$ApiPort"
$deadline = (Get-Date).AddSeconds(120)
do {
    try {
        if ((Invoke-WebRequest -UseBasicParsing "$baseUrl/health/live" -TimeoutSec 3).StatusCode -eq 200) {
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)
if ((Invoke-WebRequest -UseBasicParsing "$baseUrl/health/live" -TimeoutSec 3).StatusCode -ne 200) {
    throw "API did not become healthy"
}

$key = "jp-live-$([guid]::NewGuid().ToString('N'))"
$upload = curl.exe -sS -X POST "$baseUrl/v1/invoice-jp/extract" `
    -H "Authorization: Bearer tenant-a-token" `
    -H "Idempotency-Key: $key" `
    -H "X-Lang: ja" `
    -F "file=@tests/fixtures/invoice-jp/clean/sample_001.png;type=image/png"
if ($LASTEXITCODE -ne 0) {
    throw "Upload failed"
}
$created = $upload | ConvertFrom-Json
if ($created.status -ne "completed" -or -not $created.document_id) {
    throw "Extraction did not complete: $upload"
}
$documentId = $created.document_id

$replay = curl.exe -sS -X POST "$baseUrl/v1/invoice-jp/extract" `
    -H "Authorization: Bearer tenant-a-token" `
    -H "Idempotency-Key: $key" `
    -H "X-Lang: ja" `
    -F "file=@tests/fixtures/invoice-jp/clean/sample_001.png;type=image/png" | ConvertFrom-Json
if ($replay.document_id -ne $documentId -or $replay.status -ne "completed") {
    throw "Durable idempotency replay did not return the original document"
}

$tenantBStatus = curl.exe -sS -o NUL -w "%{http_code}" `
    -H "Authorization: Bearer tenant-b-token" "$baseUrl/v1/invoice-jp/$documentId"
if ($tenantBStatus -ne "404") {
    throw "Tenant B can access Tenant A document: HTTP $tenantBStatus"
}

$approve = curl.exe -sS -X POST "$baseUrl/v1/invoice-jp/$documentId/approve" `
    -H "Authorization: Bearer tenant-a-token" `
    -H "X-Reason: live-proof" | ConvertFrom-Json
if ($approve.status -ne "approved") {
    throw "Approve failed"
}

Invoke-Compose restart ocr-api-cpu
$deadline = (Get-Date).AddSeconds(90)
do {
    try {
        if ((Invoke-WebRequest -UseBasicParsing "$baseUrl/health/live" -TimeoutSec 3).StatusCode -eq 200) {
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)
$afterRestart = curl.exe -sS -H "Authorization: Bearer tenant-a-token" "$baseUrl/v1/invoice-jp/$documentId" | ConvertFrom-Json
if ($afterRestart.status -ne "approved") {
    throw "Document was not durable across API restart"
}

$eventJson = & docker compose @compose exec -T postgres psql -U pocr -d pocr -At -c `
    "SELECT json_build_object('event_id', id, 'event_type', event_type, 'tenant_id', tenant_id, 'invoice_id', invoice_id, 'payload', payload_json)::text FROM invoice_outbox WHERE invoice_id = '$documentId' ORDER BY created_at LIMIT 1;"
$before = [int](& docker compose @compose exec -T postgres psql -U pocr -d pocr -At -c `
    "SELECT count(*) FROM invoice_consumer_receipts WHERE event_id IN (SELECT id FROM invoice_outbox WHERE invoice_id = '$documentId') AND state = 'completed';")
$eventJson | & docker compose @compose exec -T kafka /bin/sh -ec `
    "/opt/kafka/bin/kafka-console-producer.sh --bootstrap-server kafka:9092 --topic invoice.events >/dev/null"
Start-Sleep -Seconds 3
$after = [int](& docker compose @compose exec -T postgres psql -U pocr -d pocr -At -c `
    "SELECT count(*) FROM invoice_consumer_receipts WHERE event_id IN (SELECT id FROM invoice_outbox WHERE invoice_id = '$documentId') AND state = 'completed';")
if ($after -ne $before) {
    throw "Duplicate Kafka envelope created a duplicate consumer receipt"
}

$outbox = & docker compose @compose exec -T postgres psql -U pocr -d pocr -At -c `
    "SELECT count(*) FROM invoice_outbox WHERE invoice_id = '$documentId' AND published_at IS NOT NULL;"
if ([int]$outbox -lt 2) {
    throw "Committed document and review events were not published"
}

$objects = & docker run --rm --network paddleocr-network --entrypoint /bin/sh `
    minio/mc:RELEASE.2024-10-08T09-37-26Z -ec `
    "mc alias set local http://minio:9000 pocr-minio pocr-minio-secret >/dev/null; mc ls --recursive local/pocr/documents/$documentId"
if (($objects -notmatch "raw") -or ($objects -notmatch "extracted.json")) {
    throw "Expected immutable object artifacts are missing"
}

Invoke-Compose restart invoice-outbox-worker
Write-Output "PASS document_id=$documentId api_port=$ApiPort receipts=$after published_events=$outbox"
