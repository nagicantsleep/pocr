# Brief tổng thể về hệ thống Document AI cấp doanh nghiệp tại Nhật Bản — v4

**Phạm vi:** kiến trúc, mô hình AI, luồng xử lý, dữ liệu, human-in-the-loop, bảo mật, vận hành, MLOps/DocOps, benchmark nhà cung cấp và khung tuân thủ cho hệ thống được xây dựng, sử dụng, vận hành và liên tục cải tiến tại Nhật Bản; khách hàng/chủ thể sử dụng là doanh nghiệp Nhật.

**Ngày chốt bằng chứng:** 17/07/2026 (JST).

> **Lưu ý pháp lý:** đây là brief kỹ thuật và quản trị rủi ro, không thay thế tư vấn pháp lý, thuế, kiểm toán hoặc tư vấn chuyên ngành tại Nhật Bản. Mọi control phải được xác nhận theo loại dữ liệu, loại chứng từ, ngành, hợp đồng, vai trò pháp lý của các bên và luồng dữ liệu thực tế.

---

## 0. Thông tin kiểm soát tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 4.0 |
| Trạng thái | Bản cải thiện sau rà soát nguồn chính thức; cần phê duyệt nội bộ trước production |
| Ngày cập nhật | 17/07/2026 |
| Phạm vi địa lý | Nhật Bản; có thể có xử lý xuyên biên giới nếu được phê duyệt |
| Đối tượng khách hàng | Doanh nghiệp Nhật Bản |
| Chủ sở hữu tài liệu | **Bắt buộc chỉ định:** Head of Document AI Platform hoặc vai trò tương đương |
| Người phê duyệt | Product, Security, Privacy/Legal, Tax/Records, Operations, SRE/FinOps |
| Chu kỳ rà soát | Hàng quý và theo sự kiện: luật/guideline mới, model/API/region/price/deprecation/subprocessor thay đổi |
| Tài liệu nguồn | `standard-document-ai-brief-v3.md` |
| Bằng chứng web | Chỉ ưu tiên nguồn chính thức; xem Phụ lục D |
| Release blocker | Không được phát hành production khi chưa có owner, data-flow map, legal register, benchmark report và sign-off |

### 0.1 Thay đổi trọng yếu từ v3

1. Bổ sung **Luật thúc đẩy nghiên cứu, phát triển và sử dụng công nghệ AI — Act No. 53 of 2025**, guideline theo Điều 13 và AI Basic Plan.
2. Bổ sung **Đạo luật sửa đổi APPI được ban hành ngày 17/07/2026**, đồng thời tách rõ quy định hiện hành và nghĩa vụ chuẩn bị cho quy định chưa hiệu lực đầy đủ.
3. Sửa kiến trúc intake: bản gốc đi vào **immutable quarantine store** trước khi parser/model truy cập; không coi raw store là vùng tin cậy.
4. Mở rộng data-location record thành storage, inference, log, backup, support, annotation/training và subprocessor chain.
5. Tách khả năng OCR/layout tiếng Nhật khỏi khả năng của từng prebuilt extractor; không suy diễn rằng “hỗ trợ tiếng Nhật” đồng nghĩa “hỗ trợ hóa đơn Nhật”.
6. Cập nhật lifecycle Google/Azure và yêu cầu deprecation inventory có deadline, owner và migration evidence.
7. Bổ sung benchmark leakage control, temporal split, confidence interval, coverage-risk curve và minimum sample size theo slice.
8. Bổ sung degraded mode, autonomy ceiling, document-authenticity checks, software/model supply-chain controls và golden-run diff.
9. Thêm register đầy đủ: vấn đề phát hiện, mức độ, cách sửa, trạng thái và bằng chứng.

---

## 1. Kết luận điều hành

Một hệ thống Document AI cấp doanh nghiệp tại Nhật Bản không phải là một API OCR. Nó là một hệ thống bằng chứng và quyết định có kiểm soát, gồm năm lớp:

1. **Tiếp nhận an toàn và bảo toàn chứng cứ**;
2. **Nhận biết tài liệu**: OCR, layout, handwriting, classification, splitting;
3. **Hiểu và chuẩn hóa dữ liệu** với evidence có thể truy ngược;
4. **Quyết định theo policy/risk**, không theo confidence đơn lẻ;
5. **Vận hành và quản trị vòng đời**: review, audit, drift, deprecation, incident, chi phí và thay đổi pháp lý.

### 1.1 Quyết định công nghệ

Không chọn vendor bằng bảng tính năng. Trình tự đúng là:

```text
Legal/data-location hard gates
  → Security and audit hard gates
  → Frozen Japan benchmark
  → Operational and lifecycle test
  → End-to-end cost model
  → Procurement decision
```

Các giả thuyết benchmark tại thời điểm chốt bằng chứng:

- **Azure AI Document Intelligence** là ứng viên mạnh cho OCR/Read/Layout tiếng Nhật, kể cả handwriting ở các model/version được tài liệu hóa. Tuy nhiên phải kiểm tra riêng từng model, API, region, SKU, prebuilt extractor và retention behavior.
- **Google Cloud Document AI** có classifier/splitter/extractor phong phú, nhưng danh sách location hiện hành không có Japan region. Đây là luồng xử lý ngoài Nhật nếu dùng các location được hỗ trợ; phải qua privacy/legal/contract gate. HITL tích hợp đã deprecated; một số legacy processor đã ngừng ngày 30/06/2026.
- **Amazon Textract** không phải primary OCR phù hợp cho corpus tiếng Nhật trong giới hạn hiện hành: tài liệu chính thức không liệt kê tiếng Nhật, không hỗ trợ vertical text và chỉ hỗ trợ handwriting tiếng Anh.
- Shortlist phải có ít nhất một OCR/IDP chuyên thị trường Nhật Bản hoặc phương án self-host/container khi data location, layout hoặc latency yêu cầu.

### 1.2 Kiến trúc khuyến nghị

```text
Untrusted Sources
  → Secure Intake Gateway
  → Immutable Quarantine Raw Store
  → Document Security Boundary
  → Trusted Processing Zone
  → Quality / Classify / Split
  → OCR / Layout / Extraction
  → Normalize / Enrich
  → Validation / Policy / Risk Engine
  → Auto-pass | Human Review | Reject/Quarantine
  → Controlled Downstream Integration
  → Reconciliation / Audit / Approved Feedback
```

Doanh nghiệp nên sở hữu và kiểm soát: canonical schema, policy, validation, review, audit, dataset governance, orchestration, observability và exit plan. OCR/model hosting có thể mua nếu vượt hard gate.

---

## 2. Phạm vi, giả định và thuật ngữ pháp lý

### 2.1 Phạm vi

Áp dụng cho tài liệu tiếng Nhật, tiếng Anh hoặc song ngữ, gồm PDF điện tử, PDF scan, TIFF, ảnh, fax, biểu mẫu, hợp đồng, hóa đơn, chứng từ kế toán, hồ sơ nhân sự và tài liệu có dữ liệu cá nhân hoặc mã số cá nhân.

### 2.2 Giả định an toàn

- Mọi tài liệu là **untrusted content**, kể cả từ khách hàng đã xác thực.
- File gốc có thể vừa là chứng cứ vừa là nguồn tấn công.
- AI output không phải ground truth cho tới khi vượt validation/review.
- Không có model nào được coi là phù hợp chỉ vì demo tốt hoặc cùng cloud với hệ thống hiện tại.
- Data residency là thuộc tính của toàn pipeline, không chỉ storage bucket.
- Không tự động hóa trường hoặc hành động có materiality cao nếu chưa định nghĩa false-accept budget và rollback/reversal.

### 2.3 Dùng thuật ngữ đúng bối cảnh Nhật Bản

- Dùng **specified utilization purpose / mục đích sử dụng đã xác định**, thay vì dùng “lawful basis” như một nhãn mặc định kiểu GDPR.
- PIA/DPIA có thể là control nội bộ tốt, nhưng không được mô tả như nghĩa vụ APPI phổ quát nếu chưa xác nhận theo ngành/chủ thể.
- Không dùng “SCC-equivalent” như thuật ngữ pháp định mặc định. Với chuyển dữ liệu ra nước ngoài, phải map điều kiện APPI/PPC áp dụng, thông tin cho cá nhân/consent khi cần, hệ thống tương đương hoặc continuous measures và nghĩa vụ cung cấp thông tin theo cấu trúc pháp lý thực tế.
- Mỗi quy định phải có trạng thái: `in_force`, `promulgated_not_fully_effective`, `guideline`, `policy_plan`, `draft` hoặc `contractual`.

---

## 3. Regulatory snapshot và legal-change gate

### 3.1 APPI hiện hành và sửa đổi năm 2026

Ngày 17/07/2026, PPC công bố Đạo luật sửa đổi APPI đã được ban hành. Phần lớn nội dung dự kiến có hiệu lực vào ngày do Cabinet Order ấn định trong vòng hai năm kể từ ngày ban hành; vì vậy hệ thống phải vận hành theo hai track:

| Track | Yêu cầu |
| --- | --- |
| Luật hiện hành | Tuân thủ APPI/PPC đang có hiệu lực, hợp đồng và quy định chuyên ngành |
| Readiness cho sửa đổi 2026 | Gap assessment, data inventory, policy/rule change, contract review, test và effective-date switch |

Các chủ đề cần đưa vào readiness register gồm: ngoại lệ consent trong trường hợp nhất định cho dữ liệu công khai phục vụ tạo thông tin thống kê/AI; yêu cầu mới liên quan trẻ dưới 16 tuổi; facial feature data; nghĩa vụ của processor được ủy thác; cơ chế thông báo sự cố theo rủi ro; dữ liệu không phải personal information nhưng cho phép hành động đối với cá nhân cụ thể; và tăng cường thực thi/chế tài. Không được áp dụng ngoại lệ mới trước ngày hiệu lực và trước khi legal xác nhận điều kiện.

### 3.2 AI Act, guideline và AI Basic Plan

- Act No. 53 of 2025 được ban hành năm 2025 và có hiệu lực đầy đủ từ 01/09/2025.
- Guideline theo Điều 13 hướng tới sử dụng AI phù hợp, minh bạch và quản trị rủi ro theo mức độ.
- AI Basic Plan đầu tiên được Cabinet quyết định ngày 23/12/2025.
- AI Guidelines for Business v1.2 tiếp tục là khung thực hành quan trọng, nhưng không phải là nguồn duy nhất của AI governance.

**Control bắt buộc:** legal register phải theo dõi bốn lớp riêng: luật, guideline theo luật, AI Basic Plan và hướng dẫn doanh nghiệp của METI/MIC.

### 3.3 Legal-change gate

Mỗi thay đổi pháp lý phải tạo ticket có:

```yaml
legal_item_id: JP-APPI-2026-001
status: promulgated_not_fully_effective
promulgation_date: 2026-07-17
effective_date: TBD_by_Cabinet_Order
scope: [privacy, processors, incident, AI_training]
owner: Privacy_Legal
systems_affected: [intake, dataset, vendor_contract, incident_workflow]
required_actions: []
implementation_deadline: TBD
verification_evidence: []
```

Không đóng ticket chỉ bằng “đã đọc tài liệu”; phải có mapping control, owner, test và bằng chứng triển khai.

---

## 4. Hard gates cho môi trường Nhật Bản

Một phương án chỉ được pilot production khi vượt tất cả hard gate áp dụng.

| Nhóm | Hard gate | Bằng chứng bắt buộc |
| --- | --- | --- |
| Ngôn ngữ | Printed Japanese; handwriting/vertical writing nếu use case cần | Vendor evidence + benchmark độc lập |
| Bố cục | Table, stamp-adjacent text, furigana, bilingual, multi-page | Frozen representative corpus |
| Data flow | Biết storage, inference, logs, backup, support, annotation/training, subprocessor | Architecture + contract annex + provider evidence |
| Privacy | Purpose, minimization, transfer analysis, retention, deletion, incident | Privacy review + legal register |
| My Number | Use case được legal phê duyệt; access/masking/training restriction | Specific approval + access test |
| Bảo mật | Quarantine, parser isolation, malware controls, egress, IAM, audit | Security assessment + adversarial test |
| Evidence | Raw hash, page/span/polygon, version, correction history | Traceability test |
| Chất lượng | Field/risk target; critical false accept dưới budget | Benchmark + confidence interval |
| Vận hành | Retry, DLQ, idempotency, replay, degraded mode, rollback | Failure/chaos/reconciliation test |
| DR | RTO/RPO và failover data-flow đã phê duyệt | DR exercise |
| Lifecycle | API/model deprecation inventory và migration plan | Registry + regression evidence |
| Chi phí | End-to-end unit economics, gồm reviewer và reprocess | Load test + cost model |
| Hợp đồng | Subprocessor, data reuse, deletion, support access, change notice | Legal/procurement sign-off |

### 4.1 Loại ngay hoặc giới hạn use case

Loại hoặc giới hạn khi không thể xác định nơi xử lý, không có evidence audit, không kiểm soát data reuse, không hỗ trợ script/layout cần thiết, không có reprocess/rollback, hoặc critical-field false accept vượt budget.

---

## 5. Kiến trúc tham chiếu v4

```text
Portal / API / Email / SFTP / Scanner / Mobile / DMS
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│ 1. Secure Intake Gateway                                 │
│ Auth, quota, magic bytes, size/page limits, hash, consent │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ 2. Immutable Quarantine Raw Store                        │
│ Original bytes, no execution, restricted access, WORM    │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ 3. Document Security Boundary                            │
│ Malware, sandbox, parser isolation, CDR, bombs, QR/links │
└──────────────────────────┬───────────────────────────────┘
                           ▼ approved manifest
┌──────────────────────────────────────────────────────────┐
│ 4. Trusted Processing Zone + Orchestration               │
│ State, queue, idempotency, quota, priority, DLQ, replay   │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ 5. Quality / Preprocess / Classify / Split                │
│ QC, render, rotate, deskew, unknown/OOD, page boundaries  │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ 6. OCR / Layout / Extraction                             │
│ Managed, custom, prebuilt, query, multimodal, fallback    │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ 7. Canonicalize / Normalize / Enrich                     │
│ Reversible JP normalization, master data, provenance      │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ 8. Validation / Policy / Risk / Autonomy Gate             │
│ Rules, reconciliation, calibration, materiality, limits   │
└───────────────┬──────────────────┬───────────────────────┘
                │ auto-pass        │ review/reject/security
                ▼                  ▼
       Controlled Integration   Human Review / Quarantine
                │                  │
                └──────────┬───────┘
                           ▼
          Reconciliation / Audit / Approved Dataset
```

### 5.1 Trust boundaries

- Quarantine raw store là immutable nhưng **không phải vùng tin cậy**; chỉ security service có quyền đọc rộng.
- Parser/render/model không có credential ghi ERP/CRM.
- Model output không được trực tiếp điều khiển tool; policy engine là enforcement point.
- Review/correction store tách khỏi production output và training candidate.
- Provider payload không đi thẳng xuống downstream; phải qua adapter và canonical validator.
- CDR/transform không thay thế file gốc; manifest phải liên kết hash của raw và derived copy.

---

## 6. Thiết kế thành phần

### 6.1 Secure Intake Gateway

- Xác thực user/app/tenant; rate limit và tenant quota.
- MIME bằng magic bytes, extension chỉ là metadata.
- Giới hạn file size, page count, dimensions, nesting, compression ratio, render time.
- SHA-256, duplicate/replay detection và idempotency key.
- Gắn `document_id`, `case_id`, `tenant_id`, `correlation_id`, purpose, retention, classification.
- Tách upload acknowledgement khỏi processing outcome.
- Không mở link, QR, attachment hoặc external reference từ tài liệu.

### 6.2 Storage zones

```text
quarantine/raw/   original bytes, restricted, immutable
trusted/derived/  rendered pages, CDR copy, thumbnails
results/vendor/   immutable vendor payload by run/version
results/canonical/versioned canonical objects
review/           reviewer decisions and corrections
training-candidate/quarantined feedback
approved-dataset/ versioned train/validation/test artifacts
audit/            append-only event/evidence manifests
```

Mọi deletion phải có policy evaluation; legal hold và statutory retention override phải được ghi lý do, người phê duyệt và thời điểm review lại.

### 6.3 Security boundary

Kiểm tra malware, active content, embedded files, parser exploit, decompression/page bomb, encrypted file, MIME mismatch, external callbacks, hidden/white text, visual-vs-text-layer conflict, barcode/QR side channel và anomalous metadata.

Renderer/parser:

- minimal patched image;
- no downstream secrets;
- network egress mặc định chặn;
- CPU/memory/time/file descriptor limits;
- syscall/container sandbox;
- SBOM, image signing và dependency vulnerability management.

### 6.4 Orchestration

- State machine versioned và deterministic.
- Retry theo loại lỗi, exponential backoff + jitter.
- DLQ, replay có quyền riêng và audit.
- Outbox/inbox pattern, deduplication và idempotent consumer.
- Exactly-once **business outcome** bằng idempotency/reconciliation; không tuyên bố exactly-once transport nếu hạ tầng không bảo đảm.
- Degraded modes: queue-only, human-only, approved secondary provider, reject, security quarantine.

### 6.5 Quality và preprocessing

Đo blur, glare, shadow, skew, DPI, clipping, blank page, orientation, vertical/horizontal ratio, corruption và fax noise. Preprocessing phải:

- lưu transformation graph và version;
- so sánh raw-versus-preprocessed trên benchmark;
- không làm mất nét kanji, dấu, đường bảng hoặc digital signature;
- không thay đổi file chứng cứ gốc.

### 6.6 Classification và splitting

Luôn có `unknown/other`, OOD score, page range, evidence và reason code. Không ép mọi tài liệu vào known class. Với mixed-document packet, split boundary accuracy là metric độc lập.

### 6.7 Extraction và semantic status

Mỗi trường phải có một trong các trạng thái:

- `extracted`: có evidence trực tiếp;
- `normalized`: biến đổi có quy tắc từ extracted;
- `enriched`: từ nguồn tham chiếu;
- `derived`: tính/suy luận có phương pháp;
- `not_found`: không có evidence;
- `not_applicable`: không áp dụng;
- `conflicted`: các nguồn/model không thống nhất;
- `redacted`: bị che theo policy.

LLM không điền giá trị thiếu để thỏa schema. Critical fields cần evidence span/polygon, independent validation và policy threshold.

### 6.8 Chuẩn hóa Nhật Bản

- Full-width/half-width và Unicode normalization;
- kanji numeral ↔ Arabic digit khi policy cho phép;
- Japanese era ↔ ISO date;
- tên, corporate form và spacing;
- địa chỉ, prefecture, postal code;
- yen, tax-inclusive/exclusive, rounding;
- phone, corporate number, invoice registration number;
- master vendor/customer mapping.

Không ghi đè `rawValue`. NFKC có thể làm thay đổi ký tự có ý nghĩa; phải lưu `normalizationSteps`, implementation version và reversible evidence.

### 6.9 Validation, authenticity và policy

Ba nhóm kiểm tra độc lập:

1. **Extraction correctness:** schema, regex, arithmetic, cross-page consistency, master lookup.
2. **Document authenticity signals:** digital signature/certificate/timestamp validation nếu có, hash, source channel, duplicate, metadata anomaly. Không tuyên bố “authentic” chỉ từ OCR hoặc hình ảnh con dấu.
3. **Business policy:** materiality, approval, segregation of duties, downstream permission, reversal path.

### 6.10 Downstream integration

- Outbox/event pattern và transaction ID.
- Policy check trước mọi create/update/payment/action.
- Reconciliation giữa accepted output và downstream state.
- Correction/reversal path và non-repudiation log.
- Dual authorization cho hành động tài chính/pháp lý quan trọng.

---

## 7. Chiến lược mô hình

### 7.1 Tách capability theo tầng

Không dùng nhãn “hỗ trợ tiếng Nhật” cho toàn bộ dịch vụ. Benchmark matrix phải tách:

| Tầng | Ví dụ capability |
| --- | --- |
| OCR/Read | Printed, handwriting, script, vertical text |
| Layout | Reading order, tables, cells, checkbox, polygon |
| Classification | Document type, unknown/OOD |
| Splitting | Page boundaries, mixed packets |
| Prebuilt extraction | Invoice, receipt, ID, contract — theo locale/model cụ thể |
| Custom extraction | Template/neural/generative — theo data và region |
| Tool/action | Validation, lookup, downstream write — không giao trực tiếp cho model |

### 7.2 Managed OCR/layout

Mua thường hợp lý hơn tự huấn luyện, nhưng phải benchmark: Japanese printed/handwriting, vertical text, mixed scripts, reading order, tables, stamp-adjacent text, latency, cost và region.

### 7.3 Prebuilt extractor

Chỉ dùng khi tài liệu chính thức và benchmark chứng minh đúng locale/schema. Không suy luận rằng OCR tiếng Nhật tốt đồng nghĩa prebuilt invoice hiểu Qualified Invoice System của Nhật.

### 7.4 Custom models

- Template: tốt cho form ổn định, dễ drift khi biến thể/scan lệch/stamp che.
- Neural/semantic: tốt cho nhiều layout, cần hard-case/OOD test.
- Generative/multimodal: phù hợp trường ngữ nghĩa khó, nhưng cần schema, evidence, prompt/model version, low-temperature khi khả dụng, no-tool privilege, token/page cap và deterministic regression set.

### 7.5 Ensemble/fallback

Chỉ gọi secondary model cho failed/ambiguous pages hoặc policy-defined high-risk cases. Phải có reconciliation và disagreement handling; không gọi nhiều model mọi tài liệu nếu không chứng minh lợi ích.

### 7.6 Agentic autonomy ceiling

- Level 0: extract only.
- Level 1: recommend validation/review.
- Level 2: prepare downstream draft, human approves.
- Level 3: limited auto-action trong allowlist, low materiality và reversible.
- Level 4: high-impact autonomous action — **không cho phép** nếu chưa có explicit executive/legal/risk approval, dual controls và continuous monitoring.

---

## 8. Canonical data contract v4

Downstream không phụ thuộc JSON riêng của vendor.

```json
{
  "documentId": "doc_123",
  "caseId": "case_456",
  "tenantId": "tenant_jp_001",
  "source": {
    "channel": "portal",
    "fileName": "請求書_202607.pdf",
    "sha256": "...",
    "receivedAt": "2026-07-17T10:00:00+09:00",
    "originalMimeType": "application/pdf",
    "quarantineObjectVersion": "v1"
  },
  "governance": {
    "jurisdictions": ["JP"],
    "dataClassification": "confidential-personal",
    "purposeCode": "AP_PROCESSING",
    "retentionClass": "JP_TAX_DOCUMENT_REVIEW_REQUIRED",
    "legalHold": false,
    "legalRegisterRefs": ["JP-APPI-CURRENT", "JP-EBOOKKEEPING"],
    "crossBorderProcessing": false,
    "locations": {
      "storage": ["JP"],
      "inference": ["JP"],
      "logsTelemetry": ["JP"],
      "backupDR": ["JP"],
      "supportAccessCountries": [],
      "annotationTraining": []
    },
    "subprocessors": [],
    "locationEvidenceRef": "procurement-evidence-2026-07",
    "providerDataReuse": "disabled_by_contract",
    "providerRetention": "zero_or_approved_period",
    "deletionVerificationRef": null
  },
  "security": {
    "securityDecision": "approved",
    "manifestHash": "...",
    "malwareScanVersion": "scanner-2026.07",
    "cdrApplied": false,
    "visualTextLayerConflict": false
  },
  "document": {
    "type": "qualified_invoice",
    "typeConfidenceRaw": 0.97,
    "typeCalibratedProbability": 0.91,
    "oodScore": 0.06,
    "pageRange": [1, 2],
    "languages": ["ja", "en"],
    "writingDirections": ["horizontal"]
  },
  "fields": {
    "invoiceNumber": {
      "status": "normalized",
      "rawValue": "請求書番号：ＡＢ－００１２５",
      "normalizedValue": "AB-00125",
      "dataType": "string",
      "confidenceRaw": 0.96,
      "confidenceSource": "provider_field_score",
      "calibratedProbability": 0.91,
      "calibrationModelVersion": "cal-jp-invoice-2026.07",
      "normalizationSteps": ["NFKC", "REMOVE_LABEL"],
      "normalizationVersion": "jp-normalizer-3.0",
      "evidence": [{
        "page": 1,
        "polygon": [[0.10,0.20],[0.32,0.20],[0.32,0.25],[0.10,0.25]],
        "text": "請求書番号：ＡＢ－００１２５",
        "pageImageHash": "...",
        "sourceEvidenceHash": "..."
      }]
    }
  },
  "validation": {
    "status": "warning",
    "rules": [{
      "rule": "TOTAL_EQUALS_LINE_SUM",
      "version": "2026.07",
      "status": "failed",
      "severity": "high"
    }]
  },
  "decision": {
    "policyVersion": "jp-ap-policy-4.0",
    "riskBand": "high",
    "action": "human_review",
    "reasonCodes": ["TOTAL_MISMATCH"],
    "autonomyLevel": 1
  },
  "processing": {
    "runId": "run_789",
    "pipelineVersion": "4.0.0",
    "preprocessingVersion": "3.0.0",
    "provider": "example-provider",
    "service": "document-ai",
    "apiVersion": "explicit-version",
    "modelId": "jp-invoice-custom",
    "modelVersion": "4",
    "promptVersion": null,
    "schemaVersion": "jp-doc-2.0",
    "adapterVersion": "provider-adapter-5.2",
    "processedAt": "2026-07-17T10:01:18+09:00"
  },
  "review": {
    "required": true,
    "decision": null,
    "reviewPolicyVersion": "review-2.1"
  },
  "integration": {
    "downstreamSystem": "ERP",
    "transactionId": null,
    "reconciliationStatus": "pending"
  }
}
```

### 8.1 Điểm bắt buộc

- Location phải phân rã theo activity; không chỉ một `processingLocations` chung.
- Ví dụ contract không được hard-code một overseas region như mặc định.
- Có confidence provenance, calibration version và evidence hash.
- Có policy/autonomy version và downstream transaction/reconciliation.
- Có provider data reuse/retention/deletion evidence.
- Schema evolution phải có compatibility rule và migration test.

---

## 9. Confidence, calibration và decision policy

### 9.1 Không đồng nhất confidence với xác suất đúng

Vendor score có thể không so sánh được giữa model, field, document type, version và provider. Cần calibration trên production-like data bằng reliability curve, ECE/Brier score khi phù hợp.

### 9.2 Đánh giá selective prediction

Ngoài accuracy, đo:

- coverage–risk curve;
- accuracy tại các mức auto-pass coverage;
- abstention/OOD quality;
- false accept theo materiality;
- reviewer capacity tại từng threshold.

Không chọn threshold chỉ để đạt straight-through rate cao.

### 9.3 Confidence interval và sample size

Mỗi metric/slice phải có:

- sample count;
- confidence interval hoặc bootstrap interval;
- minimum count để được dùng cho release decision;
- cảnh báo khi slice quá nhỏ;
- không lấy macro average che lỗi critical field.

### 9.4 Risk score

```text
reviewRisk =
    calibratedUncertainty
  + imageQualityRisk
  + ruleFailureRisk
  + OODRisk
  + legalFinancialMateriality
  + historicalTemplateError
  + privacyTransferSensitivity
  + modelDisagreement
  + authenticityRisk
```

Trọng số và reason code phải versioned, được Product/Risk phê duyệt và không thay đổi âm thầm.

### 9.5 Decision bands

- Low: straight-through trong autonomy allowlist.
- Medium: field-level review.
- High: full review/dual control.
- Unknown/OOD: manual triage hoặc reject.
- Security suspect: quarantine, không đi qua pipeline thường.
- SLO/error-budget breach: tự động hạ autonomy hoặc tắt auto-pass.

---

## 10. Human-in-the-loop

Human review là production control lâu dài.

### 10.1 Loại review

Full-document, field-level, random sampling auto-pass, dual control, adjudication, security triage và post-incident retrospective review.

### 10.2 Review UI

- Viewer raw/derived có nhãn rõ;
- evidence highlight, raw/normalized/derived status;
- confidence, reason, validation warning;
- history, reviewer identity, timestamp;
- masking theo role, Japanese IME, vertical/table/stamp rendering;
- SLA/priority và append-only audit;
- không cho copy/download PII nếu không cần;
- session watermark và support-access logging khi phù hợp.

### 10.3 Correction governance

```text
Reviewer correction
  → validation/adjudication
  → privacy/licensing/source check
  → contamination and leakage check
  → dataset approval
  → immutable dataset version
  → training candidate
```

Không đẩy correction trực tiếp vào training. Theo dõi reviewer agreement, bias, correction rate, suspicious pattern và poisoning signal.

### 10.4 Vendor-worker access

Không cho phép vendor/subprocessor reviewer truy cập dữ liệu thật nếu chưa có contract, location, role, confidentiality, training-use restriction, audit và masking được phê duyệt.

---

## 11. Dataset, MLOps và DocOps

### 11.1 Dataset split

Training, validation, frozen test, shadow, regression, hard case, OOD, adversarial, malicious-document, Japanese script/layout và incident replay set.

### 11.2 Chống benchmark leakage

- Tách theo source/customer/template/time, không chỉ random page split.
- Dùng temporal holdout cho template drift.
- Không để cùng document family xuất hiện ở train và test.
- Không điều chỉnh prompt/model lặp lại trên frozen test; dùng development set riêng.
- Ghi provenance/licensing/consent/purpose của từng sample.

### 11.3 Japan slices

Kanji/hiragana/katakana/Latin/digits; full/half-width; era/Gregorian; horizontal/vertical; handwriting; stamp; fax/noisy scan; bilingual; Japanese names/address/corporate forms; yen/tax/rounding; qualified invoice; electronic transaction records; My Number only when approved; rare template và drift.

### 11.4 Versioning

Provider, service, API, model/processor, prompt, preprocessing, adapter, schema, normalization, rule set, calibration, decision policy, dataset, container, dependency/SBOM và IaC.

### 11.5 Release process

```text
Offline evaluation
  → calibration and slice statistics
  → security/privacy/adversarial test
  → golden-run diff
  → shadow
  → canary by tenant/type
  → progressive rollout
  → error-budget monitoring
  → rollback / autonomy reduction
```

### 11.6 Drift và silent degradation

Theo dõi OOD, template distribution, field null, confidence/calibration, correction, rule failure, accuracy theo slice/tenant, image quality, model disagreement, cost/page, latency và downstream reversal.

### 11.7 Golden-run diff

Mỗi model/API/provider upgrade phải chạy lại immutable golden corpus và báo:

- value changes;
- polygon/span changes;
- confidence distribution changes;
- normalization/decision changes;
- latency/cost changes;
- unsupported/deprecated behavior.

---

## 12. Lifecycle và deprecation management

### 12.1 Registry

| Trường | Yêu cầu |
| --- | --- |
| Provider/service/API/model | Định danh đầy đủ |
| Current version | Không dùng “latest” không cố định |
| End of support | Ngày cụ thể hoặc `unknown` |
| Migration target | Version/model đích |
| Owner | Cá nhân/role chịu trách nhiệm |
| Affected tenants/types | Phạm vi tác động |
| Regression status | Chưa chạy/đạt/không đạt |
| Contract notice | Điều khoản và ngày nhận thông báo |
| Rollback | Version và procedure |

### 12.2 Current lifecycle facts cần phản ánh

- Google Document AI HITL đã deprecated từ 16/01/2024.
- Các legacy processor được Google nêu trong deprecation schedule đã ngừng ngày 30/06/2026; inventory phải xác minh không còn dependency production.
- Với Azure Document Intelligence, tài liệu hiện hành nêu mốc end-of-support cho REST API v2.1 là 15/09/2027 và v3.0 (2022-08-31) là 30/03/2029; new development nên dùng API ổn định mới hơn được Microsoft khuyến nghị, nhưng phải regression test.

Không copy lifecycle fact vào brief rồi bỏ quên; phải tạo alert trước 12/9/6/3 tháng tùy criticality.

---

## 13. Observability, NFR, DR và FinOps

### 13.1 KPI kỹ thuật

Volume, queue depth/age, P50/P95/P99 latency, per-step latency, success/error/retry/timeout/throttle, DLQ, quota, availability, storage/egress, reprocess và degraded-mode duration.

### 13.2 KPI chất lượng

Classification precision/recall/F1; split boundary; OCR CER/WER theo script; field exact/normalized match; table cell; calibration error; coverage-risk; OOD recall; false accept/reject; correction; reviewer agreement; confidence interval/sample count.

### 13.3 KPI nghiệp vụ

Straight-through, review rate, handling time, cost per accepted document, downstream rejection/reversal, time-to-decision, prevented financial error, SLA breach và dispute rate.

### 13.4 Workload envelope

Mỗi service tier phải định lượng:

- max MB/pages/dimensions/compression;
- average/peak pages per minute và burst;
- provider quota và headroom;
- review staffing theo arrival pattern;
- P95/P99 target theo size bucket;
- backlog drain time sau outage.

### 13.5 DR

- Recovery cho raw, metadata, results, config, model, schema, rules và IaC.
- Reconciliation queue/state sau failover.
- Mỗi alternate region/provider phải qua lại data-flow/privacy review; failover không được tự động tạo cross-border transfer ngoài phê duyệt.
- Kiểm thử DR và restore, không chỉ runbook.

### 13.6 FinOps

```text
cost/document =
  intake + quarantine/storage + render/security
  + OCR/extraction + LLM tokens + egress
  + review labor + reprocess + monitoring
  + retention + incident/exception overhead
```

Guardrail theo tenant/type/model/stage; blank/duplicate-page skip; model routing theo complexity; deterministic cache theo content hash + full version tuple; alert unit-cost/reprocess spike.

---

## 14. Security, privacy và AI threat model

### 14.1 Data controls

Encryption, CMK khi cần, workload identity, least privilege, private connectivity/perimeter khi khả dụng, no long-lived key, append-only audit, tenant isolation, DLP/masking, retention/deletion/legal hold, subprocessor inventory, support-access log và contract opt-out/ban on provider training.

### 14.2 Threats và controls

| Threat | Control |
| --- | --- |
| Malware/active content | Quarantine, sandbox, CDR-derived copy, no execution |
| Parser exploit | Patched minimal image, SBOM, signing, syscall/network restriction |
| Decompression/page bomb | Pre/post-render limits, timeouts |
| Password-protected file | Quarantine/special workflow |
| External URL/QR | Treat as data, no automatic fetch |
| Hidden/white text | Compare visual/text layer; preserve evidence |
| Prompt injection | Untrusted delimiters, tool allowlist, policy gateway |
| Output exfiltration | Schema/semantic validation, DLP, egress proxy |
| Tenant leakage | Strict partitioning and authorization test |
| Reviewer poisoning | Adjudication, anomaly monitoring, dataset quarantine |
| Model/dependency compromise | Registry, hashes, signatures, SBOM, controlled rollout |
| Authenticity spoofing | Signature/timestamp/source verification; no visual-only assertion |

### 14.3 GenAI controls

- System policy tách document content.
- Model không có direct write credential.
- Tool calls qua allowlist, parameter validator và materiality gate.
- Không tự mở URL/attachment.
- Evidence required, `not_found` allowed.
- Prompt injection/adversarial set trong regression.
- Minimize PII in prompt/log; retention và provider reuse theo contract.
- Isolate RAG corpus và kiểm soát poisoning.

### 14.4 Incident response

Containment/quarantine; identify tenant/document/model/run; freeze downstream actions; preserve evidence; privacy/legal assessment; notification theo luật/hợp đồng; reprocess; customer reconciliation; post-incident test case; autonomy reduction until closure.

---

## 15. Compliance và governance tại Nhật Bản

### 15.1 APPI/PPC hiện hành

Operational controls tối thiểu:

- specified utilization purpose và notice/consent/exception mapping;
- minimization, accuracy và retention;
- safety management measures;
- employee/vendor/subprocessor supervision;
- leakage/loss/damage response;
- data subject request workflow;
- cross-border transfer analysis;
- access/deletion/legal-hold decision log.

### 15.2 Chuyển dữ liệu ra nước ngoài

Map country/region và role của từng bên; xác định outsourcing hay third-party provision theo facts; đánh giá điều kiện APPI/PPC; contract onward transfer, security, audit, notification và change notice; theo dõi pháp luật nơi nhận; ghi location evidence theo processing run hoặc provider configuration version.

Văn phòng hoặc pháp nhân Nhật của vendor không chứng minh API xử lý tại Nhật.

### 15.3 APPI amendment 2026 readiness

- Không bật ngoại lệ mới trước hiệu lực.
- Inventory public-source data dùng cho model/benchmark.
- Đánh giá dữ liệu trẻ dưới 16 tuổi, facial feature data và processor obligations.
- Cập nhật incident severity matrix và notification workflow.
- Rà soát dữ liệu cho phép “action toward a specific individual” dù không phải personal information theo định nghĩa truyền thống.
- Theo dõi Cabinet Order, PPC rules/guidelines và transitional measures.

### 15.4 My Number / Specific Personal Information

- Default deny: chỉ xử lý khi use case được legal phê duyệt.
- Purpose/access/masking/retention riêng và nghiêm hơn.
- Không dùng cho general model training/evaluation theo mặc định.
- Review UI theo need-to-know; audit mọi reveal/export.
- Outsourcing/re-outsourcing và incident path chuyên biệt.

### 15.5 Electronic Bookkeeping Act

Phải map chính xác loại record và phương thức lưu áp dụng. Với electronic transaction data, không mặc định OCR JSON hoặc PDF render là record pháp định thay cho dữ liệu gốc. Bảo toàn dữ liệu điện tử nhận được, tính toàn vẹn/khả dụng/searchability/retention theo yêu cầu áp dụng và ý kiến tax/records.

### 15.6 Qualified Invoice System

- Extract fields theo loại invoice/credit note và rule hiện hành.
- Arithmetic/tax-rate/rounding reconciliation.
- NTA issuer lookup khi nghiệp vụ cần; lưu timestamp, query/key, response/evidence để phân biệt trạng thái tại thời điểm tra cứu và lịch sử.
- Không coi registration lookup đơn lẻ là bằng chứng toàn diện về validity của giao dịch.

### 15.7 AI governance

Áp dụng risk-proportionate governance theo AI Act/guideline/AI Basic Plan và AI Guidelines for Business v1.2:

- human-centric, safety, fairness, privacy, security;
- transparency/accountability và incident disclosure process;
- literacy, lifecycle governance và vendor management;
- autonomy ceiling và human oversight theo materiality;
- evidence, audit và change management.

### 15.8 Contract checklist

Data ownership; purpose/data reuse/training; exact locations; subprocessors/change notice; support access; retention/deletion verification; breach SLA; model/API change; availability/quotas; Japanese support; export/exit; audit reports; liability; human-review responsibility; no absolute accuracy claims.

---

## 16. Vendor assessment tại thời điểm chốt bằng chứng

### 16.1 Verified facts và giới hạn diễn giải

| Chủ đề | Google Cloud Document AI | Azure AI Document Intelligence | Amazon Textract |
| --- | --- | --- | --- |
| Japanese OCR | Xác minh theo processor/version và benchmark | Tài liệu Read/Layout liệt kê Japanese, gồm handwriting ở các phiên bản được nêu | Không liệt kê Japanese trong ngôn ngữ hỗ trợ hiện hành |
| Vertical text | Không giả định; benchmark | Không suy luận từ language list; benchmark | Tài liệu nêu không hỗ trợ vertical text |
| Japan data location | Không có Japan trong location list hiện hành; Asia single-region gồm Mumbai/Singapore/Sydney | Xác minh model/API/SKU và Japan East/West trong procurement | Xác minh theo từng service; AWS region không chứng minh Textract/model coverage |
| Prebuilt invoice Japan | Không giả định | Không suy luận từ OCR support; xác minh locale/model | Primary OCR limitation đã là hard constraint |
| HITL tích hợp | Deprecated; tự xây review | Tự xây review độc lập | Tự xây review độc lập |
| Lifecycle | Legacy processors nêu trong schedule đã dừng 30/06/2026 | Theo dõi API end-of-support và migrate có regression | Theo dõi quotas/features/region và API changes |

### 16.2 Procurement evidence package

Vendor phải cung cấp bằng văn bản:

- service/model/API/version/SKU;
- storage/inference/log/backup/support/annotation locations;
- subprocessor và change notice;
- data retention/reuse/training behavior;
- deletion verification;
- Japanese script/layout/locale limitations;
- quotas/SLA/support;
- deprecation/change policy;
- security attestations;
- price assumptions;
- export/exit format.

### 16.3 Shortlist

1. Azure AI Document Intelligence;
2. Google Document AI chỉ khi cross-border gate có thể được phê duyệt;
3. ít nhất một Japan-specialized OCR/IDP;
4. cloud-native orchestration + OCR khác khi cloud chiến lược không có OCR phù hợp;
5. self-host/container khi locality/latency/layout bắt buộc.

Không tuyên bố winner trước frozen benchmark.

---

## 17. Benchmark và acceptance framework

### 17.1 Hard gate pass/fail

| Mã | Tiêu chí | Pass condition |
| --- | --- | --- |
| H1 | Japanese printed OCR | Target trên frozen test và đủ sample |
| H2 | Vertical/handwriting nếu cần | Target hoặc approved fallback |
| H3 | Data flow/location | Privacy/Legal/Security phê duyệt |
| H4 | Evidence/audit | Page/span/polygon/hash/version traceability |
| H5 | Security | Threat/adversarial review đạt |
| H6 | Critical false accept | Dưới approved budget với interval |
| H7 | Reprocess/rollback | Test thành công |
| H8 | Contract/subprocessor | Procurement/legal chấp thuận |
| H9 | Lifecycle | Không dependency đã EOL; migration drill đạt |
| H10 | Degraded mode | Queue/human/fallback/reject path đã test |

### 17.2 Weighted score sau hard gate

| Nhóm | Trọng số gợi ý |
| --- | ---: |
| Critical-field accuracy, OOD, coverage-risk | 30% |
| Japanese script/layout | 15% |
| Security/privacy/location | 15% |
| Evidence/integration | 10% |
| Lifecycle/operations | 10% |
| Reliability/latency/throughput | 8% |
| End-to-end cost | 7% |
| Reviewer productivity | 5% |

Không bù hard-gate failure bằng weighted average. Không dùng một accuracy tổng để che critical fields.

### 17.3 Acceptance template

```text
Document type: JP qualified invoice
Critical fields: issuer, registration number, invoice number,
transaction date, tax rate, tax amount, total amount

Pass only when:
- all hard gates pass;
- test-set provenance and leakage controls are approved;
- critical-field normalized accuracy and confidence intervals meet targets;
- false accept is below budget;
- arithmetic/tax reconciliation supports approved patterns;
- vertical/bilingual/fax slices meet slice targets with minimum sample size;
- P95/P99 latency, throughput and cost meet workload envelope;
- reviewer AHT and agreement improve against baseline;
- end-to-end evidence and downstream reversal are demonstrated;
- no EOL dependency remains.
```

---

## 18. Build, buy hay hybrid

### 18.1 Mua/managed khi vượt hard gate

OCR/layout/handwriting, inference/model hosting, autoscaling, suitable prebuilt extraction và foundation-model access.

### 18.2 Tự kiểm soát

Intake/quarantine/security boundary, immutable evidence, orchestration, canonical schema, Japanese normalization, validation, risk policy, review, audit, dataset governance, observability, FinOps, vendor abstraction và exit.

### 18.3 Self-host/container

Cân nhắc khi policy yêu cầu Japan/on-prem, volume ổn định, latency/availability đặc biệt hoặc managed service không hỗ trợ. Self-host không tự động an toàn hơn; tổ chức chịu patching, capacity, model lifecycle, SBOM/signing và incident.

---

## 19. Operating model, RACI và separation of duties

| Vai trò | Trách nhiệm |
| --- | --- |
| Document owner | Chịu trách nhiệm nội dung, review cadence, approval evidence |
| Product owner | KPI, scope, automation policy, acceptance |
| Platform | Intake, pipeline, storage, API, orchestration |
| ML/AI | Dataset, benchmark, calibration, drift, release |
| Security | Threat model, IAM, network, supply chain, incident |
| Privacy/Legal | APPI, transfer, AI governance, contracts, legal register |
| Tax/Records | E-Bookkeeping, invoice/retention mapping |
| Operations | Review, reason code, SLA, stop-auto-pass authority |
| Data steward | Canonical schema, master data, quality |
| SRE/FinOps | SLO, capacity, DR, cost |

Không để một người đồng thời sửa ground truth, phê duyệt dataset, deploy model, phê duyệt business output và xóa raw/audit.

**Stop authority:** Security/Privacy có quyền chặn release; Operations/SRE có quyền hạ autonomy/tắt auto-pass khi silent degradation hoặc SLO breach.

---

## 20. Lộ trình và stage gates

### G0 — Discovery/legal/data mapping

Chọn use case; map data/purpose/retention/flow; identify personal/My Number/records; corpus; manual baseline; error budget; legal register.

**Exit:** scope, owner, legal assumptions, dataset policy và hard gates được phê duyệt.

### G1 — Benchmark

Frozen corpus, leakage control, slices, evidence, latency/cost, region/security/lifecycle/reviewer test.

**Exit:** ít nhất một phương án vượt tất cả hard gates.

### G2 — Controlled MVP

Intake/quarantine/security, raw store, classify/extract, canonical JSON, validation, review, one integration, audit, dashboard; auto-pass off/narrow.

**Exit:** traceability, incident, reconciliation, reversal hoạt động.

### G3 — Production hardening

Private connectivity, IAM/KMS, queue/DLQ/replay, load/capacity, DR, canary/rollback, adversarial/supply-chain test, legal/contract sign-off.

**Exit:** production readiness approved.

### G4 — Progressive automation

Tăng auto-pass theo field/type/tenant sau calibration, false-accept, sampling và downstream reversal test.

### G5 — Scale/continuous improvement

New types, governed active learning, drift/OOD, cost optimization, migration drills, quarterly legal/vendor review.

---

## 21. Anti-pattern cần tránh

1. Chọn OCR chỉ vì cùng cloud.
2. Đồng nhất OCR Japanese support với prebuilt invoice Japan support.
3. Giả định cloud region bằng AI service region.
4. Lưu raw vào vùng người dùng/model truy cập trước security clearance.
5. Chỉ lưu text, mất layout/evidence.
6. Ghi đè raw bằng normalized value.
7. Một prompt xử lý OCR → quyết định → action.
8. Cho model direct write credential.
9. Không có unknown/OOD/abstention.
10. Một threshold cho mọi field.
11. Tin confidence chưa calibration.
12. Dùng tiny slice nhưng báo phần trăm như chắc chắn.
13. Random page split gây benchmark leakage.
14. Downstream phụ thuộc vendor JSON.
15. Correction đi thẳng vào training.
16. Không có frozen regression/golden-run diff.
17. Auto-pass 100% từ đầu.
18. Không có degraded mode và stop authority.
19. Không reprocess/reconcile/reverse.
20. Không theo dõi API/model EOL.
21. Phụ thuộc HITL vendor đã deprecated.
22. Xem document content là instruction.
23. Tự mở QR/link/attachment trích từ tài liệu.
24. Không quản lý subprocessor/support access/data reuse.
25. Hard-code overseas region trong canonical example như mặc định.
26. Mô tả bill/guideline như luật đã hiệu lực.
27. Áp dụng APPI 2026 exception trước effective date.
28. Coi OCR hoặc hình con dấu là xác minh authenticity.
29. Failover sang region/provider mới mà không re-review data flow.
30. Không gắn owner và bằng chứng phê duyệt cho brief.

---

## 22. Kiến trúc và quyết định cuối cùng

Đối với phần lớn doanh nghiệp Nhật Bản:

- Japan-first frozen benchmark;
- hybrid, event-driven, vendor-neutral;
- immutable quarantine raw store và security boundary trước parser/model;
- classifier/splitter trước extractor;
- canonical schema độc lập vendor và location-aware;
- raw/normalized/enriched/derived/conflicted separation;
- authenticity signal tách khỏi OCR accuracy;
- business validation/policy tách AI;
- calibrated confidence + OOD + coverage-risk;
- independent human review;
- autonomy ceiling và dual control;
- full versioning, golden-run diff, canary/rollback;
- APPI current-law controls + 2026-amendment readiness;
- AI Act/guideline/AI Basic Plan governance;
- E-Bookkeeping/Qualified Invoice-aware records design;
- SLO/DR/FinOps/degraded mode;
- provider exit plan.

### 22.1 Quyết định ngắn gọn

1. Không dùng Amazon Textract làm primary OCR cho tài liệu tiếng Nhật theo capability hiện hành.
2. Đưa Azure và ít nhất một Japan-specialized vendor vào benchmark chính.
3. Chỉ shortlist Google khi cross-border được phê duyệt; không dùng deprecated HITL/legacy processor.
4. Tự kiểm soát quarantine, schema, review, policy, audit, orchestration và dataset governance.
5. Chỉ bật auto-pass sau benchmark, calibration, confidence interval, sampling và reversal test.
6. Tạo ngay APPI 2026 readiness program và AI Act governance register.

---

# Phụ lục A — Vấn đề phát hiện trong v3

| ID | Mức độ | Vấn đề | Rủi ro |
| --- | --- | --- | --- |
| V4-01 | Critical | Thiếu APPI amendment được ban hành 17/07/2026 | Brief sai snapshot pháp lý ngay ngày chốt tài liệu |
| V4-02 | High | Thiếu AI Act 2025, Điều 13 guideline và AI Basic Plan | AI governance không đầy đủ |
| V4-03 | High | Dùng “lawful purpose”, “DPIA”, “SCC-equivalent” thiếu chú thích | Dễ nhập nhầm khái niệm GDPR vào APPI |
| V4-04 | High | Legal status chưa có register vận hành | Dễ áp dụng bill/guideline sai thời điểm |
| V4-05 | High | Raw store đặt trước security boundary nhưng chưa gọi rõ là quarantine | Người/model có thể truy cập file độc hại |
| V4-06 | High | Location record chỉ có processing locations chung | Bỏ sót logs, backup, support, training, subprocessor |
| V4-07 | High | Canonical example hard-code cross-border/Singapore | Có thể bị hiểu là mặc định khuyến nghị |
| V4-08 | High | Japanese OCR support có thể bị hiểu là prebuilt invoice support | Procurement/model selection sai |
| V4-09 | Medium | Google legacy processor được mô tả như sự kiện sắp tới | Tại 17/07/2026, mốc 30/06/2026 đã qua |
| V4-10 | Medium | Thiếu Azure API support deadlines | Migration risk |
| V4-11 | High | Benchmark thiếu leakage/temporal split control | Kết quả accuracy phồng giả tạo |
| V4-12 | High | Slice metric thiếu sample size/confidence interval | Quyết định dựa trên dữ liệu quá nhỏ |
| V4-13 | Medium | Calibration chưa có coverage-risk/selective prediction | Threshold khó gắn với automation coverage |
| V4-14 | High | Chưa tách document authenticity khỏi OCR correctness | Dễ coi dấu/chữ ký hình ảnh là thật |
| V4-15 | High | Thiếu autonomy ceiling cho GenAI/tool action | Hành động vượt quyền/materiality |
| V4-16 | High | Threat model thiếu output exfiltration và supply chain | Rò dữ liệu/model dependency compromise |
| V4-17 | Medium | Human review thiếu vendor-worker access control | Privacy/location risk |
| V4-18 | High | Correction governance thiếu explicit contamination/leakage test | Data poisoning/test leakage |
| V4-19 | Medium | DR chưa bắt buộc re-review cross-border failover | Failover tạo transfer trái policy |
| V4-20 | Medium | Thiếu degraded mode | Outage dễ dẫn tới bypass control |
| V4-21 | Medium | Thiếu golden-run diff | Upgrade làm thay đổi output âm thầm |
| V4-22 | Medium | E-Bookkeeping wording có thể bị hiểu quá tuyệt đối | Lưu sai record pháp định |
| V4-23 | Medium | NTA registration lookup chưa lưu evidence-at-time | Không chứng minh lịch sử tra cứu |
| V4-24 | High | My Number chưa có default-deny hard gate | Xử lý vượt purpose/quyền |
| V4-25 | Medium | Owner vẫn là placeholder không có release blocker | Accountability mơ hồ |
| V4-26 | Medium | Kết luận lặp lại ở nhiều phần | Khó sử dụng và dễ lệch khi cập nhật |
| V4-27 | Medium | Không có open legal/vendor assumptions register | Unknowns bị coi như facts |
| V4-28 | Medium | Provider data reuse/retention/deletion chưa nằm trong schema | Audit contract khó |
| V4-29 | Medium | Downstream transaction/reconciliation chưa có trong contract | Khó phát hiện/đảo giao dịch sai |
| V4-30 | Medium | Không có explicit stop-auto-pass authority | Silent degradation kéo dài |

---

# Phụ lục B — Vấn đề đã được xử lý trong v4

| ID | Cách xử lý | Trạng thái |
| --- | --- | --- |
| V4-01 | Thêm dual-track APPI current law + 2026 readiness, effective-date gate | Đã xử lý trong brief |
| V4-02 | Thêm AI Act, Điều 13 guideline, AI Basic Plan và legal register | Đã xử lý trong brief |
| V4-03 | Thay/giải thích thuật ngữ theo APPI/Japan context | Đã xử lý |
| V4-04 | Thêm schema legal-change ticket và status taxonomy | Đã xử lý |
| V4-05 | Đổi thành immutable quarantine raw store, restricted access | Đã xử lý |
| V4-06 | Phân rã location theo storage/inference/log/backup/support/training | Đã xử lý |
| V4-07 | Dùng ví dụ Japan-local trung tính; cross-border không còn hard-code | Đã xử lý |
| V4-08 | Thêm capability matrix và model/locale-specific gate | Đã xử lý |
| V4-09 | Cập nhật Google processors là đã discontinued | Đã xử lý |
| V4-10 | Thêm Azure v2.1/v3.0 support dates và migration requirement | Đã xử lý |
| V4-11 | Thêm source/customer/template/time split và leakage control | Đã xử lý |
| V4-12 | Thêm minimum sample và confidence/bootstrap interval | Đã xử lý |
| V4-13 | Thêm coverage-risk curve/selective prediction | Đã xử lý |
| V4-14 | Thêm authenticity signal layer riêng | Đã xử lý |
| V4-15 | Thêm autonomy levels và high-impact prohibition mặc định | Đã xử lý |
| V4-16 | Thêm DLP/output exfiltration, SBOM, signing, dependency controls | Đã xử lý |
| V4-17 | Thêm contract/location/masking controls cho vendor reviewer | Đã xử lý |
| V4-18 | Thêm contamination/leakage/provenance check trước dataset approval | Đã xử lý |
| V4-19 | Thêm data-flow re-review cho failover region/provider | Đã xử lý |
| V4-20 | Thêm queue-only/human-only/fallback/reject/quarantine modes | Đã xử lý |
| V4-21 | Thêm immutable golden corpus và output diff | Đã xử lý |
| V4-22 | Sửa wording: map exact record type và applicable method | Đã xử lý |
| V4-23 | Thêm timestamp/query/response evidence cho NTA lookup | Đã xử lý |
| V4-24 | Thêm My Number default-deny hard gate | Đã xử lý |
| V4-25 | Thêm required owner role và release blocker | Đã xử lý một phần; vẫn cần tổ chức điền tên cụ thể |
| V4-26 | Hợp nhất kết luận và chuyển chi tiết vào register | Đã xử lý |
| V4-27 | Thêm legal register và evidence package; vẫn cần project-specific assumptions | Đã xử lý một phần |
| V4-28 | Thêm reuse/retention/deletion fields trong governance object | Đã xử lý |
| V4-29 | Thêm transaction ID và reconciliation status | Đã xử lý |
| V4-30 | Thêm stop authority cho Operations/SRE/Security/Privacy | Đã xử lý |

### B.1 Việc chưa thể đóng chỉ bằng tài liệu

1. Điền tên owner/approver thực tế.
2. Chốt use case, field criticality và false-accept budgets.
3. Xác nhận model/API/SKU/region bằng văn bản từ vendor.
4. Chạy benchmark trên corpus doanh nghiệp Nhật thực tế.
5. Legal/tax mapping theo loại chứng từ và hợp đồng.
6. Kiểm thử DR, incident, rollback, reconciliation và reviewer capacity.
7. Theo dõi Cabinet Order/PPC rules cho APPI amendment 2026.

---

# Phụ lục C — Change log v3 → v4

| Khu vực | v3 | v4 |
| --- | --- | --- |
| Legal snapshot | APPI/guidelines hiện hành | Thêm APPI 2026 amendment readiness và status tracking |
| AI governance | AI Guidelines for Business | Thêm AI Act, Article 13 guideline, AI Basic Plan |
| Intake | Raw store trước security boundary | Immutable quarantine raw store + trusted zone |
| Data contract | Processing location chung | Activity-level locations, reuse, retention, deletion evidence |
| Models | Vendor-level support | Layer/model/locale-specific capability matrix |
| Lifecycle | General deprecation watch | Current Google/Azure dates + inventory/migration gates |
| Benchmark | Slices và scorecard | Leakage control, intervals, coverage-risk, minimum sample |
| Security | Malware/prompt injection | Thêm supply chain, output exfiltration, authenticity, autonomy ceiling |
| Review | Independent UI | Thêm vendor-worker access và contamination checks |
| Operations | Retry/DR/FinOps | Thêm degraded mode, golden-run diff, failover privacy re-review |
| Accountability | Placeholder owner | Release blocker và stop authority |

---

# Phụ lục D — Evidence register và tài liệu tham khảo chính thức

> Các nguồn phải được kiểm tra lại tại mỗi kỳ review; link và nội dung có thể thay đổi.

## D.1 Nhật Bản — privacy và AI governance

1. PPC, công bố Đạo luật sửa đổi APPI, 17/07/2026:  
   https://www.ppc.go.jp/news/press/2026/260717/
2. PPC, tóm tắt nội dung sửa đổi APPI 2026:  
   https://www.ppc.go.jp/files/pdf/260717_kaiseihounitsuite.pdf
3. PPC, hệ thống luật và hướng dẫn APPI:  
   https://www.ppc.go.jp/personalinfo/legal/
4. PPC, hướng dẫn chuyển personal data cho bên thứ ba ở nước ngoài:  
   https://www.ppc.go.jp/personalinfo/legal/guidelines_offshore/
5. PPC, My Number / Specific Personal Information guidance:  
   https://www.ppc.go.jp/legal/policy/my_number_guideline_jigyosha
6. Cabinet Office, Outline of the AI Act (Act No. 53 of 2025):  
   https://www8.cao.go.jp/cstp/ai/ai_hou_gaiyou_en.pdf
7. Cabinet Office, Guideline to Promote Appropriate Research, Development and Utilization of AI:  
   https://www8.cao.go.jp/cstp/ai/ai_guideline/ai_gl_eng_20260116.pdf
8. Cabinet Office, First AI Basic Plan, provisional English:  
   https://www8.cao.go.jp/cstp/stmain/20260619ai/aiplan_2601_draft_en.pdf
9. METI, AI Guidelines for Business v1.2:  
   https://www.meti.go.jp/shingikai/mono_info_service/ai_shakai_jisso/20260331_report.html

## D.2 Records và tax

10. NTA, Electronic Bookkeeping Act portal:  
    https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/tokusetsu/index.htm
11. NTA, Qualified Invoice Issuer Publication Site:  
    https://www.invoice-kohyo.nta.go.jp/

## D.3 Google Cloud

12. Document AI locations:  
    https://docs.cloud.google.com/document-ai/docs/regions
13. Document AI deprecations:  
    https://docs.cloud.google.com/document-ai/docs/deprecation
14. Document AI release notes:  
    https://docs.cloud.google.com/document-ai/docs/release-notes
15. Document AI security/compliance:  
    https://docs.cloud.google.com/document-ai/docs/security

## D.4 Microsoft Azure

16. Document Intelligence OCR language support:  
    https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/language-support/ocr?view=doc-intel-4.0.0
17. Document Intelligence model overview:  
    https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/model-overview?view=doc-intel-4.0.0
18. Document Intelligence What’s New / lifecycle:  
    https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/whats-new?view=doc-intel-4.0.0
19. Custom neural model:  
    https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/train/custom-neural?view=doc-intel-4.0.0
20. Service limits:  
    https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0

## D.5 AWS

21. Amazon Textract quotas and fixed limits, including language/layout limitations:  
    https://docs.aws.amazon.com/textract/latest/dg/limits-document.html
22. Amazon Textract best practices:  
    https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html
23. Amazon Textract overview:  
    https://docs.aws.amazon.com/textract/latest/dg/what-is.html

---

**Kết thúc tài liệu — phiên bản 4.0**
