[CmdletBinding()]
param(
    [int]$ApiPort = 8000
)

$ErrorActionPreference = "Stop"
$compose = @("-p", "pocr-proof", "-f", "docker-compose.cpu.yml", "--profile", "structured")
$fixture = Join-Path $PSScriptRoot "..\tests\fixtures\invoice-jp\clean\sample_001.png"
$runId = [guid]::NewGuid().ToString("N")
$baseUrl = "http://localhost:$ApiPort"
$createdDocumentIds = [System.Collections.Generic.List[string]]::new()
$proofKeys = [System.Collections.Generic.List[string]]::new()
$traceContainer = "pocr-proof-minio-trace-$runId"
$outboxWorkerWasRunning = $false
$queueTriggerName = "pocr_proof_reject_job_$runId"
$queueFunctionName = "pocr_proof_reject_job_fn_$runId"

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

function Wait-MinIO {
    $deadline = (Get-Date).AddSeconds(60)
    do {
        & docker run --rm --network paddleocr-network --entrypoint /bin/sh `
            minio/mc:RELEASE.2024-10-08T09-37-26Z -ec `
            "mc alias set local http://minio:9000 pocr-minio pocr-minio-secret >/dev/null; mc ls local/pocr >/dev/null"
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "MinIO did not become ready"
}

function Invoke-Psql {
    param([Parameter(Mandatory = $true)][string]$Sql)
    $result = & docker compose @compose exec -T postgres psql -v ON_ERROR_STOP=1 -U pocr -d pocr -At -c $Sql
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL command failed"
    }
    return @($result)
}

function Invoke-PsqlScalarInt {
    param([Parameter(Mandatory = $true)][string]$Sql)
    $values = Invoke-Psql $Sql
    if ($values.Count -ne 1) {
        throw "Expected one PostgreSQL scalar result, got $($values.Count)"
    }
    return [int]($values | Select-Object -First 1)
}

function Invoke-SyncUpload {
    param([Parameter(Mandatory = $true)][string]$Key)
    $response = curl.exe -sS --max-time 120 -X POST "$baseUrl/v1/invoice-jp/extract" `
        -H "Authorization: Bearer tenant-a-token" `
        -H "Idempotency-Key: $Key" `
        -H "X-Lang: ja" `
        -F "file=@$fixture;type=image/png"
    if ($LASTEXITCODE -ne 0) {
        throw "Synchronous upload failed for key $Key"
    }
    return $response | ConvertFrom-Json
}

function Invoke-AsyncUploadStatus {
    param([Parameter(Mandatory = $true)][string]$Key)
    $responseFile = Join-Path $env:TEMP "pocr-$runId-response.json"
    try {
        $status = curl.exe -sS --max-time 120 -o $responseFile -w "%{http_code}" -X POST `
            "$baseUrl/v1/invoice-jp/extract:async" `
            -H "Authorization: Bearer tenant-a-token" `
            -H "Idempotency-Key: $Key" `
            -H "X-Lang: ja" `
            -F "file=@$fixture;type=image/png"
        if ($LASTEXITCODE -ne 0) {
            throw "Asynchronous upload transport failed for key $Key"
        }
        return @{
            Status = [int]$status
            Body = Get-Content -Raw $responseFile
        }
    } finally {
        Remove-Item -LiteralPath $responseFile -Force -ErrorAction SilentlyContinue
    }
}

function Start-MinIOTrace {
    & docker run -d --name $traceContainer --network paddleocr-network --entrypoint /bin/sh `
        minio/mc:RELEASE.2024-10-08T09-37-26Z -ec `
        "mc alias set local http://minio:9000 pocr-minio pocr-minio-secret >/dev/null; exec mc admin trace --json local" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not start MinIO trace"
    }
    Start-Sleep -Milliseconds 500
}

function Stop-MinIOTrace {
    $trace = @(& docker logs $traceContainer 2>&1)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & docker rm -f $traceContainer 2>$null | Out-Null
    $ErrorActionPreference = $previousErrorActionPreference
    return $trace -join "`n"
}

function Remove-ProofData {
    if ($createdDocumentIds.Count -gt 0) {
        $ids = ($createdDocumentIds | ForEach-Object { "'$_'" }) -join ","
        Invoke-Psql @"
DELETE FROM invoice_webhook_deliveries
WHERE event_id IN (SELECT id FROM invoice_outbox WHERE invoice_id IN ($ids));
DELETE FROM invoice_consumer_receipts
WHERE event_id IN (SELECT id FROM invoice_outbox WHERE invoice_id IN ($ids));
DELETE FROM invoice_outbox WHERE invoice_id IN ($ids);
DELETE FROM invoice_audit_logs WHERE invoice_id IN ($ids);
DELETE FROM invoices WHERE id IN ($ids);
"@ | Out-Null
        foreach ($documentId in $createdDocumentIds) {
            & docker run --rm --network paddleocr-network --entrypoint /bin/sh `
                minio/mc:RELEASE.2024-10-08T09-37-26Z -ec `
                "mc alias set local http://minio:9000 pocr-minio pocr-minio-secret >/dev/null; mc rm --recursive --force local/pocr/documents/$documentId >/dev/null 2>&1 || true"
        }
    }
    if ($proofKeys.Count -gt 0) {
        $keys = ($proofKeys | ForEach-Object { "'$_'" }) -join ","
        Invoke-Psql "DELETE FROM invoice_idempotency_records WHERE tenant_id = 'tenant-a' AND idempotency_key IN ($keys);" | Out-Null
    }
}

if (-not (Test-Path -LiteralPath $fixture)) {
    throw "Missing proof fixture: $fixture"
}

try {
    if ((Invoke-WebRequest -UseBasicParsing "$baseUrl/health/live" -TimeoutSec 5).StatusCode -ne 200) {
        throw "Durable API is not live at $baseUrl"
    }
    Wait-MinIO
    $outboxWorkerWasRunning = Test-ServiceRunning "invoice-outbox-worker"
    if ($outboxWorkerWasRunning) {
        Invoke-Compose stop invoice-outbox-worker
    }

    $redisKey = "failure-proof-$runId-redis"
    $proofKeys.Add($redisKey)
    Invoke-Compose stop redis
    $redisOutageCreated = Invoke-SyncUpload $redisKey
    if ($redisOutageCreated.status -ne "completed" -or -not $redisOutageCreated.document_id) {
        throw "Durable sync extraction did not survive Redis outage"
    }
    $createdDocumentIds.Add($redisOutageCreated.document_id)
    Invoke-Compose start redis
    $redisReplay = Invoke-SyncUpload $redisKey
    if ($redisReplay.document_id -ne $redisOutageCreated.document_id -or $redisReplay.status -ne "completed") {
        throw "Redis recovery did not retain durable idempotency replay"
    }

    $contentionKey = "failure-proof-$runId-contention"
    $proofKeys.Add($contentionKey)
    $contentionJobs = @(
        1..2 | ForEach-Object {
            Start-Job -ScriptBlock {
                param($Url, $File, $Key)
                curl.exe -sS --max-time 120 -X POST "$Url/v1/invoice-jp/extract" `
                    -H "Authorization: Bearer tenant-a-token" `
                    -H "Idempotency-Key: $Key" `
                    -H "X-Lang: ja" `
                    -F "file=@$File;type=image/png"
            } -ArgumentList $baseUrl, $fixture, $contentionKey
        }
    )
    try {
        $null = $contentionJobs | Wait-Job -Timeout 180
        if (($contentionJobs | Where-Object State -ne "Completed").Count -ne 0) {
            throw "Concurrent idempotency requests did not complete"
        }
        $contentionResponses = @(
            $contentionJobs |
                Receive-Job |
                ForEach-Object { $_ | ConvertFrom-Json }
        )
    } finally {
        $contentionJobs | Remove-Job -Force -ErrorAction SilentlyContinue
    }
    $contentionDocumentIds = @($contentionResponses | ForEach-Object document_id | Where-Object { $_ } | Sort-Object -Unique)
    if ($contentionResponses.Count -ne 2 -or $contentionDocumentIds.Count -ne 1) {
        throw "Concurrent idempotency requests did not converge on one document"
    }
    $createdDocumentIds.Add($contentionDocumentIds[0])

    $expiryKey = "failure-proof-$runId-expiry"
    $proofKeys.Add($expiryKey)
    $beforeExpiry = Invoke-SyncUpload $expiryKey
    $createdDocumentIds.Add($beforeExpiry.document_id)
    Invoke-Psql "UPDATE invoice_idempotency_records SET expires_at = NOW() - INTERVAL '1 second' WHERE tenant_id = 'tenant-a' AND idempotency_key = '$expiryKey';" | Out-Null
    $afterExpiry = Invoke-SyncUpload $expiryKey
    if ($afterExpiry.document_id -eq $beforeExpiry.document_id -or $afterExpiry.status -ne "completed") {
        throw "Expired idempotency record was not reclaimed"
    }
    $createdDocumentIds.Add($afterExpiry.document_id)

    $rollbackId = "rollback-proof-$runId"
    $rollbackKey = "failure-proof-$runId-rollback"
    $proofKeys.Add($rollbackKey)
    @'
from datetime import datetime, timedelta, timezone
from app.repositories.invoice_repository import InvoiceRepository

repo = InvoiceRepository()
repo.ensure_schema()
tenant_id = "tenant-a"
invoice_id = "__ROLLBACK_ID__"
key = "__ROLLBACK_KEY__"
fingerprint = "rollback-proof-fingerprint"
claimed, _ = repo.claim_idempotency_record(
    tenant_id=tenant_id,
    idempotency_key=key,
    request_fingerprint=fingerprint,
    resource_id=invoice_id,
    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
)
assert claimed
write = {
    "invoice_id": invoice_id,
    "invoice_data": {
        "source": {"file_hash": "proof", "file_path": f"documents/{invoice_id}/raw"},
        "raw_ocr": {"results": []},
        "extracted": {},
        "validation": {},
    },
    "actor": "proof",
    "reason": "forced rollback",
}
try:
    repo.save_invoices_and_complete_idempotency(
        [write, write],
        tenant_id=tenant_id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        resource_id=invoice_id,
        canonical_response={"document_id": invoice_id},
    )
except Exception:
    pass
else:
    raise AssertionError("duplicate primary key did not abort the transaction")
with repo._conn() as conn:
    counts = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM invoices WHERE id = %s),
            (SELECT COUNT(*) FROM invoice_audit_logs WHERE invoice_id = %s),
            (SELECT COUNT(*) FROM invoice_outbox WHERE invoice_id = %s)
        """,
        (invoice_id, invoice_id, invoice_id),
    ).fetchone()
assert counts == (0, 0, 0), counts
print("PASS rollback=invoices_audits_outbox_zero")
'@.Replace("__ROLLBACK_ID__", $rollbackId).Replace("__ROLLBACK_KEY__", $rollbackKey) |
        & docker compose @compose exec -T ocr-api-cpu python -
    if ($LASTEXITCODE -ne 0) {
        throw "Transactional rollback proof failed"
    }

    $storageDownKey = "failure-proof-$runId-storage-down"
    $proofKeys.Add($storageDownKey)
    $storageProofStartedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    Invoke-Compose stop minio
    $storageDown = Invoke-AsyncUploadStatus $storageDownKey
    if ($storageDown.Status -ne 503) {
        throw "Storage outage returned HTTP $($storageDown.Status), expected 503: $($storageDown.Body)"
    }
    Invoke-Compose start minio
    Wait-MinIO
    $storageDownIdempotencyCount = Invoke-PsqlScalarInt "SELECT COUNT(*) FROM invoice_idempotency_records WHERE tenant_id = 'tenant-a' AND idempotency_key = '$storageDownKey';"
    $storageDownJobCount = Invoke-PsqlScalarInt "SELECT COUNT(*) FROM invoice_extraction_jobs WHERE created_at >= '$storageProofStartedAt';"
    if ($storageDownIdempotencyCount -ne 0 -or $storageDownJobCount -ne 0) {
        throw (
            "Storage outage left a durable idempotency or job record: " +
            "idempotency=$storageDownIdempotencyCount jobs_created=$storageDownJobCount"
        )
    }

    $queueFailureKey = "failure-proof-$runId-queue"
    $proofKeys.Add($queueFailureKey)
    $queueRollbackStartedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    $fixtureHash = (Get-FileHash -LiteralPath $fixture -Algorithm SHA256).Hash.ToLowerInvariant()
    Invoke-Psql @"
CREATE OR REPLACE FUNCTION $queueFunctionName() RETURNS trigger AS `$`$
BEGIN
    IF NEW.source_file_hash = '$fixtureHash' THEN
        RAISE EXCEPTION 'forced durable queue rollback';
    END IF;
    RETURN NEW;
END;
`$`$ LANGUAGE plpgsql;
CREATE TRIGGER $queueTriggerName
BEFORE INSERT ON invoice_extraction_jobs
FOR EACH ROW EXECUTE FUNCTION $queueFunctionName();
"@ | Out-Null
    Start-MinIOTrace
    $queueFailure = Invoke-AsyncUploadStatus $queueFailureKey
    $minioTrace = Stop-MinIOTrace
    if ($queueFailure.Status -ne 503) {
        throw "Forced durable queue rollback returned HTTP $($queueFailure.Status), expected 503: $($queueFailure.Body)"
    }
    $traceEvents = @(
        $minioTrace -split "\r?\n" |
            Where-Object { $_.TrimStart().StartsWith("{") } |
            ForEach-Object { $_ | ConvertFrom-Json }
    )
    $sourcePuts = @(
        $traceEvents | Where-Object {
            $_.api -eq "s3.PutObject" -and $_.path -match "^/pocr/jobs/.+/source$"
        }
    )
    if ($sourcePuts.Count -ne 1) {
        throw "MinIO trace expected one source PUT, observed $($sourcePuts.Count)"
    }
    $sourcePath = $sourcePuts[0].path
    $sourceDeletes = @(
        $traceEvents | Where-Object {
            $_.api -eq "s3.DeleteObject" -and $_.path -eq $sourcePath
        }
    )
    if ($sourceDeletes.Count -ne 1 -or [datetime]$sourceDeletes[0].time -lt [datetime]$sourcePuts[0].time) {
        throw "MinIO trace did not prove ordered source PUT then matching DELETE for $sourcePath"
    }
    $queueFailureIdempotencyCount = Invoke-PsqlScalarInt "SELECT COUNT(*) FROM invoice_idempotency_records WHERE tenant_id = 'tenant-a' AND idempotency_key = '$queueFailureKey';"
    $queueFailureJobCount = Invoke-PsqlScalarInt "SELECT COUNT(*) FROM invoice_extraction_jobs WHERE created_at >= '$queueRollbackStartedAt';"
    $queueFailureOutboxCount = Invoke-PsqlScalarInt "SELECT COUNT(*) FROM invoice_outbox WHERE created_at >= '$queueRollbackStartedAt';"
    if (
        $queueFailureIdempotencyCount -ne 0 -or
        $queueFailureJobCount -ne 0 -or
        $queueFailureOutboxCount -ne 0
    ) {
        throw "Queue rollback left a durable idempotency, job, or outbox record"
    }

    Write-Output (
        "PASS run_id=$runId redis_outage=durable_replay idempotency_expiry=reclaimed " +
        "idempotency_contention=one_document db_rollback=zero_outbox storage_outage=503 queue_rollback=minio_put_delete"
    )
}
finally {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & docker rm -f $traceContainer 2>$null | Out-Null
    $ErrorActionPreference = $previousErrorActionPreference
    try {
        Invoke-Psql "DROP TRIGGER IF EXISTS $queueTriggerName ON invoice_extraction_jobs; DROP FUNCTION IF EXISTS $queueFunctionName();" | Out-Null
    } catch {
        Write-Warning "Could not remove the temporary durable-queue proof trigger: $($_.Exception.Message)"
    }
    if (-not (Test-ServiceRunning "minio")) {
        try {
            Invoke-Compose start minio
            Wait-MinIO
        } catch {
            Write-Warning "Could not restore MinIO: $($_.Exception.Message)"
        }
    }
    if (-not (Test-ServiceRunning "redis")) {
        try {
            Invoke-Compose start redis
        } catch {
            Write-Warning "Could not restore Redis: $($_.Exception.Message)"
        }
    }
    try {
        Remove-ProofData
    } catch {
        Write-Warning "Could not remove proof rows: $($_.Exception.Message)"
    }
    if ($outboxWorkerWasRunning -and -not (Test-ServiceRunning "invoice-outbox-worker")) {
        try {
            Invoke-Compose start invoice-outbox-worker
        } catch {
            Write-Warning "Could not restore the outbox worker: $($_.Exception.Message)"
        }
    }
}
