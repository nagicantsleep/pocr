# Brief tổng thể về hệ thống Document AI cấp doanh nghiệp tại Nhật Bản

**Phạm vi:** kiến trúc, mô hình AI, luồng xử lý, dữ liệu, human-in-the-loop, bảo mật, vận hành, MLOps/DocOps, benchmark nhà cung cấp và khung tuân thủ cho hệ thống được xây dựng, sử dụng, vận hành và liên tục cải tiến tại Nhật Bản; khách hàng/chủ thể sử dụng là doanh nghiệp Nhật.

**Thời điểm đối chiếu tài liệu:** 17/07/2026.

> **Lưu ý pháp lý:** tài liệu này là brief kỹ thuật và quản trị rủi ro, không thay thế ý kiến tư vấn pháp lý, thuế hoặc kiểm toán tại Nhật Bản. Các yêu cầu cụ thể phải được xác nhận theo ngành, loại tài liệu, hợp đồng khách hàng và luồng dữ liệu thực tế.

## Thông tin kiểm soát tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 3.0 |
| Trạng thái | Bản rà soát kỹ thuật/pháp lý sơ bộ |
| Ngày cập nhật | 17/07/2026 |
| Phạm vi địa lý | Nhật Bản |
| Đối tượng khách hàng | Doanh nghiệp Nhật Bản |
| Chủ sở hữu tài liệu | _(cần bổ sung tên vai trò hoặc đơn vị chịu trách nhiệm)_ |
| Người phê duyệt | Product, Security, Privacy/Legal, Operations |
| Chu kỳ rà soát | 3 tháng; hoặc ngay khi có thay đổi lớn về luật, region, model, API, giá hay deprecation |
| Tài liệu nguồn | `standard-document-ai-brief-v2.md` |
| Thay đổi chính so với v2 | Chuyển toàn bộ bối cảnh từ Việt Nam sang Nhật Bản; thêm hard gate về tiếng Nhật và data location; sửa thông tin nhà cung cấp lỗi thời; thêm threat model cho tài liệu độc hại/GenAI; bổ sung calibration, NFR, DR, FinOps, scorecard benchmark và stage gate |

## Mục lục

1. Kết luận điều hành
2. Phạm vi, giả định và nguyên tắc ra quyết định
3. Các hard gate cho môi trường Nhật Bản
4. Khái niệm và đầu ra chuẩn của Document AI
5. Kiến trúc tham chiếu
6. Thiết kế từng thành phần
7. Chiến lược mô hình
8. Canonical data contract cho Nhật Bản
9. Confidence, calibration và cơ chế quyết định
10. Human-in-the-loop
11. Model lifecycle, MLOps và DocOps
12. Observability, NFR, DR và FinOps
13. Security, privacy và AI threat model
14. Compliance và governance tại Nhật Bản
15. So sánh Google, Azure và AWS trong bối cảnh Nhật Bản
16. Build, buy hay hybrid
17. Operating model và phân quyền
18. Lộ trình triển khai và stage gate
19. Anti-pattern cần tránh
20. Kiến trúc khuyến nghị cuối cùng
21. Phụ lục A — Vấn đề của v2 và cách sửa trong v3
22. Phụ lục B — Scorecard benchmark đề xuất
23. Tài liệu tham khảo

---

## 1. Kết luận điều hành

Một hệ thống Document AI cấp doanh nghiệp tại Nhật Bản không nên được thiết kế như một dịch vụ OCR đơn lẻ. Nó phải là một nền tảng xử lý tài liệu có khả năng:

1. tiếp nhận tài liệu không tin cậy một cách an toàn;
2. bảo toàn bản gốc và chuỗi bằng chứng;
3. đọc chính xác tiếng Nhật, tài liệu song ngữ và bố cục đặc thù;
4. phân loại, tách, trích xuất và chuẩn hóa dữ liệu;
5. kiểm tra quy tắc nghiệp vụ;
6. định tuyến theo rủi ro sang xử lý tự động hoặc human review;
7. đáp ứng yêu cầu privacy, lưu trữ chứng từ, audit và hợp đồng của doanh nghiệp Nhật;
8. kiểm soát model drift, deprecation, chi phí và thay đổi nhà cung cấp.

### 1.1 Kết luận lựa chọn công nghệ

Không nên chọn nhà cung cấp chỉ từ bảng tính năng. Lựa chọn phải dựa trên **hard gate + benchmark trên dữ liệu Nhật Bản**.

* **Azure AI Document Intelligence** là một giả thuyết benchmark mạnh cho OCR/layout tiếng Nhật vì tài liệu chính thức liệt kê hỗ trợ tiếng Nhật in và viết tay. Tuy nhiên, từng model, API version, SKU và region phải được xác nhận trong quá trình procurement.
* **Google Cloud Document AI** có khả năng classify/split/extract tốt, nhưng tại thời điểm đối chiếu không liệt kê location tại Nhật Bản; các location châu Á được nêu gồm Mumbai và Singapore. Việc sử dụng vì vậy cần được coi là luồng xử lý ngoài Nhật Bản và phải qua privacy/legal/contract gate. Human in the Loop tích hợp của Google đã bị deprecated, nên review workflow phải được xây độc lập.
* **Amazon Textract** không nên được giả định là OCR chính cho tài liệu tiếng Nhật: tài liệu chính thức hiện chỉ liệt kê sáu ngôn ngữ châu Âu, không hỗ trợ chữ dọc và chỉ hỗ trợ chữ viết tay tiếng Anh. AWS vẫn có thể là nền tảng lưu trữ, orchestration và vận hành nếu kết hợp OCR/IDP khác.
* Benchmark nên có thêm ít nhất một giải pháp OCR/IDP chuyên cho thị trường Nhật Bản, không giới hạn ở ba hyperscaler.

### 1.2 Kiến trúc khuyến nghị

Khuyến nghị là kiến trúc **hybrid, event-driven, vendor-neutral**:

```text
Secure Intake
  → Immutable Raw Store
  → Document Security Boundary
  → Quality/Pre-processing
  → Classify/Split
  → OCR/Layout/Extraction
  → Normalize/Enrich
  → Validation & Risk Engine
  → Auto-pass hoặc Human Review
  → Downstream Integration
  → Feedback Governance
```

Các thành phần tạo lợi thế và kiểm soát rủi ro — canonical schema, validation, review, audit, policy, dataset governance, observability — nên do doanh nghiệp kiểm soát. OCR/layout/model hosting có thể dùng managed service nếu vượt qua hard gate.

---

## 2. Phạm vi, giả định và nguyên tắc ra quyết định

### 2.1 Phạm vi

Tài liệu này áp dụng cho hệ thống:

* được triển khai và vận hành bởi tổ chức tại Nhật Bản;
* phục vụ doanh nghiệp Nhật Bản;
* xử lý tài liệu tiếng Nhật, tiếng Anh hoặc song ngữ;
* có thể chứa dữ liệu cá nhân, dữ liệu nhân sự, hợp đồng, hóa đơn, chứng từ kế toán, thông tin tài chính hoặc mã số cá nhân;
* có vòng đời cải tiến liên tục bằng correction, annotation, benchmark và retraining.

### 2.2 Giả định

* Tài liệu đầu vào là **untrusted content** kể cả khi đến từ khách hàng hợp lệ.
* Một tài liệu có thể vừa là bằng chứng pháp lý vừa là input cho AI.
* Không phải mọi trường đều được phép tự động hóa.
* Không có model nào được coi là phù hợp chỉ vì có demo tốt.
* Data residency, cross-border transfer và subcontractor chain là thuộc tính của toàn pipeline, không chỉ của storage bucket.
* Output AI không phải ground truth cho đến khi vượt qua validation hoặc review phù hợp.

### 2.3 Nguyên tắc ra quyết định

1. **Hard gate trước, điểm số sau.** Không đáp ứng yêu cầu bắt buộc thì không được bù bằng giá rẻ hay accuracy trung bình cao.
2. **Đánh giá theo trường và mức rủi ro.** Không dùng một accuracy trung bình cho cả tài liệu.
3. **Evidence first.** Mọi dữ liệu quan trọng phải truy ngược được tới trang, polygon/span và file gốc.
4. **Raw is immutable.** Không ghi đè tài liệu gốc hoặc raw OCR.
5. **Human review độc lập nhà cung cấp.** Không gắn vận hành cốt lõi vào một UI vendor.
6. **No direct action from untrusted text.** Nội dung tài liệu không được trở thành chỉ thị hệ thống hay trực tiếp kích hoạt tác vụ đặc quyền.
7. **Version everything.** Model, prompt, schema, rule, preprocessing và pipeline phải có version.
8. **Japan-first benchmark.** Corpus phải phản ánh tài liệu thực tế tại Nhật, không dùng bộ mẫu tiếng Anh làm đại diện.

---

## 3. Các hard gate cho môi trường Nhật Bản

Một giải pháp chỉ được đưa vào pilot production khi vượt qua tất cả hard gate áp dụng.

| Nhóm | Hard gate | Bằng chứng cần có |
| --- | --- | --- |
| Ngôn ngữ | Hỗ trợ tiếng Nhật in; nếu use case cần thì hỗ trợ chữ viết tay và chữ dọc | Tài liệu vendor + benchmark độc lập |
| Bố cục | Đọc được bảng, con dấu, furigana, biểu mẫu, tài liệu song ngữ và multi-page | Test set đại diện |
| Data location | Xác định chính xác nơi storage, processing, logging, support và backup diễn ra | Kiến trúc + DPA/SCC-equivalent/contract annex |
| APPI | Có lawful purpose, data map, vendor/subprocessor control, retention và incident procedure | Privacy review/DPIA nội bộ |
| Bảo mật | Private connectivity phù hợp, encryption, IAM, audit, malware isolation và egress control | Security assessment |
| Audit | Lưu bản gốc, hash, evidence, version và correction history | Data contract + audit test |
| Chất lượng | Đạt target theo field/risk; false accept không vượt error budget | Benchmark report |
| Vận hành | Có retry, DLQ, idempotency, rate control, rollback và reprocess | Chaos/failure test |
| DR | Đạt RTO/RPO đã phê duyệt | DR test |
| Chi phí | Có unit economics và guardrail theo page/document/model | Cost model + load test |
| Lifecycle | Có deprecation watch, model registry và exit plan | Runbook + contract |

### 3.1 Trường hợp loại ngay

Giải pháp phải bị loại hoặc giới hạn use case khi:

* không hỗ trợ tiếng Nhật nhưng tài liệu chính là tiếng Nhật;
* không hỗ trợ chữ dọc trong khi corpus có tỷ lệ chữ dọc đáng kể;
* không xác định được nơi xử lý hoặc subprocessor;
* không cung cấp evidence đủ cho audit;
* không thể tắt sử dụng dữ liệu khách hàng để train dịch vụ chung theo yêu cầu hợp đồng;
* không có cách reprocess và truy vết version;
* accuracy ở trường tài chính/pháp lý không đạt false-accept budget.

---

## 4. Khái niệm và đầu ra chuẩn của Document AI

### 4.1 Document AI giải quyết bài toán gì?

Đầu vào thường gồm:

* PDF điện tử, PDF scan, TIFF và ảnh;
* ảnh chụp mờ, nghiêng, có bóng hoặc phản quang;
* form Nhật cũ, fax, tài liệu có con dấu;
* chữ ngang và chữ dọc;
* kanji, hiragana, katakana, Latin, chữ số và ký hiệu trộn lẫn;
* ký tự full-width/half-width;
* ngày theo niên hiệu Nhật và lịch Tây;
* địa chỉ Nhật không đồng nhất cách viết;
* bảng nhiều trang, merged cell và chú thích;
* nhiều tài liệu logic ghép trong một file.

### 4.2 Ba tầng thông minh

**Perception:** OCR, handwriting, layout, table, checkbox, stamp/signature indication.

**Understanding:** document type, page range, field semantics, relationship, reading order.

**Decision/action:** validation, reconciliation, risk classification, workflow routing và downstream action.

Không gom cả ba tầng vào một prompt LLM. Perception, extraction, validation và action phải có boundary rõ ràng để kiểm thử, audit và rollback.

### 4.3 Document Object chuẩn

Đầu ra nên bao gồm:

* text và cấu trúc trang;
* polygon/span và reading order;
* loại tài liệu, phạm vi trang và language/script;
* raw value, normalized value và derived value;
* bảng, hàng, cột và merged cell;
* confidence và calibration metadata;
* evidence;
* model/prompt/schema/rule/pipeline version;
* trạng thái validation và review;
* data classification, legal hold và retention class;
* processing location và provider/subprocessor metadata.

---

## 5. Kiến trúc tham chiếu

```text
Nguồn tài liệu
Portal / API / Email / SFTP / Scanner / Mobile / DMS
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 1. Secure Intake Gateway                             │
│ Auth, quota, MIME, hash, allowlist, job metadata     │
└────────────────────────┬─────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────┐
│ 2. Immutable Raw Store                               │
│ Original bytes, WORM/legal hold, retention, KMS      │
└────────────────────────┬─────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────┐
│ 3. Document Security Boundary                        │
│ Malware, sandbox, CDR, parser isolation, bomb limits │
└────────────────────────┬─────────────────────────────┘
                         ▼ event/job
┌──────────────────────────────────────────────────────┐
│ 4. Orchestration & Queue                             │
│ State, retry, idempotency, quota, priority, DLQ      │
└────────────────────────┬─────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────┐
│ 5. Quality & Pre-processing                          │
│ Rotate, deskew, QC, render, page/format validation   │
└────────────────────────┬─────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────┐
│ 6. Classify & Split                                  │
│ Type, page range, unknown/OOD, routing               │
└────────────────────────┬─────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────┐
│ 7. OCR / Layout / Extraction                         │
│ Managed OCR, custom, prebuilt, query, multimodal     │
└────────────────────────┬─────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────┐
│ 8. Normalize & Enrich                                │
│ Japanese dates, width, address, currency, master data│
└────────────────────────┬─────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────┐
│ 9. Validation, Policy & Risk Engine                  │
│ Schema, rules, cross-check, calibration, materiality │
└───────────────┬─────────────────────────────┬────────┘
                │ auto-pass                   │ exception
                ▼                             ▼
       Downstream systems              Human Review Queue
                │                             │
                └──────────────┬──────────────┘
                               ▼
                  Approved Feedback & Dataset
```

### 5.1 Boundary bắt buộc

* **Security boundary** đứng trước parser/model để tránh malware, malformed file và resource exhaustion.
* **Policy enforcement point** đứng giữa AI output và downstream action.
* **Review/correction store** tách khỏi production output và training dataset.
* **Provider adapter** tách JSON vendor khỏi canonical schema.
* **Raw store** không bị thay đổi bởi preprocessing.

---

## 6. Thiết kế từng thành phần

### 6.1 Secure Intake Gateway

Trách nhiệm:

* xác thực người dùng, ứng dụng hoặc tenant;
* kiểm tra MIME bằng magic bytes, không chỉ file extension;
* giới hạn kích thước, số trang, độ phân giải, nesting và tỷ lệ nén;
* tính SHA-256 và phát hiện duplicate/replay;
* gắn `document_id`, `case_id`, `tenant_id`, `correlation_id`;
* ghi nguồn, mục đích xử lý, retention class và data classification;
* trả `job_id`; không đồng nhất upload success với processing success.

### 6.2 Immutable Raw Store

Tách tối thiểu:

```text
raw/        original bytes, hash, source metadata
derived/    rendered pages, thumbnails, transformed copies
results/    versioned canonical JSON and vendor payloads
review/     reviewer decisions and corrections
dataset/    approved train/validation/test artifacts
audit/      append-only events and evidence manifests
```

Cần hỗ trợ legal hold, retention policy, object versioning và kiểm soát xóa. Reprocess luôn tham chiếu cùng hash nhưng tạo processing run mới.

### 6.3 Document Security Boundary

Kiểm tra và cô lập:

* malware, embedded files, scripts, macros và active content;
* malformed PDF/TIFF, parser exploit và decompression bomb;
* file mã hóa/password-protected;
* số trang hoặc kích thước render bất thường;
* external references và network callbacks;
* file polyglot hoặc MIME mismatch.

Parser/render service chạy với quyền tối thiểu, không có credential downstream, egress mặc định bị chặn và có resource/time limit. Content Disarm and Reconstruction chỉ tạo derived copy; không thay raw file.

### 6.4 Orchestrator và queue

Mỗi step cần:

* idempotency key;
* timeout và retry policy riêng;
* exponential backoff + jitter;
* dead-letter queue và replay có kiểm soát;
* concurrency/quota control;
* priority theo SLA và materiality;
* deterministic state transition;
* exactly-once business effect, dù hạ tầng thường chỉ bảo đảm at-least-once delivery.

### 6.5 Quality và preprocessing

Đo trước khi sửa:

* blur, glare, shadow, skew;
* DPI và kích thước ký tự;
* clipping, blank page, page orientation;
* tỷ lệ chữ dọc/ngang;
* page corruption;
* fax/noise score.

Không preprocessing quá mạnh. Lưu transformation graph và tham số. Benchmark phải so sánh raw-vs-preprocessed để tránh làm mất dấu, nét kanji hoặc đường bảng.

### 6.6 Classification và splitting

Output tối thiểu:

```json
{
  "type": "qualified_invoice",
  "pageStart": 1,
  "pageEnd": 2,
  "confidence": 0.97,
  "oodScore": 0.08,
  "modelVersion": "classifier-2026-07",
  "reasonCodes": []
}
```

Luôn có `unknown/other` và OOD routing. Không buộc mọi tài liệu vào lớp đã biết.

### 6.7 Extraction

Tách rõ:

* `extracted`: có bằng chứng trực tiếp;
* `normalized`: biến đổi có quy tắc từ extracted value;
* `enriched`: lấy từ master/reference data;
* `derived`: suy luận hoặc tính toán;
* `not_found`: không có bằng chứng;
* `not_applicable`: trường không áp dụng.

LLM không được điền giá trị thiếu chỉ để thỏa schema. Với trường rủi ro cao, yêu cầu evidence span và validation độc lập.

### 6.8 Normalize và enrich cho Nhật Bản

Các phép chuẩn hóa cần version và reversible metadata:

* full-width ↔ half-width;
* Unicode normalization;
* kanji numeral ↔ Arabic digit khi được phép;
* niên hiệu Nhật ↔ ISO date;
* họ tên và corporate name spacing;
* địa chỉ, prefecture, postal code;
* yen, tax-inclusive/tax-exclusive, rounding;
* số điện thoại và mã doanh nghiệp;
* invoice registration lookup;
* master vendor/customer mapping.

**Không ghi đè raw value.** Unicode/NFKC có thể làm thay đổi ký tự có ý nghĩa; chỉ dùng cho trường normalized và lưu `normalizationSteps`.

### 6.9 Validation và policy engine

Nhóm rule:

* schema/type/regex;
* arithmetic và tax reconciliation;
* cross-page consistency;
* master data lookup;
* duplicate/fraud signal;
* contract date/term;
* mandatory-document completeness;
* policy theo tenant, industry và materiality.

Decision engine không được phụ thuộc duy nhất vào model confidence.

### 6.10 Downstream integration

* Dùng outbox/event pattern để tránh ghi trùng.
* Mọi write action phải có policy check.
* LLM/extractor không sở hữu credential ghi ERP/CRM.
* Cần reconciliation job giữa accepted output và downstream record.
* Hỗ trợ correction/reversal, không chỉ create.

---

## 7. Chiến lược mô hình

### 7.1 OCR/layout managed service

Thường nên mua thay vì tự huấn luyện từ đầu, nhưng phải benchmark riêng:

* tiếng Nhật in;
* tiếng Nhật viết tay nếu cần;
* chữ dọc;
* mixed script;
* reading order;
* table và stamp-adjacent text;
* latency/cost theo region.

### 7.2 Prebuilt extractor

Dùng khi schema gần nghiệp vụ và coverage Nhật Bản đã được chứng minh. Không suy luận rằng model invoice của vendor được tối ưu cho qualified invoice Nhật chỉ vì tên là “invoice”.

### 7.3 Custom template

Phù hợp với form cố định nhưng dễ suy giảm khi:

* form thay đổi;
* scan lệch;
* nhiều chi nhánh dùng biến thể;
* có chữ dọc hoặc stamp che trường.

### 7.4 Custom neural/semantic extractor

Phù hợp với nhiều layout và từ vựng biến thiên. Cần ground truth theo field, hard-case set và OOD test.

### 7.5 Generative/multimodal extractor

Dùng cho trường ngữ nghĩa phức tạp, tài liệu dài hoặc zero/few-shot, nhưng phải có:

* JSON schema;
* prompt/model version;
* temperature thấp khi có thể;
* evidence requirement;
* `not_found` rõ ràng;
* field allowlist;
* output validation;
* prompt-injection isolation;
* no direct tool privilege;
* cost/token/page limit;
* deterministic regression suite.

### 7.6 Derived-field model

Trường derived không được giả là OCR. Ví dụ:

* risk category;
* contract duration;
* completeness assessment;
* anomaly classification;
* inferred tax treatment.

Mỗi derived field cần `derivationMethod`, input references và version.

### 7.7 Ensemble và fallback

Chỉ dùng multi-model fallback khi có policy rõ:

```text
Primary OCR
  → quality/coverage check
  → secondary OCR only for failed pages
  → reconciliation
  → human review if disagreement is material
```

Không gọi nhiều model cho mọi tài liệu nếu không chứng minh lợi ích so với chi phí và latency.

---

## 8. Canonical data contract cho Nhật Bản

Không cho downstream phụ thuộc JSON riêng của Google, Azure hay AWS.

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
    "originalMimeType": "application/pdf"
  },
  "governance": {
    "jurisdiction": ["JP"],
    "dataClassification": "confidential-personal",
    "purposeCode": "AP_PROCESSING",
    "retentionClass": "JP_TAX_DOCUMENT",
    "legalHold": false,
    "crossBorderProcessing": true,
    "processingLocations": ["asia-southeast1"],
    "provider": "example-provider"
  },
  "document": {
    "type": "qualified_invoice",
    "typeConfidence": 0.97,
    "oodScore": 0.06,
    "pageRange": [1, 2],
    "languages": ["ja", "en"],
    "writingDirections": ["horizontal"]
  },
  "fields": {
    "invoiceNumber": {
      "rawValue": "請求書番号：ＡＢ－００１２５",
      "normalizedValue": "AB-00125",
      "dataType": "string",
      "confidence": 0.96,
      "calibratedProbability": 0.91,
      "normalizationSteps": ["NFKC", "REMOVE_LABEL"],
      "evidence": [{
        "page": 1,
        "polygon": [[0.10,0.20],[0.32,0.20],[0.32,0.25],[0.10,0.25]],
        "text": "請求書番号：ＡＢ－００１２５"
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
  "processing": {
    "runId": "run_789",
    "pipelineVersion": "3.0.0",
    "preprocessingVersion": "2.1.0",
    "modelProvider": "provider",
    "modelId": "jp-invoice-v3",
    "modelVersion": "3",
    "promptVersion": null,
    "schemaVersion": "jp-doc-1.0",
    "processedAt": "2026-07-17T10:01:18+09:00"
  },
  "review": {
    "required": true,
    "reasonCodes": ["TOTAL_MISMATCH"],
    "decision": null
  }
}
```

### 8.1 Thuộc tính bắt buộc bổ sung so với v2

* `jurisdiction`;
* `purposeCode`;
* `dataClassification`;
* `retentionClass` và `legalHold`;
* `crossBorderProcessing` và `processingLocations`;
* `writingDirections`;
* `oodScore`;
* `calibratedProbability`;
* `normalizationSteps`;
* `runId` và đầy đủ version;
* reason code có severity.

---

## 9. Confidence, calibration và cơ chế quyết định

### 9.1 Confidence không phải xác suất đã được hiệu chỉnh

Confidence do vendor trả về có thể không so sánh được giữa:

* model khác nhau;
* field khác nhau;
* document type khác nhau;
* version khác nhau;
* provider khác nhau.

Cần đo calibration trên dữ liệu thật bằng reliability curve, Expected Calibration Error hoặc Brier score khi phù hợp. Nếu 1.000 trường có confidence khoảng 0,9 nhưng chỉ 700 trường đúng, confidence đó không thể dùng trực tiếp như xác suất 90%.

### 9.2 Threshold theo field và materiality

Ví dụ minh họa, không phải giá trị production:

| Trường | Policy |
| --- | --- |
| Tên nhà cung cấp | Auto-pass chỉ khi confidence đã hiệu chỉnh đạt ngưỡng và master data match |
| Số hóa đơn | Regex + duplicate check + confidence cao |
| Tổng tiền | Arithmetic reconciliation bắt buộc; mismatch luôn review |
| Registration number | Validate format và đối chiếu nguồn tin cậy khi cần |
| Điều khoản pháp lý | Không auto-pass chỉ dựa trên confidence |
| My Number | Xử lý theo use case hợp pháp, quyền truy cập đặc biệt và masking |

### 9.3 Error budget

Mỗi use case cần đặt:

* false accept budget;
* false reject budget;
* maximum financial exposure;
* review capacity;
* acceptable abstention/OOD rate.

Ví dụ, “accuracy 97%” là không đủ nếu 3% lỗi tập trung ở tổng tiền hoặc mã số thuế.

### 9.4 Risk score tổng hợp

```text
reviewRisk =
    w1 × calibratedUncertainty
  + w2 × poorImageQuality
  + w3 × businessRuleFailure
  + w4 × outOfDistributionScore
  + w5 × legalOrFinancialMateriality
  + w6 × templateHistoricalError
  + w7 × crossBorderOrPrivacySensitivity
  + w8 × modelDisagreement
```

Trọng số phải được đánh giá định kỳ và không thay đổi âm thầm.

### 9.5 Decision bands

* **Low risk:** straight-through processing.
* **Medium risk:** field-level review.
* **High risk:** full review/dual control.
* **Unknown/OOD:** manual triage hoặc reject.
* **Security suspect:** quarantine, không đưa vào model pipeline thông thường.

---

## 10. Human-in-the-loop

Human review là control bắt buộc, không phải fallback tạm thời.

### 10.1 Loại review

* full-document review;
* field-level review;
* random sampling của auto-pass;
* dual control cho tài chính/pháp lý quan trọng;
* adjudication khi hai reviewer bất đồng;
* security/manual triage cho file bất thường.

### 10.2 Review UI

Cần có:

* viewer bản gốc và derived copy;
* highlight evidence;
* raw/normalized value;
* confidence và reason code;
* validation warnings;
* history và reviewer identity;
* keyboard workflow;
* masking theo role;
* Japanese IME-friendly input;
* hiển thị chữ dọc/bảng/con dấu đúng orientation;
* SLA/priority;
* audit append-only.

### 10.3 Governance correction

Correction không được đẩy thẳng vào training set. Quy trình:

```text
Reviewer correction
  → validation/adjudication
  → PII and licensing check
  → dataset approval
  → dataset version
  → training candidate
```

Theo dõi reviewer agreement, correction rate và bias theo team/template.

### 10.4 Vendor independence

Review service nên là module riêng. Đặc biệt, không được thiết kế dựa trên giả định rằng Google Document AI còn cung cấp HITL tích hợp; tính năng này đã bị deprecated.

---

## 11. Model lifecycle, MLOps và DocOps

### 11.1 Dataset split

Tối thiểu:

* training;
* validation;
* frozen test;
* shadow production;
* regression suite;
* hard cases;
* OOD/unknown;
* adversarial/malicious-content set;
* Japanese script/layout slices.

### 11.2 Japan benchmark slices

Đánh giá riêng:

* kanji/hiragana/katakana/Latin/digits;
* full-width và half-width;
* Japanese era và Gregorian date;
* horizontal và vertical writing;
* handwritten notes;
* seals/stamps;
* fax/noisy scan;
* bilingual Japanese-English;
* Japanese names, addresses và corporate forms;
* yen/tax/rounding;
* qualified invoice;
* electronic transaction records;
* My Number-related documents nếu use case hợp pháp;
* rare templates và template drift.

### 11.3 Versioning

Lưu:

* provider, service và API version;
* processor/model ID/version;
* prompt/template version;
* preprocessing version;
* schema version;
* normalization version;
* rule-set version;
* dataset version;
* pipeline/container/IaC version.

### 11.4 Release process

```text
Train/configure
  → Offline evaluation
  → Calibration test
  → Regression and adversarial test
  → Security/privacy review
  → Shadow deployment
  → Canary by tenant/document type
  → Compare old/new
  → Progressive rollout
  → Monitor error budget
  → Rollback if violated
```

Không overwrite model production nếu mất khả năng so sánh/rollback.

### 11.5 Drift

Theo dõi:

* unknown/OOD rate;
* template distribution;
* field null rate;
* confidence và calibration drift;
* correction rate;
* business-rule failure;
* accuracy theo language/script/layout/vendor/tenant;
* image quality distribution;
* model disagreement;
* cost/page và latency drift.

### 11.6 Deprecation watch

Tạo registry có:

* end-of-support date;
* migration target;
* owner;
* affected tenants;
* regression status;
* rollback plan.

Google đã công bố nhiều processor legacy dừng ngày 30/06/2026; đây là ví dụ cho việc release note và deprecation phải là đầu vào vận hành, không phải hoạt động kiểm tra tùy hứng.

---

## 12. Observability, NFR, DR và FinOps

### 12.1 KPI kỹ thuật

* documents/pages processed;
* queue depth và age;
* P50/P95/P99 end-to-end latency;
* per-step latency;
* success/error/retry/timeout/throttle rate;
* DLQ volume;
* provider quota utilization;
* storage and egress volume;
* availability;
* reprocess rate.

### 12.2 KPI chất lượng

* classification precision/recall/F1;
* split boundary accuracy;
* OCR CER/WER theo script;
* field exact/normalized match;
* table cell accuracy;
* calibration error;
* OOD recall;
* false accept/false reject;
* correction rate;
* reviewer agreement.

### 12.3 KPI nghiệp vụ

* straight-through processing;
* review rate;
* handling time;
* cost per accepted document;
* downstream rejection/reversal;
* time-to-decision;
* financial error prevented;
* SLA breach;
* customer dispute rate.

### 12.4 NFR phải được định lượng

Ví dụ template:

| NFR | Target cần phê duyệt |
| --- | --- |
| Availability | theo tier dịch vụ, không dùng một target cho mọi use case |
| P95 latency | theo document size và sync/async flow |
| Throughput | pages/minute ở peak + burst |
| RTO | thời gian khôi phục pipeline |
| RPO | mức mất dữ liệu chấp nhận được cho metadata/result |
| Max document | MB, pages, dimensions, compression ratio |
| Data durability | raw/result/audit theo storage class |
| Review SLA | theo priority và giờ làm việc Nhật |
| Reprocess SLA | theo incident class |

### 12.5 Disaster recovery

* raw file và metadata phải có recovery plan tương xứng;
* model/config/schema/rule/IaC phải được backup/version-control;
* queue state cần reconciliation sau failover;
* tránh active-active nếu không có nhu cầu và làm tăng cross-border complexity;
* kiểm thử DR định kỳ, không chỉ viết runbook;
* xác định fallback khi provider region hoặc model unavailable.

### 12.6 FinOps

Cost model theo:

```text
cost/document =
  intake + storage + rendering + OCR + extraction
  + LLM tokens + network egress + review labor
  + reprocess + monitoring + retention
```

Theo dõi theo tenant, document type, model và stage. Guardrail:

* page/token limit;
* skip blank/duplicate pages;
* route model theo complexity;
* cache deterministic result theo content hash + version;
* alert khi unit cost hoặc reprocess rate tăng;
* không tối ưu chi phí bằng cách bỏ evidence/audit bắt buộc.

---

## 13. Security, privacy và AI threat model

### 13.1 Data security controls

* encryption in transit/at rest;
* customer-managed keys khi yêu cầu;
* workload identity/managed identity;
* least privilege và separation of duties;
* private connectivity/service perimeter khi khả dụng;
* no long-lived access key;
* append-only audit;
* tenant isolation;
* DLP/masking;
* secrets scanning;
* retention/deletion/legal hold;
* subprocessor inventory;
* support-access logging;
* training-use opt-out/contract control.

### 13.2 Threat model tài liệu độc hại

| Threat | Control |
| --- | --- |
| Malware/active content | sandbox, CDR, no execution, isolate renderer |
| Parser exploit | patched minimal image, syscall/network restriction, resource limits |
| Decompression/page bomb | limits trước và sau render |
| Password-protected file | quarantine/special workflow |
| External URL/reference | no egress by default |
| Hidden/white text | preserve evidence; compare visual layer và text layer |
| QR/link phishing | treat as data, không tự truy cập |
| Tenant data leakage | strict partitioning, per-tenant authorization |

### 13.3 Prompt injection và GenAI

Nội dung tài liệu có thể chứa câu như “bỏ qua hướng dẫn” hoặc “gửi dữ liệu tới URL này”. Hệ thống phải coi đó là dữ liệu, không phải instruction.

Controls:

* system instruction tách khỏi document content;
* delimit và label nguồn untrusted;
* tool allowlist và policy enforcement;
* model không có credential ghi hệ thống;
* network egress bị chặn hoặc qua proxy allowlist;
* output schema và semantic validator;
* evidence requirement;
* không tự động mở URL/attachment được trích từ tài liệu;
* test prompt injection trong regression suite;
* log tối thiểu, tránh đưa PII vào prompt/log không cần thiết;
* isolate RAG corpus và kiểm soát poisoning.

### 13.4 Incident response

Runbook phải bao gồm:

* containment và quarantine;
* xác định tenant/document/model/run bị ảnh hưởng;
* khóa downstream action;
* bảo toàn audit evidence;
* privacy/legal assessment;
* thông báo nội bộ, khách hàng và cơ quan có thẩm quyền khi áp dụng;
* reprocess sau remediation;
* post-incident regression case.

---

## 14. Compliance và governance tại Nhật Bản

### 14.1 APPI và hướng dẫn của PPC

Đối với personal data, cần xác định và ghi lại:

* mục đích sử dụng;
* phạm vi dữ liệu cần thiết;
* legal/business basis và thông báo phù hợp;
* chính xác/cập nhật trong phạm vi mục đích;
* retention và xóa;
* safety management measures;
* giám sát nhân viên, vendor và subprocessor;
* procedure cho leakage/loss/damage;
* quyền và yêu cầu của data subject khi áp dụng.

PPC yêu cầu các biện pháp quản lý an toàn tương xứng rủi ro và nhấn mạnh giám sát bên được ủy thác, bao gồm việc lựa chọn, hợp đồng, theo dõi tình trạng xử lý và kiểm soát tái ủy thác.

### 14.2 Chuyển dữ liệu ra nước ngoài

Nếu OCR/model xử lý ngoài Nhật Bản:

1. lập data-flow map đến country/region và subprocessor;
2. xác định đây là outsourcing hay cung cấp cho bên thứ ba theo cấu trúc pháp lý thực tế;
3. đánh giá điều kiện áp dụng của APPI và hướng dẫn PPC;
4. ghi contract controls, onward-transfer restrictions và audit rights;
5. theo dõi thay đổi luật/quy định tại nơi nhận;
6. thông báo/consent hoặc biện pháp tương đương khi yêu cầu;
7. ghi `processingLocations` trong processing record.

Việc nhà cung cấp có công ty con hoặc văn phòng tại Nhật không có nghĩa là API xử lý dữ liệu tại Nhật.

### 14.3 My Number và Specific Personal Information

Nếu hệ thống xử lý My Number:

* chỉ thu thập/sử dụng trong trường hợp pháp luật cho phép;
* quyền truy cập và masking phải chặt hơn personal data thông thường;
* không dùng tùy tiện cho training/evaluation;
* dataset phải được de-identify hoặc loại trừ theo policy;
* kiểm soát outsourcing/re-outsourcing;
* retention và deletion theo purpose và yêu cầu pháp luật;
* review UI không hiển thị cho role không cần thiết.

### 14.4 Electronic Bookkeeping Act

Đối với chứng từ thuế/kế toán:

* phân biệt electronic transaction data, electronic books/documents và scanner storage;
* lưu bản điện tử gốc khi giao dịch được nhận điện tử, không chỉ lưu bản OCR hay PDF render;
* bảo đảm searchability, integrity, retention và khả năng xuất trình theo phương thức áp dụng;
* Document AI output là chỉ mục/dữ liệu hỗ trợ, không mặc nhiên thay thế chứng từ gốc;
* legal hold và correction không được phá chuỗi bằng chứng.

### 14.5 Qualified Invoice System

Với invoice Nhật:

* lưu ảnh/PDF/XML hoặc dữ liệu nguồn theo quy định áp dụng;
* trích xuất registration number, issuer, transaction date, tax rate, tax amount và total;
* kiểm tra arithmetic và tax rounding;
* khi nghiệp vụ yêu cầu, đối chiếu registration information với nguồn NTA phù hợp;
* benchmark các biểu mẫu có nhiều mức thuế, credit note và tài liệu song ngữ.

### 14.6 AI governance tại Nhật

Áp dụng AI Guidelines for Business phiên bản hiện hành như khung quản trị thực hành:

* human-centric và tôn trọng quyền;
* safety, fairness, privacy, security;
* transparency/accountability;
* literacy và governance xuyên vòng đời;
* quản lý vendor, dữ liệu, model và incident.

Tài liệu pháp lý và guideline cần có `status` rõ: luật có hiệu lực, guideline, draft/bill hoặc thay đổi chờ hiệu lực. Không chuyển một dự luật thành control production trước khi xác nhận ngày ban hành/hiệu lực và quy định hướng dẫn.

### 14.7 Contract checklist cho khách hàng doanh nghiệp Nhật

* data ownership;
* use of customer data for training;
* processing/data locations;
* subprocessor list và change notice;
* breach notification SLA;
* deletion/return at termination;
* audit/assurance reports;
* model/version change notice;
* availability/support hours bằng tiếng Nhật nếu yêu cầu;
* exit/export format;
* liability và human-review responsibility;
* accuracy không được trình bày như bảo đảm tuyệt đối nếu hợp đồng không quy định.

---

## 15. So sánh Google, Azure và AWS trong bối cảnh Nhật Bản

### 15.1 Bảng đánh giá định hướng

| Khía cạnh | Google Cloud Document AI | Azure AI Document Intelligence | AWS Textract / lớp AWS khác |
| --- | --- | --- | --- |
| OCR tiếng Nhật | Phải xác nhận theo processor/version và benchmark | Tài liệu chính thức liệt kê tiếng Nhật cho Read/Layout, gồm handwriting ở các phiên bản được nêu | Textract hiện không liệt kê tiếng Nhật |
| Chữ dọc | Không được giả định; benchmark bắt buộc | Benchmark bắt buộc | Textract nêu rõ không hỗ trợ vertical text |
| Data location Nhật | Không có location Nhật trong danh sách Document AI tại thời điểm đối chiếu; single-region châu Á gồm Mumbai/Singapore | Xác nhận chính xác model/API/SKU tại Japan East/West trong procurement | Xác nhận từng dịch vụ; region hạ tầng AWS không đồng nghĩa mọi AI service/model đều có cùng coverage |
| Classify/split | Mạnh, processor-centric | Custom classifier/page ranges | Thường cần orchestration riêng hoặc dịch vụ/model bổ sung |
| Custom extraction | Custom và generative extraction | Custom models/composed/routing | Queries/adapters; nhưng OCR source limitation vẫn là hard constraint |
| Human review tích hợp | HITL đã deprecated; phải tự xây | Nên tự xây service độc lập | Nên tự xây service độc lập |
| Evidence/output | Rich anchors/polygons | Spans/polygons/fields | Block graph/geometry |
| Japan suitability | Có thể phù hợp kỹ thuật nhưng cross-border gate rất quan trọng | Giả thuyết mạnh cho benchmark tiếng Nhật; vẫn cần region/model/cost test | Không phù hợp làm primary OCR tiếng Nhật với giới hạn Textract hiện tại; vẫn phù hợp làm cloud/orchestration |

### 15.2 Cách diễn giải đúng

Bảng trên không tuyên bố “winner”. Mỗi kết luận phải được chuyển thành testable hypothesis.

**Ví dụ:**

* “Azure hỗ trợ tiếng Nhật” không đồng nghĩa field accuracy đạt SLA cho invoice của khách hàng.
* “Google có custom splitter” không giải quyết được yêu cầu xử lý trong Nhật Bản nếu policy cấm cross-border.
* “Hệ thống đang chạy trên AWS” không có nghĩa Textract là OCR phù hợp cho tiếng Nhật.

### 15.3 Khuyến nghị shortlist

Shortlist benchmark nên gồm:

1. Azure AI Document Intelligence;
2. Google Document AI nếu cross-border có thể được xem xét;
3. một hoặc nhiều OCR/IDP chuyên thị trường Nhật Bản;
4. AWS-native orchestration + OCR engine khác nếu hạ tầng chiến lược là AWS;
5. phương án self-host/container khi data-location hoặc latency bắt buộc.

### 15.4 Tiêu chí procurement

Yêu cầu vendor cung cấp bằng văn bản:

* model/API/version cụ thể;
* region processing, storage, logs, backup và support access;
* subprocessor;
* data retention;
* training-use policy;
* SLA và quota;
* deprecation/change policy;
* Japanese language/layout limitations;
* export và deletion;
* security attestations;
* pricing assumptions.

---

## 16. Build, buy hay hybrid

### 16.1 Nên mua/managed

* OCR/layout/handwriting đã được benchmark;
* model inference/hosting;
* autoscaling;
* prebuilt extraction phù hợp;
* foundation model access khi cần.

### 16.2 Nên tự kiểm soát

* intake và security boundary;
* immutable storage;
* canonical schema;
* orchestration và idempotency;
* normalization Nhật Bản;
* business validation;
* risk policy;
* human review;
* audit;
* dataset governance;
* observability/FinOps;
* vendor abstraction và exit plan.

### 16.3 Khi cân nhắc self-host/container

* policy yêu cầu xử lý trong Nhật hoặc on-prem;
* volume ổn định đủ lớn;
* latency/availability cần kiểm soát;
* có năng lực vận hành model và security patching;
* managed service không hỗ trợ layout/ngôn ngữ cần thiết.

Self-host không tự động an toàn hơn; doanh nghiệp phải chịu trách nhiệm patch, capacity, monitoring và model lifecycle.

---

## 17. Operating model và phân quyền

### 17.1 Vai trò

| Vai trò | Trách nhiệm chính |
| --- | --- |
| Product owner | KPI, scope, automation policy, acceptance criteria |
| Document AI platform | Pipeline, API, storage, orchestration, observability |
| ML/AI | Dataset, benchmark, calibration, drift, release |
| Security | Threat model, IAM, network, incident response |
| Privacy/Legal | APPI, cross-border, contracts, retention |
| Tax/Records | Electronic Bookkeeping Act, invoice/document retention |
| Operations | Review, reason code, template discovery, SLA |
| Data steward | Canonical schema, master data, quality |
| SRE/FinOps | SLO, capacity, DR, unit cost |

### 17.2 Separation of duties

Không để một người có thể đồng thời:

* sửa ground truth;
* phê duyệt dataset;
* train/configure model;
* deploy production;
* phê duyệt output nghiệp vụ;
* xóa audit/raw data.

### 17.3 Decision ownership

* Model team đề xuất threshold.
* Product/Risk phê duyệt automation policy.
* Security/Privacy có quyền chặn release khi hard gate vi phạm.
* Operations có quyền dừng auto-pass khi phát hiện silent degradation.

---

## 18. Lộ trình triển khai và stage gate

### 18.1 Giai đoạn 0 — Discovery và legal/data mapping

* chọn 2–3 document types có volume và ROI rõ;
* map data fields, purpose, retention và flow;
* xác định tài liệu chứa personal data/My Number;
* xác định yêu cầu Electronic Bookkeeping Act;
* thu thập corpus đại diện tại Nhật;
* đo baseline thủ công;
* đặt error budget và review capacity.

**Exit gate:** scope, legal assumptions, ground truth policy và hard gates được phê duyệt.

### 18.2 Giai đoạn 1 — Benchmark

Chạy cùng frozen test set trên shortlist.

Đánh giá:

* accuracy theo field/slice;
* vertical/horizontal/bilingual;
* OOD và abstention;
* evidence quality;
* latency/throughput;
* cost;
* region/data flow;
* security/integration;
* model lifecycle/deprecation;
* reviewer productivity.

**Exit gate:** ít nhất một phương án vượt mọi hard gate và đạt error budget.

### 18.3 Giai đoạn 2 — MVP kiểm soát

* secure intake;
* raw store;
* classifier/extractor;
* canonical JSON;
* validation;
* review UI;
* một downstream integration;
* audit và dashboard;
* auto-pass tắt hoặc giới hạn hẹp.

**Exit gate:** end-to-end traceability, incident procedure và reconciliation hoạt động.

### 18.4 Giai đoạn 3 — Production hardening

* private connectivity;
* IAM/KMS;
* queue/DLQ/replay;
* idempotency;
* SLO/alert;
* capacity/load test;
* DR test;
* canary/rollback;
* prompt-injection/adversarial test;
* contract/security/privacy sign-off.

**Exit gate:** production readiness review được phê duyệt.

### 18.5 Giai đoạn 4 — Progressive automation

Tăng auto-pass theo document type/field/tenant sau khi:

* calibration ổn định;
* false accept dưới budget;
* sampling review không phát hiện degradation;
* downstream correction/reversal đã kiểm thử.

### 18.6 Giai đoạn 5 — Scale và continuous improvement

* thêm document type;
* active learning có governance;
* drift/OOD monitoring;
* generative extraction có guardrail;
* cost optimization;
* vendor/model migration drills;
* quarterly legal/vendor review.

---

## 19. Anti-pattern cần tránh

1. Chọn OCR không hỗ trợ tiếng Nhật nhưng vẫn triển khai vì hạ tầng cùng cloud.
2. Không benchmark chữ dọc, dấu/con dấu, fax và full-width/half-width.
3. Giả định region của cloud đồng nghĩa region của AI service.
4. Chỉ lưu text, làm mất layout/evidence.
5. Ghi đè raw value bằng normalized value.
6. Một prompt LLM xử lý từ OCR đến quyết định nghiệp vụ.
7. Cho model quyền ghi trực tiếp ERP/CRM.
8. Không có `unknown/OOD`.
9. Dùng một threshold cho mọi field.
10. Tin confidence chưa calibration như xác suất đúng.
11. Không giữ file gốc/hash/version.
12. Downstream phụ thuộc JSON vendor.
13. Trộn extraction và business decision.
14. Đưa reviewer correction thẳng vào training.
15. Không có frozen regression test.
16. Đánh giá bằng accuracy trung bình.
17. Auto-pass 100% từ đầu.
18. Không theo dõi cost theo stage/document type.
19. Không có reprocess/reconciliation.
20. Không theo dõi deprecation và model change.
21. Dùng HITL vendor đã deprecated như dependency kiến trúc.
22. Xem nội dung tài liệu như instruction cho LLM/tool.
23. Không quản lý subprocessor và onward transfer.
24. Chỉ lưu OCR output cho chứng từ điện tử, bỏ bản điện tử gốc.

---

## 20. Kiến trúc khuyến nghị cuối cùng

Đối với phần lớn doanh nghiệp Nhật Bản, thiết kế cân bằng nhất là:

* **Japan-first benchmark** trước khi chọn engine;
* **hybrid vendor-neutral architecture**;
* **event-driven asynchronous pipeline**;
* **secure document boundary** trước parser/model;
* **immutable raw storage** và legal-hold support;
* **classifier/splitter trước extractor**;
* **canonical schema độc lập vendor**;
* **raw/normalized/derived separation**;
* **business validation tách khỏi AI**;
* **calibrated confidence + field-level risk routing**;
* **human review service độc lập**;
* **policy enforcement trước downstream action**;
* **versioning đầy đủ**;
* **APPI/cross-border/subprocessor governance**;
* **Electronic Bookkeeping Act-aware retention**;
* **prompt-injection và malicious-document controls**;
* **SLO, DR, FinOps, canary, rollback và drift monitoring**;
* **exit plan để thay model/provider**.

```text
Enterprise Document AI for Japan
=
Secure Intake & Immutable Evidence
+ Japanese OCR/Layout
+ Classification/Splitting
+ Extraction
+ Reversible Normalization
+ Business Validation
+ Calibrated Risk Routing
+ Human Review
+ Controlled Integration
+ APPI/Records Governance
+ Continuous Evaluation
```

### 20.1 Khuyến nghị quyết định ngắn gọn

1. Không dùng Amazon Textract làm primary OCR cho tài liệu tiếng Nhật trong điều kiện hỗ trợ hiện tại.
2. Đưa Azure và ít nhất một vendor Nhật vào benchmark chính.
3. Chỉ đưa Google Document AI vào shortlist nếu doanh nghiệp chấp nhận đánh giá luồng xử lý ngoài Nhật Bản; không phụ thuộc HITL của Google.
4. Tự xây canonical schema, review, policy, audit và orchestration dù engine OCR thuộc vendor nào.
5. Chỉ bật auto-pass sau benchmark, calibration và sampling production.

---

## 21. Phụ lục A — Vấn đề của v2 và cách sửa trong v3

| Vấn đề ở v2 | Rủi ro | Cải thiện trong v3 |
| --- | --- | --- |
| Phạm vi pháp lý Việt Nam, không phù hợp yêu cầu mới | Kiến trúc/compliance sai jurisdiction | Chuyển toàn bộ sang Nhật Bản, APPI, My Number, Electronic Bookkeeping Act, Qualified Invoice |
| Thiếu Japan-specific language gate | Có thể chọn engine không đọc được tiếng Nhật/chữ dọc | Thêm hard gate và corpus benchmark tiếng Nhật |
| Không nêu giới hạn ngôn ngữ của Textract | Dễ chọn sai primary OCR trên AWS | Nêu rõ Textract không hỗ trợ tiếng Nhật và vertical text theo tài liệu hiện hành |
| Không nêu Google Document AI thiếu location Nhật | Bỏ sót cross-border/privacy risk | Thêm data-location gate và đánh giá Google theo location thực tế |
| Nói Google có HITL như capability đang dùng được | Phụ thuộc tính năng đã deprecated | Sửa thành review service độc lập; ghi rõ HITL Google deprecated |
| Bảng vendor mang tính kết luận | Procurement bias, bỏ qua benchmark | Chuyển thành hypothesis + hard gate + scorecard |
| Confidence chỉ có threshold minh họa | False accept do confidence không calibration | Thêm calibration, reliability, error budget và materiality |
| Security chỉ là danh sách cloud control | Không xử lý file độc hại/prompt injection | Thêm security boundary, sandbox/CDR, tool isolation, egress control |
| Data contract thiếu thông tin jurisdiction | Khó audit cross-border/retention | Bổ sung jurisdiction, purpose, location, classification, legal hold, OOD và normalization provenance |
| Thiếu NFR/DR/capacity | MVP khó vận hành production | Thêm SLO template, RTO/RPO, DR test và reconciliation |
| Thiếu cost model end-to-end | Chỉ thấy API cost, bỏ review/egress/reprocess | Thêm unit economics và FinOps guardrail |
| Correction được mô tả chủ yếu như feedback | Poisoning/ground-truth error | Thêm quarantine, adjudication và dataset approval |
| Không phân biệt tình trạng luật/guideline/bill | Có thể áp dụng sai thời điểm | Yêu cầu legal status và effective-date tracking |
| Chu kỳ rà soát 6 tháng | Quá chậm với model/API deprecation | Rút còn 3 tháng hoặc event-driven review |
| Chủ sở hữu tài liệu để trống | Không rõ accountability | Giữ placeholder nhưng yêu cầu role owner và approver rõ ràng |

---

## 22. Phụ lục B — Scorecard benchmark đề xuất

### 22.1 Hard gate — pass/fail

| Mã | Tiêu chí | Pass condition |
| --- | --- | --- |
| H1 | Japanese printed OCR | Đạt target theo frozen test set |
| H2 | Vertical text nếu có trong use case | Đạt target hoặc có approved fallback |
| H3 | Data location | Được Privacy/Legal/Security phê duyệt |
| H4 | Evidence/audit | Có page/span/polygon và version traceability |
| H5 | Security | Vượt threat-model review |
| H6 | False accept | Không vượt budget ở field critical |
| H7 | Reprocess/rollback | Đã test thành công |
| H8 | Contract/subprocessor | Được procurement/legal chấp thuận |

### 22.2 Weighted score sau hard gate

| Nhóm | Trọng số gợi ý |
| --- | ---: |
| Field accuracy và OOD | 30% |
| Japanese layout/script coverage | 15% |
| Security/privacy/data location | 15% |
| Integration và evidence | 10% |
| Operations, versioning, deprecation | 10% |
| Latency/throughput/reliability | 8% |
| Cost end-to-end | 7% |
| Reviewer productivity | 5% |

Trọng số phải được điều chỉnh theo use case. Với HR/My Number hoặc tài chính rủi ro cao, privacy/security và false accept có thể được nâng thành hard gate nghiêm ngặt hơn thay vì chỉ là điểm số.

### 22.3 Mẫu acceptance criteria

```text
Document type: JP qualified invoice
Critical fields: issuer, registration number, invoice number,
transaction date, tax rate, tax amount, total amount

Pass when:
- all hard gates pass;
- critical-field normalized accuracy reaches approved target;
- false accept is below approved budget;
- arithmetic reconciliation works on all supported patterns;
- vertical/bilingual/fax slices meet their slice targets;
- P95 latency and cost/document meet NFR;
- reviewer AHT improves against manual baseline;
- full traceability from downstream value to original evidence is demonstrated.
```

---

## 23. Tài liệu tham khảo

Các nguồn dưới đây ưu tiên tài liệu chính thức và cần được rà soát lại tại mỗi chu kỳ cập nhật.

### Nhật Bản — privacy, AI và chứng từ

1. Personal Information Protection Commission, hướng dẫn chuyển personal data cho bên thứ ba ở nước ngoài: <https://www.ppc.go.jp/personalinfo/legal/guidelines_offshore/>
2. Personal Information Protection Commission, hệ thống hướng dẫn APPI: <https://www.ppc.go.jp/personalinfo/legal/>
3. Personal Information Protection Commission, My Number/Special Personal Information guidance: <https://www.ppc.go.jp/legal/policy/my_number_guideline_jigyosha>
4. METI, AI Guidelines for Business, phiên bản 1.2: <https://www.meti.go.jp/shingikai/mono_info_service/ai_shakai_jisso/20260331_report.html>
5. National Tax Agency, Electronic Bookkeeping Act portal: <https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/tokusetsu/index.htm>
6. National Tax Agency, Qualified Invoice Issuer Publication Site: <https://www.invoice-kohyo.nta.go.jp/>
7. IPA, AI security: <https://www.ipa.go.jp/digital/ai/security/index.html>
8. AISI/IPA, AI safety evaluation guidance: <https://www.ipa.go.jp/pressrelease/2024/press20240918-2.html>

### Google Cloud

9. Document AI regional and multi-regional support: <https://docs.cloud.google.com/document-ai/docs/regions>
10. Document AI deprecations: <https://docs.cloud.google.com/document-ai/docs/deprecation>
11. Document AI release notes: <https://docs.cloud.google.com/document-ai/docs/release-notes>
12. Document AI security and compliance: <https://docs.cloud.google.com/document-ai/docs/security>

### Microsoft Azure

13. Document Intelligence OCR language support: <https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/language-support/ocr?view=doc-intel-4.0.0>
14. Document Intelligence model overview: <https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/model-overview?view=doc-intel-4.0.0>
15. Document Intelligence updates: <https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/whats-new?view=doc-intel-4.0.0>
16. Document Intelligence quotas and limits: <https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0>

### AWS

17. Amazon Textract quotas and fixed limits: <https://docs.aws.amazon.com/textract/latest/dg/limits-document.html>
18. Amazon Textract best practices: <https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html>
19. Amazon Textract overview: <https://docs.aws.amazon.com/textract/latest/dg/what-is.html>

---

**Kết thúc tài liệu — phiên bản 3.0**
