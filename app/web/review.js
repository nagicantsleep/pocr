// ===== State =====
let documents = [];
let currentIndex = -1;
let pendingAction = null;

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
    loadDocuments();
    bindShortcuts();
    bindSearch();
});

// ===== API Helpers =====
function getActor() {
    return document.getElementById('actorInput').value || 'operator';
}

async function apiFetch(url, options = {}) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`${resp.status}: ${text}`);
    }
    return resp;
}

// ===== Load Documents =====
async function loadDocuments() {
    try {
        const resp = await apiFetch('/v1/documents?review_status=needs_review&limit=50');
        const data = await resp.json();
        documents = data.documents || [];
        renderDocumentList();
        if (documents.length > 0 && currentIndex === -1) {
            selectDocument(0);
        } else if (documents.length === 0) {
            currentIndex = -1;
            showDetailEmpty();
        }
    } catch (err) {
        showToast('Failed to load documents: ' + err.message, 'error');
    }
}

// ===== Render Document List =====
function renderDocumentList() {
    const container = document.getElementById('docListContainer');
    const count = document.getElementById('docCount');
    count.textContent = documents.length;

    if (documents.length === 0) {
        container.innerHTML = '<div class="empty-state">No documents need review</div>';
        return;
    }

    container.innerHTML = documents.map((doc, i) => {
        const conf = doc.confidence ?? 0;
        const confColor = conf >= 0.85 ? '#4caf50' : conf >= 0.7 ? '#ff9800' : '#f44336';
        const amount = doc.total_amount != null ? formatCurrency(doc.total_amount, doc.currency) : '--';
        return `
            <div class="doc-item${i === currentIndex ? ' active' : ''}" onclick="selectDocument(${i})">
                <div class="doc-item-row">
                    <span class="doc-issuer">${escapeHtml(doc.issuer_name || 'Unknown')}</span>
                    <span class="doc-amount">${escapeHtml(amount)}</span>
                </div>
                <div class="doc-meta">
                    <span class="doc-id">${escapeHtml(shortId(doc.document_id || doc.id))}</span>
                    <span><span class="confidence-dot" style="background:${confColor}"></span>${(conf * 100).toFixed(0)}%</span>
                    <span class="status-tag">${escapeHtml(doc.review_status || 'unknown')}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ===== Select Document =====
function selectDocument(index) {
    if (documents.length === 0) return;
    index = Math.max(0, Math.min(index, documents.length - 1));
    currentIndex = index;
    renderDocumentList();
    renderDetail(documents[index]);
}

// ===== Render Detail =====
async function renderDetail(doc) {
    const content = document.getElementById('detailContent');
    const empty = document.getElementById('detailEmpty');
    empty.style.display = 'none';
    content.style.display = 'block';

    const docId = doc.document_id || doc.id;
    document.getElementById('detailIssuerName').textContent = doc.issuer_name || 'Unknown';
    document.getElementById('detailDocId').textContent = docId;
    document.getElementById('detailStatus').textContent = doc.review_status || 'unknown';

    const conf = doc.confidence ?? 0;
    document.getElementById('detailConfidence').textContent = (conf * 100).toFixed(1) + '%';
    document.getElementById('detailConfidence').className = conf >= 0.85 ? 'conf-high' : conf >= 0.7 ? 'conf-medium' : 'conf-low';

    // Fetch full document detail
    let fullDoc = doc;
    try {
        const resp = await apiFetch(`/v1/documents/${docId}`);
        fullDoc = await resp.json();
    } catch (_) {
        // Use the list version if detail fetch fails
    }

    renderFields(fullDoc);
}

function renderFields(doc) {
    const table = document.getElementById('fieldsTable');
    const fields = doc.extracted_fields || doc.fields || {};
    const confidences = doc.field_confidences || {};

    const keys = Object.keys(fields);
    if (keys.length === 0) {
        table.innerHTML = '<div class="empty-state">No extracted fields</div>';
        return;
    }

    table.innerHTML = keys.map(key => {
        const value = fields[key];
        const conf = confidences[key];
        let confHtml = '';
        let rowBg = '';

        if (conf != null) {
            const pct = (conf * 100).toFixed(0);
            const cls = conf >= 0.85 ? 'conf-high' : conf >= 0.7 ? 'conf-medium' : 'conf-low';
            confHtml = `<span class="field-confidence ${cls}">${pct}%</span>`;
            rowBg = conf >= 0.85 ? '#f1f8e9' : conf >= 0.7 ? '#fff8e1' : '#ffebee';
        }

        const displayValue = typeof value === 'object' ? JSON.stringify(value) : String(value ?? '');
        return `
            <div class="field-row" style="background:${rowBg}">
                <span class="field-name">${escapeHtml(key)}</span>
                <span class="field-value">${escapeHtml(displayValue)}</span>
                ${confHtml}
            </div>
        `;
    }).join('');
}

function showDetailEmpty() {
    document.getElementById('detailContent').style.display = 'none';
    document.getElementById('detailEmpty').style.display = 'flex';
}

// ===== Actions =====
function getCurrentDoc() {
    if (currentIndex < 0 || currentIndex >= documents.length) return null;
    return documents[currentIndex];
}

function approve() {
    const doc = getCurrentDoc();
    if (!doc) return;
    pendingAction = 'approve';
    document.getElementById('modalTitle').textContent = 'Approve / 承認 — Reason (optional)';
    document.getElementById('modalReason').value = '';
    document.getElementById('modalOverlay').style.display = 'flex';
    document.getElementById('modalReason').focus();
}

function reject() {
    const doc = getCurrentDoc();
    if (!doc) return;
    pendingAction = 'reject';
    document.getElementById('modalTitle').textContent = 'Reject / 却下 — Reason';
    document.getElementById('modalReason').value = '';
    document.getElementById('modalOverlay').style.display = 'flex';
    document.getElementById('modalReason').focus();
}

async function confirmAction() {
    const doc = getCurrentDoc();
    if (!doc || !pendingAction) return;

    const docId = doc.document_id || doc.id;
    const reason = document.getElementById('modalReason').value;
    const actor = getActor();

    closeModal();

    try {
        await apiFetch(`/v1/documents/${docId}/${pendingAction}`, {
            method: 'POST',
            headers: {
                'X-Actor': actor,
                'X-Reason': reason
            }
        });
        showToast(`Document ${pendingAction === 'approve' ? 'approved' : 'rejected'}`, 'success');
        loadDocuments();
    } catch (err) {
        showToast(`Failed: ${err.message}`, 'error');
    }
    pendingAction = null;
}

function openPatchModal() {
    const doc = getCurrentDoc();
    if (!doc) return;
    document.getElementById('patchField').value = '';
    document.getElementById('patchValue').value = '';
    document.getElementById('patchOverlay').style.display = 'flex';
    document.getElementById('patchField').focus();
}

async function submitPatch() {
    const doc = getCurrentDoc();
    if (!doc) return;

    const docId = doc.document_id || doc.id;
    const field = document.getElementById('patchField').value.trim();
    const value = document.getElementById('patchValue').value;

    if (!field) {
        showToast('Field name is required', 'error');
        return;
    }

    closePatchModal();

    try {
        await apiFetch(`/v1/documents/${docId}/fields`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-Actor': getActor()
            },
            body: JSON.stringify({ [field]: value })
        });
        showToast('Field patched', 'success');
        // Refresh detail
        renderDetail(documents[currentIndex]);
    } catch (err) {
        showToast(`Failed: ${err.message}`, 'error');
    }
}

// ===== Modals =====
function closeModal() {
    document.getElementById('modalOverlay').style.display = 'none';
    pendingAction = null;
}

function closePatchModal() {
    document.getElementById('patchOverlay').style.display = 'none';
}

// ===== Search =====
function bindSearch() {
    const input = document.getElementById('searchInput');
    const btn = document.getElementById('searchBtn');

    btn.addEventListener('click', () => runSearch(input.value));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') runSearch(input.value);
    });
}

async function runSearch(query) {
    if (!query.trim()) {
        loadDocuments();
        return;
    }
    try {
        const resp = await apiFetch(`/v1/search?q=${encodeURIComponent(query)}&mode=hybrid`);
        const data = await resp.json();
        documents = data.results || data.documents || [];
        currentIndex = -1;
        renderDocumentList();
        showDetailEmpty();
    } catch (err) {
        showToast('Search failed: ' + err.message, 'error');
    }
}

// ===== Keyboard Shortcuts =====
function bindShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Don't capture if typing in an input
        const tag = e.target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

        // Don't capture if modal is open
        const modalOpen =
            document.getElementById('modalOverlay').style.display === 'flex' ||
            document.getElementById('patchOverlay').style.display === 'flex';
        if (modalOpen) {
            if (e.key === 'Escape') {
                closeModal();
                closePatchModal();
            }
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                if (document.getElementById('modalOverlay').style.display === 'flex') {
                    confirmAction();
                } else {
                    submitPatch();
                }
            }
            return;
        }

        switch (e.key.toLowerCase()) {
            case 'a':
                e.preventDefault();
                approve();
                break;
            case 'r':
                e.preventDefault();
                reject();
                break;
            case 'j':
                e.preventDefault();
                selectDocument(currentIndex + 1);
                break;
            case 'k':
                e.preventDefault();
                selectDocument(currentIndex - 1);
                break;
            case 'p':
                e.preventDefault();
                openPatchModal();
                break;
            case 'escape':
                closeModal();
                closePatchModal();
                break;
        }
    });
}

// ===== Utilities =====
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function shortId(id) {
    if (!id) return '--';
    return id.length > 16 ? id.slice(0, 8) + '...' + id.slice(-8) : id;
}

function formatCurrency(amount, currency) {
    const num = parseFloat(amount);
    if (isNaN(num)) return String(amount);
    if (currency) {
        try {
            return new Intl.NumberFormat('ja-JP', { style: 'currency', currency: currency }).format(num);
        } catch (_) {
            // Fall through
        }
    }
    return num.toLocaleString();
}

function showToast(message, type) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type || ''}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
