[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [string]$OperatorToken = "tenant-b-token",
    [string]$TenantId = "tenant-b"
)

$ErrorActionPreference = "Stop"
$compose = @("-p", "pocr-proof", "-f", "docker-compose.cpu.yml", "--profile", "structured")
$baseUrl = "http://localhost:$ApiPort"
$runId = [guid]::NewGuid().ToString("N")
$session = "jp-console-$runId"
$headers = @{ Authorization = "Bearer $OperatorToken" }

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $Arguments failed"
    }
}

function Invoke-Playwright {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & npx --yes --package @playwright/cli playwright-cli @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "playwright-cli $Arguments failed"
    }
}

function Invoke-PlaywrightCode {
    param([string]$Code)
    $codeFile = Join-Path $env:TEMP "pocr-playwright-$runId.js"
    try {
        Set-Content -LiteralPath $codeFile -Value "async (page) => { $Code }" -NoNewline
        Invoke-Playwright --session $session run-code --filename $codeFile
    } finally {
        Remove-Item -LiteralPath $codeFile -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-PythonInApi {
    param(
        [string]$Script,
        [hashtable]$Environment
    )
    $environmentArgs = @()
    foreach ($entry in $Environment.GetEnumerator()) {
        $environmentArgs += @("-e", "$($entry.Key)=$($entry.Value)")
    }
    $output = $Script | & docker compose @compose exec -T @environmentArgs ocr-api-cpu python -
    if ($LASTEXITCODE -ne 0) {
        throw "Durable stack Python command failed"
    }
    return $output
}

function New-Documents {
    param(
        [string]$Prefix,
        [int]$Count
    )
    $script = @'
import json
import os

from app.repositories.invoice_repository import InvoiceRepository

prefix = os.environ["CONSOLE_PROOF_PREFIX"]
count = int(os.environ["CONSOLE_PROOF_COUNT"])
repo = InvoiceRepository()
repo.ensure_schema()
ids = []

with repo._conn() as conn:
    for index in range(1, count + 1):
        invoice_id = f"{prefix}-{index:03d}"
        extracted = {
            "issuer_name": {"value": f"Console Proof {index}"},
            "invoice_number": {"value": f"CONSOLE-{index:03d}"},
            "total_amount": {"value": 1000 + index},
        }
        metadata = {
            "_durable_document": {
                "document_type": "invoice_jp",
                "confidence": 0.5,
                "needs_review": True,
                "reviewed_by": None,
                "review_reason": None,
            }
        }
        conn.execute(
            """
            INSERT INTO invoices (
                id, tenant_id, source_file_path, issuer_name, invoice_number,
                total_amount, raw_ocr_json, extracted_json, validation_json,
                review_status, document_version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, '{}'::jsonb, %s::jsonb, %s::jsonb,
                'needs_review', 1
            )
            """,
            (
                invoice_id,
                os.environ["CONSOLE_PROOF_TENANT_ID"],
                f"console-proof://{prefix}/{index}",
                f"Console Proof {index}",
                f"CONSOLE-{index:03d}",
                1000 + index,
                json.dumps(extracted),
                json.dumps(metadata),
            ),
        )
        ids.append(invoice_id)

print(json.dumps(ids))
'@
    $output = Invoke-PythonInApi -Script $script -Environment @{
        CONSOLE_PROOF_PREFIX = $Prefix
        CONSOLE_PROOF_COUNT = $Count
        CONSOLE_PROOF_TENANT_ID = $TenantId
    }
    return (($output | Select-Object -Last 1) | ConvertFrom-Json)
}

function Remove-Documents {
    param([string]$Prefix)
    $script = @'
import os

from app.repositories.invoice_repository import InvoiceRepository

prefix = os.environ["CONSOLE_PROOF_PREFIX"] + "%"
repo = InvoiceRepository()
repo.ensure_schema()

with repo._conn() as conn:
    conn.execute(
        """
        DELETE FROM invoice_webhook_deliveries
        WHERE event_id IN (
            SELECT id FROM invoice_outbox WHERE invoice_id LIKE %s
        )
        """,
        (prefix,),
    )
    conn.execute(
        """
        DELETE FROM invoice_consumer_receipts
        WHERE event_id IN (
            SELECT id FROM invoice_outbox WHERE invoice_id LIKE %s
        )
        """,
        (prefix,),
    )
    conn.execute("DELETE FROM invoice_outbox WHERE invoice_id LIKE %s", (prefix,))
    conn.execute("DELETE FROM invoice_search_chunks WHERE invoice_id LIKE %s", (prefix,))
    conn.execute("DELETE FROM invoice_audit_logs WHERE invoice_id LIKE %s", (prefix,))
    conn.execute("DELETE FROM invoices WHERE id LIKE %s", (prefix,))
'@
    [void](Invoke-PythonInApi -Script $script -Environment @{
        CONSOLE_PROOF_PREFIX = $Prefix
    })
}

function Assert-DatabaseProof {
    param(
        [string]$Prefix,
        [int]$ExpectedApproved,
        [int]$ExpectedRejected,
        [switch]$RequirePatched
    )
    $script = @'
import json
import os

from app.repositories.invoice_repository import InvoiceRepository

prefix = os.environ["CONSOLE_PROOF_PREFIX"] + "%"
expected_approved = int(os.environ["CONSOLE_PROOF_APPROVED"])
expected_rejected = int(os.environ["CONSOLE_PROOF_REJECTED"])
require_patched = os.environ["CONSOLE_PROOF_PATCHED"] == "true"
repo = InvoiceRepository()
repo.ensure_schema()

with repo._conn() as conn:
    rows = conn.execute(
        """
        SELECT id, review_status, extracted_json
        FROM invoices
        WHERE id LIKE %s
        ORDER BY id
        """,
        (prefix,),
    ).fetchall()
    audit_rows = conn.execute(
        """
        SELECT action, COUNT(*)
        FROM invoice_audit_logs
        WHERE invoice_id LIKE %s
        GROUP BY action
        """,
        (prefix,),
    ).fetchall()

statuses = [row[1] for row in rows]
audits = {row[0]: row[1] for row in audit_rows}
assert statuses.count("reviewed") == expected_approved, (statuses, expected_approved)
assert statuses.count("rejected") == expected_rejected, (statuses, expected_rejected)
assert audits.get("approve", 0) == expected_approved, (audits, expected_approved)
assert audits.get("reject", 0) == expected_rejected, (audits, expected_rejected)
if require_patched:
    assert any(
        (row[2] or {}).get("invoice_number") == "PATCHED-BY-CONSOLE-PROOF"
        or (row[2] or {}).get("invoice_number", {}).get("value") == "PATCHED-BY-CONSOLE-PROOF"
        for row in rows
    ), rows
    assert audits.get("patch", 0) == 1, audits

print(json.dumps({
    "documents": len(rows),
    "approved": expected_approved,
    "rejected": expected_rejected,
    "audits": audits,
}))
'@
    $output = Invoke-PythonInApi -Script $script -Environment @{
        CONSOLE_PROOF_PREFIX = $Prefix
        CONSOLE_PROOF_APPROVED = $ExpectedApproved
        CONSOLE_PROOF_REJECTED = $ExpectedRejected
        CONSOLE_PROOF_PATCHED = $RequirePatched.IsPresent.ToString().ToLowerInvariant()
    }
    return (($output | Select-Object -Last 1) | ConvertFrom-Json)
}

function Open-Console {
    Invoke-Playwright --session $session open "$baseUrl/console/review"
    $tokenJson = $OperatorToken | ConvertTo-Json -Compress
    $script = @'
await page.getByLabel("Operator bearer token").fill(TOKEN_JSON);
await page.getByLabel("Operator bearer token").dispatchEvent("change");
await page.waitForTimeout(1000);
if (await page.locator("#docCount").textContent() === "0") {
    throw new Error("Token reload did not load any needs-review documents");
}
await page.locator(".doc-item").first().click();
'@.Replace("TOKEN_JSON", $tokenJson)
    Invoke-PlaywrightCode $script
}

$gatePrefix = "console-proof-$runId-gate"
$timingPrefix = "console-proof-$runId-timing"

try {
    if ((Invoke-WebRequest -UseBasicParsing "$baseUrl/health/live" -TimeoutSec 5).StatusCode -ne 200) {
        throw "Durable API is not live at $baseUrl"
    }
    Invoke-Compose ps --status running --services | Out-Null
    $existing = Invoke-RestMethod -Uri "$baseUrl/v1/documents?review_status=needs_review&limit=50" -Headers $headers
    if ($existing.total -ne 0) {
        throw "Tenant $TenantId already has $($existing.total) needs-review documents; use an isolated proof tenant"
    }

    [void](New-Documents -Prefix $gatePrefix -Count 3)
    Open-Console
    $gateScript = @'
if (await page.locator("#docCount").textContent() !== "3") {
    throw new Error("Expected three gate documents");
}
const firstId = await page.locator("#detailDocId").textContent();
await page.keyboard.press("j");
await page.waitForTimeout(100);
if ((await page.locator("#detailDocId").textContent()).trim() === firstId.trim()) {
    throw new Error("J did not select the next document");
}
await page.keyboard.press("k");
await page.waitForTimeout(100);
if ((await page.locator("#detailDocId").textContent()).trim() !== firstId.trim()) {
    throw new Error("K did not restore the prior document");
}

await page.keyboard.press("p");
await page.waitForSelector("#patchOverlay", { state: "visible" });
await page.locator("#patchField").fill("invoice_number");
await page.locator("#patchValue").fill("PATCHED-BY-CONSOLE-PROOF");
await page.locator("#patchReason").fill("console-proof-patch");
'@
    Invoke-PlaywrightCode $gateScript
    $patchSubmitScript = @'
await page.keyboard.press("Control+Enter");
await page.waitForSelector("#patchOverlay", { state: "hidden" });
await page.waitForTimeout(500);
'@
    Invoke-PlaywrightCode $patchSubmitScript
    $gateActionsScript = @'
await page.waitForTimeout(500);

await page.locator(".doc-item").first().click();
await page.keyboard.press("r");
await page.waitForSelector("#modalOverlay", { state: "visible" });
await page.locator("#modalReason").fill("console-proof-reject");
await page.keyboard.press("Control+Enter");
await page.waitForSelector("#modalOverlay", { state: "hidden" });
await page.waitForFunction(
    () => Number(document.querySelector("#docCount").textContent) === 2,
    { timeout: 10000 }
);
if (await page.locator("#docCount").textContent() !== "2") {
    throw new Error("R/Ctrl+Enter did not remove the rejected document");
}

await page.locator(".doc-item").first().click();
await page.keyboard.press("a");
await page.waitForSelector("#modalOverlay", { state: "visible" });
await page.locator("#modalReason").fill("console-proof-approve");
await page.keyboard.press("Control+Enter");
await page.waitForSelector("#modalOverlay", { state: "hidden" });
await page.waitForFunction(
    () => Number(document.querySelector("#docCount").textContent) === 1,
    { timeout: 10000 }
);
if (await page.locator("#docCount").textContent() !== "1") {
    throw new Error("A/Ctrl+Enter did not remove the approved document");
}
'@
    Invoke-PlaywrightCode $gateActionsScript
    $gateProof = Assert-DatabaseProof -Prefix $gatePrefix -ExpectedApproved 1 -ExpectedRejected 1 -RequirePatched
    Remove-Documents -Prefix $gatePrefix

    [void](New-Documents -Prefix $timingPrefix -Count 50)
    Open-Console
    $timingScript = @'
if (Number(await page.locator("#docCount").textContent()) !== 50) {
    throw new Error("Expected fifty timing documents");
}
for (let expected = 49; expected >= 0; expected -= 1) {
    await page.locator(".doc-item").first().click();
    await page.keyboard.press("a");
    await page.waitForSelector("#modalOverlay", { state: "visible" });
    await page.locator("#modalReason").fill("console-workflow-timing");
    await page.keyboard.press("Control+Enter");
    await page.waitForSelector("#modalOverlay", { state: "hidden" });
    await page.waitForFunction(
        expectedCount => Number(document.querySelector("#docCount").textContent) === expectedCount,
        expected,
        { timeout: 10000 }
    );
    if (Number(await page.locator("#docCount").textContent()) !== expected) {
        throw new Error("A/Ctrl+Enter did not advance the 50-document workflow");
    }
}
'@
    $timer = [Diagnostics.Stopwatch]::StartNew()
    Invoke-PlaywrightCode $timingScript
    $timer.Stop()
    if ($timer.Elapsed.TotalMinutes -gt 30) {
        throw "50-document workflow exceeded 30 minutes: $($timer.Elapsed)"
    }
    $timingProof = Assert-DatabaseProof -Prefix $timingPrefix -ExpectedApproved 50 -ExpectedRejected 0

    Write-Output (
        "PASS run_id=$runId shortcuts=R,J,K,P timing_documents=$($timingProof.documents) " +
        "elapsed=$($timer.Elapsed) gate_audits=$($gateProof.audits | ConvertTo-Json -Compress)"
    )
}
finally {
    Invoke-Playwright --session $session close 2>$null
    Remove-Documents -Prefix $gatePrefix
    Remove-Documents -Prefix $timingPrefix
}
