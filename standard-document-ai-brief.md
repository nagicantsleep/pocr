# Brief tổng thể về hệ thống Document AI cấp doanh nghiệp

**Phạm vi:** kiến trúc, mô hình AI, luồng xử lý, dữ liệu, human-in-the-loop, bảo mật, vận hành, MLOps/DocOps và cách lựa chọn Google Cloud Document AI, Azure AI Document Intelligence hoặc AWS Textract/Bedrock Data Automation.

**Thời điểm đối chiếu tài liệu:** 17/07/2026.

---

## 1. Executive summary

Một hệ thống **Document AI doanh nghiệp** là nền tảng biến tài liệu không cấu trúc hoặc bán cấu trúc như PDF, ảnh scan, hồ sơ vay, hóa đơn, hợp đồng, biểu mẫu, email đính kèm thành:

* Dữ liệu có cấu trúc.
* Nội dung có thể tìm kiếm.
* Các sự kiện hoặc quyết định nghiệp vụ.
* Hồ sơ có thể kiểm toán và truy vết.

Nó **không chỉ là OCR**. OCR chỉ đọc chữ, trong khi Document AI còn phải:

1. Tiếp nhận và bảo quản tài liệu gốc.
2. Kiểm tra chất lượng, định dạng và bảo mật.
3. Phân loại loại tài liệu.
4. Tách một bộ PDF thành các tài liệu logic.
5. Nhận diện text, bảng, checkbox, chữ viết tay, bố cục.
6. Trích xuất trường dữ liệu và quan hệ.
7. Chuẩn hóa ngày, tiền, địa chỉ, mã số.
8. Kiểm tra quy tắc nghiệp vụ và đối chiếu hệ thống khác.
9. Đẩy trường hợp không chắc chắn cho con người.
10. Xuất kết quả sang ERP, CRM, BPM, data platform hoặc search/RAG.
11. Theo dõi chất lượng, drift, chi phí và phiên bản mô hình.

Google mô tả Document AI theo mô hình các **processor** cho OCR, phân loại, tách và trích xuất; Azure cung cấp Read, Layout, prebuilt, custom extraction, classifier và composed model; AWS Textract cung cấp các API nhận diện text, biểu mẫu, bảng, query, hóa đơn, ID và lending, đồng thời AWS bổ sung Bedrock Data Automation cho pipeline IDP có generative AI. ([Google Cloud][1])

---

# 2. Concept cốt lõi

## 2.1 Document AI giải quyết bài toán gì?

Đầu vào thường có độ biến thiên rất lớn:

* File PDF điện tử và PDF scan.
* Ảnh chụp lệch, mờ, thiếu sáng.
* Nhiều loại tài liệu ghép trong một file.
* Nhiều template cho cùng một loại tài liệu.
* Bảng kéo dài qua nhiều trang.
* Dữ liệu vừa in vừa viết tay.
* Giá trị không xuất hiện trực tiếp mà phải suy luận.
* Ngôn ngữ và ký hiệu khác nhau.

Đầu ra không nên chỉ là text thuần mà là một **Document Object** gồm:

* Text và cấu trúc trang.
* Bounding box hoặc polygon của từng phần tử.
* Loại tài liệu và phạm vi trang.
* Trường dữ liệu thô và giá trị đã chuẩn hóa.
* Bảng, hàng, cột và merged cell.
* Confidence.
* Bằng chứng nguồn.
* Phiên bản mô hình.
* Trạng thái validation và review.

Google Document AI trả về đối tượng `Document` có text, entities, pages, page anchors, vị trí hình học và normalized values; Azure trả về text, lines, words, polygons, tables, fields và confidence; AWS Textract biểu diễn kết quả bằng các `Block` có nội dung, quan hệ, trang và vị trí. ([Google Cloud Documentation][2])

## 2.2 Ba tầng “thông minh”

### Tầng 1: Perception

Nhìn và đọc tài liệu:

* OCR.
* Chữ viết tay.
* Layout.
* Bảng.
* Checkbox.
* Chữ ký.
* Hình, tiêu đề, đoạn, danh sách.

### Tầng 2: Understanding

Hiểu tài liệu:

* Đây là hóa đơn hay hợp đồng?
* Trang 1–3 thuộc đơn vay, trang 4 là sao kê?
* “Total payable” là trường nào?
* Dòng nào thuộc sản phẩm nào?
* Ngày nào là ngày phát hành, ngày nào là hạn thanh toán?

### Tầng 3: Decision và action

Áp dụng nghiệp vụ:

* Tổng tiền có khớp chi tiết?
* Mã khách hàng có tồn tại?
* Hợp đồng đã hết hạn chưa?
* Hồ sơ có thiếu tài liệu bắt buộc?
* Tự động ghi nhận hay phải gửi kiểm tra?
* Có dấu hiệu gian lận hoặc trùng lặp không?

Sai lầm phổ biến là gom cả ba tầng vào một prompt LLM dài như sớ Táo quân. Kết quả thì đẹp trong demo, khó kiểm soát trong production.

---

# 3. Kiến trúc tham chiếu

```text
Nguồn tài liệu
Email / Portal / API / SFTP / Scanner / Mobile / DMS
                         │
                         ▼
┌───────────────────────────────────────────────┐
│ 1. Intake Gateway                            │
│ Auth, upload, checksum, malware scan, quota  │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ 2. Immutable Raw Document Store              │
│ File gốc, metadata, retention, encryption    │
└───────────────────────┬───────────────────────┘
                        ▼ event/job
┌───────────────────────────────────────────────┐
│ 3. Orchestration & Queue                      │
│ Retry, idempotency, timeout, priority, DLQ   │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ 4. Pre-processing                             │
│ Validate, rotate, deskew, enhance, page QC   │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ 5. Classify & Split                           │
│ Loại tài liệu, phạm vi trang, unknown class  │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ 6. OCR / Layout / Extraction                  │
│ Prebuilt / custom / query / generative model │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ 7. Normalize & Enrich                         │
│ Date, currency, address, IDs, master data    │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ 8. Validation & Risk Engine                   │
│ Rules, cross-check, anomaly, confidence      │
└───────────────┬───────────────────┬───────────┘
                │ auto-pass         │ exception
                ▼                   ▼
       Downstream systems     Human Review Queue
                │                   │ corrections
                └─────────────┬─────┘
                              ▼
                   Feedback / Training Data
```

Kiến trúc nên là **event-driven và bất đồng bộ** cho tải lớn, vì pipeline có nhiều bước lâu dài, nhiều retry và thường xử lý PDF nhiều trang. Chế độ đồng bộ chỉ nên dùng cho tài liệu nhỏ hoặc luồng người dùng cần phản hồi ngay. Google hỗ trợ online processing cho một tài liệu và batch processing ghi kết quả ra Cloud Storage; AWS phân biệt synchronous cho trường hợp nhạy latency và asynchronous cho tài liệu nhiều trang; Azure có batch document analysis bên cạnh API phân tích thông thường. ([Google Cloud Documentation][3])

---

# 4. Thiết kế từng thành phần

## 4.1 Intake Gateway

Trách nhiệm:

* Xác thực người gửi hoặc ứng dụng.
* Kiểm tra MIME type, kích thước, số trang.
* Tính hash để phát hiện trùng lặp.
* Quét malware.
* Gán `document_id`, `tenant_id`, `correlation_id`.
* Xác định độ ưu tiên và SLA.
* Ghi metadata trước khi bắt đầu xử lý.

**Nguyên tắc:** upload thành công không đồng nghĩa với xử lý thành công. API upload nên trả về `job_id`, sau đó client nhận kết quả bằng polling, webhook hoặc event.

## 4.2 Raw Document Store

Tài liệu gốc cần được lưu bất biến để:

* Tái xử lý khi đổi mô hình.
* Điều tra lỗi.
* Chứng minh nguồn dữ liệu.
* Kiểm toán.
* Đối chiếu kết quả AI với bản gốc.

Nên tách:

* `raw/`: file nguyên bản.
* `derived/`: ảnh trang, thumbnail, PDF đã sửa hướng.
* `results/`: JSON kết quả.
* `review/`: correction và annotation.
* `dataset/`: bộ train/test được phê duyệt.

Không ghi đè file gốc. Con người đã phát minh ra audit rồi lại thích ghi đè dữ liệu, một truyền thống công nghệ rất khó hiểu.

## 4.3 Orchestrator và queue

Orchestrator quản lý:

* State machine.
* Retry có backoff.
* Timeout.
* Dead-letter queue.
* Giới hạn concurrency.
* Quota của dịch vụ AI.
* Chia batch.
* Callback bất đồng bộ.
* Compensation khi một bước thất bại.
* Reprocessing có kiểm soát.

Mỗi bước phải **idempotent**. Một job chạy lại không được tạo hai hóa đơn hoặc hai hồ sơ khách hàng.

AWS đưa ra kiến trúc IDP tham chiếu theo hướng tài liệu vào S3, phát sự kiện, tạo tracking job và điều phối xử lý; các hướng dẫn AWS cũng nhấn mạnh kiến trúc serverless, event-driven và queue để điều tiết concurrency. ([AWS Documentation][4])

## 4.4 Pre-processing

Không nên “chữa ảnh” một cách mù quáng. Pre-processing quá mạnh có thể làm mất dấu chấm, ký tự nhỏ hoặc đường bảng.

Các bước thường dùng:

* Auto-rotate.
* Deskew.
* Crop biên.
* Phát hiện trang trắng.
* Kiểm tra độ phân giải.
* Phát hiện blur, glare, shadow.
* Chuyển đổi format.
* Tách PDF quá lớn.
* Loại bỏ mật khẩu hoặc chuyển sang hàng đợi xử lý đặc biệt.
* Đánh giá chất lượng trang.

Lưu cả bản gốc và bản đã xử lý, cùng tham số biến đổi.

## 4.5 Classification và splitting

### Classification

Xác định tài liệu là:

* Invoice.
* Purchase order.
* Contract.
* Bank statement.
* Identity document.
* Payslip.
* Hồ sơ khác.
* Unknown/other.

Luôn có lớp `unknown` hoặc quy tắc từ chối. Ép mọi tài liệu vào một lớp đã biết khiến hệ thống tự tin nói sai, một phẩm chất mà AI học từ con người khá nhanh.

### Splitting

Một file 80 trang có thể chứa:

* Đơn đăng ký.
* Chứng minh thư.
* Sao kê ngân hàng.
* Hợp đồng.
* Tài liệu bổ sung.

Splitter phải trả về:

* Loại tài liệu.
* Trang bắt đầu và kết thúc.
* Confidence.
* Quan hệ với bộ hồ sơ cha.

Google có custom splitter cho composite document; Azure classifier có thể nhận diện nhiều tài liệu hoặc nhiều instance trong cùng một file và trả về page range; Azure yêu cầu bật `splitMode=auto` nếu muốn tự động tách ở API v4. ([Google Cloud][1])

---

# 5. Các loại mô hình trong hệ thống

## 5.1 OCR và layout model

Dùng để lấy:

* Text.
* Word/line/paragraph.
* Reading order.
* Bounding polygon.
* Table.
* Selection mark.
* Heading, footer, list.
* Kiểu chữ viết tay.

Đây là nền tảng chung, thường nên mua dưới dạng managed service thay vì tự train OCR từ đầu.

## 5.2 Prebuilt extractor

Mô hình được nhà cung cấp huấn luyện sẵn cho:

* Invoice.
* Receipt.
* ID.
* Tax form.
* Lending document.
* Business card.

Phù hợp khi schema của nhà cung cấp gần với schema nghiệp vụ của doanh nghiệp.

Ưu điểm:

* Triển khai nhanh.
* Ít dữ liệu huấn luyện.
* Vendor duy trì mô hình.

Nhược điểm:

* Schema cứng hơn.
* Khó xử lý trường đặc thù.
* Chất lượng có thể khác nhau theo quốc gia, ngôn ngữ và template.

## 5.3 Custom template model

Phù hợp với tài liệu có bố cục tương đối cố định:

* Biểu mẫu nội bộ.
* Form cơ quan.
* Phiếu có vị trí trường ổn định.

Nhanh và dễ huấn luyện, nhưng suy giảm khi template biến đổi mạnh.

## 5.4 Custom neural hoặc semantic extractor

Phù hợp khi:

* Cùng loại tài liệu nhưng nhiều layout.
* Tên trường thay đổi.
* Vị trí trường không cố định.
* Cần hiểu quan hệ ngữ nghĩa.

Azure custom model hỗ trợ extraction cho tài liệu đặc thù và có thể compose nhiều custom model; Google có custom extractor; AWS Textract Custom Queries dùng adapter để điều chỉnh output của mô hình query theo tài liệu doanh nghiệp. ([Microsoft Learn][5])

## 5.5 Generative extractor

LLM hoặc multimodal foundation model nhận schema và mô tả trường để trích xuất.

Phù hợp với:

* Tài liệu dài và đa dạng.
* Trường ngữ nghĩa phức tạp.
* Zero-shot hoặc few-shot.
* Giá trị cần suy luận.
* Tóm tắt và hỏi đáp.

Google Custom Extractor hỗ trợ zero-shot, few-shot và fine-tuning; tài liệu Google đề xuất khoảng 5–10 tài liệu cho few-shot và 10–50+ cho fine-tuning, tùy độ phức tạp. Đây là mức khởi động kỹ thuật, không phải lời hứa thần kỳ về production. ([Google Cloud Documentation][6])

Generative model cần thêm guardrail:

* JSON schema bắt buộc.
* Data type validation.
* Evidence hoặc source span.
* Không cho phép tự bịa giá trị thiếu.
* Tách rõ `extracted`, `derived` và `not_found`.
* Temperature thấp.
* Version prompt và model.
* Kiểm tra bằng rule hoặc mô hình thứ hai ở trường rủi ro cao.

## 5.6 Derived-field model

Một số giá trị không tồn tại nguyên văn:

* Xác định loại khách hàng.
* Tính thời hạn hợp đồng.
* Suy ra quốc gia từ địa chỉ.
* Nhận định hồ sơ đầy đủ hay thiếu.
* Phân loại điều khoản rủi ro.

Các trường này phải đánh dấu là **derived**, không được giả vờ rằng chúng được OCR từ một vùng trên tài liệu. Google cũng phân biệt entity được trích trực tiếp với entity được suy ra, trong đó trường suy ra không có text anchor hoặc page anchor. ([Google Cloud Documentation][7])

---

# 6. Thiết kế data contract

Không để các hệ thống downstream phụ thuộc trực tiếp vào JSON riêng của Google, Azure hoặc AWS. Hãy tạo một schema trung gian ổn định.

Ví dụ rút gọn:

```json
{
  "documentId": "doc_123",
  "caseId": "case_456",
  "source": {
    "channel": "email",
    "fileName": "invoice.pdf",
    "sha256": "...",
    "receivedAt": "2026-07-17T10:00:00Z"
  },
  "document": {
    "type": "invoice",
    "typeConfidence": 0.97,
    "pageRange": [1, 3],
    "language": "vi"
  },
  "fields": {
    "invoiceNumber": {
      "rawValue": "HD-00125",
      "normalizedValue": "HD-00125",
      "dataType": "string",
      "confidence": 0.96,
      "evidence": [
        {
          "page": 1,
          "polygon": [[0.1, 0.2], [0.3, 0.2], [0.3, 0.25], [0.1, 0.25]],
          "text": "HD-00125"
        }
      ]
    }
  },
  "validation": {
    "status": "warning",
    "rules": [
      {
        "rule": "TOTAL_EQUALS_LINE_SUM",
        "status": "failed"
      }
    ]
  },
  "processing": {
    "pipelineVersion": "3.2.0",
    "modelProvider": "azure",
    "modelId": "invoice-neural-v7",
    "modelVersion": "7",
    "processedAt": "2026-07-17T10:01:18Z"
  },
  "review": {
    "required": true,
    "reasonCodes": ["TOTAL_MISMATCH"]
  }
}
```

Schema nên lưu đồng thời:

* Raw value.
* Normalized value.
* Confidence.
* Evidence.
* Model và pipeline version.
* Validation.
* Correction của reviewer.
* Thời điểm và danh tính người sửa.

---

# 7. Confidence và cơ chế quyết định

## 7.1 Không dùng một threshold toàn hệ thống

Không nên quy định kiểu:

> Confidence ≥ 0.8 thì auto-pass.

Threshold cần khác nhau theo:

* Loại tài liệu.
* Trường dữ liệu.
* Giá trị tiền.
* Mức độ ảnh hưởng nghiệp vụ.
* Chất lượng ảnh.
* Khách hàng hoặc quốc gia.
* Model version.
* Kết quả business validation.

Ví dụ:

| Trường             |              Ngưỡng gợi ý | Hành động                              |
| ------------------ | ------------------------: | -------------------------------------- |
| Tên nhà cung cấp   |                      0,85 | Có thể auto-pass nếu vendor tồn tại    |
| Số hóa đơn         |                      0,95 | Review nếu trùng hoặc không đúng regex |
| Tổng tiền          |                      0,98 | Phải đối chiếu tổng dòng               |
| Mã số thuế         |                      0,99 | Kiểm tra checksum/master data          |
| Điều khoản pháp lý | Không chỉ dùng confidence | Review theo mức rủi ro                 |

Confidence của mô hình nên được xem là **một tín hiệu**, không phải bằng chứng tuyệt đối rằng trường đúng. Azure cũng khuyến nghị xem xét tập hợp confidence của các trường và đánh giá chúng trên dữ liệu thực tế của ứng dụng. ([Microsoft Learn][8])

## 7.2 Risk score tổng hợp

Có thể xây:

```text
reviewRisk =
    w1 × modelUncertainty
  + w2 × poorImageQuality
  + w3 × businessRuleFailure
  + w4 × outOfDistributionScore
  + w5 × financialOrLegalMateriality
  + w6 × historicalErrorRate
```

Sau đó chia:

* **Low risk:** straight-through processing.
* **Medium risk:** kiểm tra một số trường.
* **High risk:** full review hoặc từ chối tự động.
* **Unknown:** chuyển manual triage.

---

# 8. Human-in-the-loop

Human review không phải thất bại của AI. Nó là thành phần kiểm soát rủi ro, chỉ là ít hào nhoáng hơn màn hình chatbot nên thường bị quên.

## 8.1 Loại review

### Full-document review

Reviewer xem toàn bộ kết quả.

Dùng khi:

* Tài liệu mới.
* Model mới.
* Nghiệp vụ rủi ro cao.
* Hồ sơ bị nghi gian lận.

### Field-level review

Chỉ kiểm tra trường có confidence thấp hoặc rule fail.

Đây thường là mô hình hiệu quả nhất về chi phí.

### Sampling review

Kiểm tra ngẫu nhiên một phần auto-pass để phát hiện silent degradation.

### Dual control

Hai người phê duyệt độc lập cho trường pháp lý hoặc tài chính quan trọng.

## 8.2 Review UI cần có

* Viewer tài liệu gốc.
* Highlight vùng nguồn.
* Giá trị AI và confidence.
* Validation warnings.
* Phím tắt nhập liệu.
* History.
* Reason code cho correction.
* SLA và priority.
* Chống reviewer nhìn thấy thông tin không cần thiết.
* Audit log đầy đủ.

Google API có cơ chế human review với các processor hỗ trợ HITL; tuy nhiên, kiến trúc doanh nghiệp không nên phụ thuộc vào việc vendor có sẵn toàn bộ review workflow. Review service nên là một module riêng, có thể kết nối bất kỳ engine Document AI nào. ([Google Cloud Documentation][3])

---

# 9. Model lifecycle và DocOps

## 9.1 Dataset

Tối thiểu cần tách:

* Training.
* Validation.
* Test.
* Shadow production.
* Regression suite.
* Hard cases.
* Out-of-distribution documents.

Test set phải bất biến trong từng chu kỳ đánh giá. AWS cũng yêu cầu đánh giá adapter trên tập test mà mô hình chưa thấy và cung cấp precision, recall, F1 dựa trên ground truth. ([AWS Documentation][9])

## 9.2 Versioning

Mỗi kết quả phải ghi:

* Processor/model ID.
* Model version.
* API version.
* Prompt version.
* Schema version.
* Pipeline version.
* Rule-set version.
* Pre-processing version.

Không lưu version thì sáu tháng sau không ai giải thích được tại sao cùng một PDF cho ra hai kết quả khác nhau. Lúc đó người ta sẽ họp, vì họp là nghi thức truyền thống khi metadata bị bỏ quên.

## 9.3 Quy trình release

```text
Train
  → Offline evaluation
  → Regression test
  → Security and privacy review
  → Shadow deployment
  → Canary 5–10%
  → Compare old/new
  → Progressive rollout
  → Full production
  → Monitor
  → Rollback if needed
```

Không overwrite production model trước khi đánh giá. Azure hỗ trợ incremental classifier và overwrite, nhưng tài liệu Microsoft cũng cảnh báo overwrite làm mất khả năng so sánh và không thể khôi phục model cũ. AWS adapter hỗ trợ nhiều version và quy trình lặp train, đánh giá, bổ sung dữ liệu rồi tạo version cải tiến. ([Microsoft Learn][10])

## 9.4 Drift

Theo dõi:

* Tỷ lệ loại tài liệu mới.
* Distribution confidence.
* Image quality.
* Tỷ lệ trường rỗng.
* Tỷ lệ business rule fail.
* Review correction rate.
* Accuracy theo template/vendor/quốc gia.
* Tỷ lệ unknown.
* Tần suất template mới.
* Chênh lệch giữa model version.

Trigger retraining khi:

* Correction rate vượt ngưỡng.
* Một template mới chiếm tỷ lệ đáng kể.
* Field-level accuracy giảm.
* Business process thay đổi.
* Schema thay đổi.

---

# 10. Observability và KPI

## KPI kỹ thuật

* Documents/pages processed.
* Throughput.
* Queue depth.
* P50/P95/P99 latency.
* API error rate.
* Retry rate.
* Timeout.
* Quota throttling.
* Cost per page/document.
* Storage volume.
* Availability.

AWS Textract cung cấp CloudWatch metrics để theo dõi số lần operation thành công, server error và đặt alarm khi metric vượt ngưỡng. ([AWS Documentation][11])

## KPI chất lượng AI

* Classification precision/recall/F1.
* Split boundary accuracy.
* Field precision/recall/F1.
* Character/word error rate cho OCR.
* Table cell accuracy.
* Exact match.
* Normalized value accuracy.
* False accept rate.
* False reject rate.

## KPI nghiệp vụ

* Straight-through processing rate.
* Human review rate.
* Average handling time.
* Cost per accepted document.
* Time-to-decision.
* Rework rate.
* Downstream rejection rate.
* Financial error prevented.
* SLA breach rate.

**KPI quan trọng nhất thường không phải OCR accuracy**, mà là tỷ lệ tài liệu đi hết quy trình mà không tạo lỗi nghiệp vụ.

---

# 11. Security, privacy và compliance

## 11.1 Các control bắt buộc

* Mã hóa khi truyền và khi lưu.
* Customer-managed key khi cần.
* Least-privilege IAM/RBAC.
* Managed identity hoặc workload identity.
* Private endpoint hoặc service perimeter.
* Không nhúng access key trong source code.
* Audit log.
* Retention và deletion policy.
* Data residency.
* PII masking.
* Tenant isolation.
* DLP và secret scanning.
* Backup metadata, model config và dataset.
* Tách quyền label, train, deploy và review.
* Không dùng production document tùy tiện cho training.

Google Document AI có tài liệu security/compliance riêng và có thể được đặt trong VPC Service Controls để giảm nguy cơ data exfiltration. Azure hỗ trợ managed identity, RBAC, private endpoint, storage firewall và customer-managed keys. AWS Textract hỗ trợ encryption at rest/in transit và interface VPC endpoint qua AWS PrivateLink. ([Google Cloud Documentation][12])

## 11.2 Retention

Cần phân biệt:

* Retention của file gốc trong storage của doanh nghiệp.
* Retention tạm thời của API provider.
* Retention của training data.
* Retention của model artifact.
* Retention của review screenshots và audit records.

Azure cho biết dữ liệu và kết quả phân tích được lưu tạm thời trong cùng region và mặc định xóa sau 24 giờ, với API v4 có thể yêu cầu xóa kết quả sớm hơn. Đây là chi tiết cần đưa vào DPIA và thiết kế retention, thay vì giả định “gọi API xong là dữ liệu biến mất trong không khí”. ([Microsoft Learn][13])

---

# 12. So sánh Google, Azure và AWS

| Khía cạnh           | Google Cloud Document AI                                                           | Azure AI Document Intelligence                                                               | AWS Textract / Bedrock Data Automation                                            |
| ------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Triết lý chính      | Processor-centric                                                                  | Model-centric                                                                                | API building blocks và event-driven services                                      |
| OCR/layout          | Enterprise Document OCR, Layout Parser                                             | Read, Layout                                                                                 | DetectDocumentText, AnalyzeDocument Layout                                        |
| Classification      | Custom classifier                                                                  | Custom classifier                                                                            | Thường ghép Textract với model/service phân loại; lending có routing chuyên biệt  |
| Splitting           | Custom splitter                                                                    | Classifier với page ranges và split mode                                                     | Tự xây orchestration hoặc dùng workflow chuyên biệt                               |
| Prebuilt            | Nhiều specialized processor                                                        | Invoice, receipt, ID, business card và các model prebuilt                                    | Expense, ID, lending                                                              |
| Custom extraction   | Custom extractor truyền thống và generative                                        | Custom template/neural model                                                                 | Queries và Custom Queries adapter                                                 |
| Generative IDP      | Gemini-based extractor/layout                                                      | Kết hợp Document Intelligence với hệ sinh thái Azure AI                                      | Bedrock Data Automation và foundation models                                      |
| Batch               | Có batch API, output vào Cloud Storage                                             | Có batch analysis                                                                            | Async APIs, S3-based processing                                                   |
| Output              | Document JSON giàu anchor và normalized value                                      | AnalyzeResult với spans, polygons, fields                                                    | Block graph với relationships và geometry                                         |
| Private networking  | VPC Service Controls và control của GCP                                            | Private endpoint, VNet, managed identity                                                     | PrivateLink/VPC endpoint                                                          |
| Hybrid/container    | Chủ yếu managed cloud service                                                      | Có Docker container cho một số model/capability                                              | Textract là managed service                                                       |
| Điểm mạnh tương đối | Split/classify/extract rõ ràng, schema evidence tốt, generative extractor tích hợp | Phù hợp hệ sinh thái Microsoft, Office documents, bảo mật Azure, custom model/composed model | Phù hợp AWS serverless/event-driven, API đơn giản, tích hợp S3/SQS/Lambda/Bedrock |
| Lưu ý               | Cần quản lý processor/version và chi phí từng bước                                 | Cần quản lý API version, storage permissions, classifier/extractor routing                   | Nhiều use case cần tự ghép workflow và canonical data model                       |

Các khả năng trong bảng dựa trên tài liệu sản phẩm chính thức của ba nhà cung cấp. ([Google Cloud][1])

## Lựa chọn thực tế

### Chọn Google khi

* Tài liệu composite và splitting là bài toán trọng tâm.
* Muốn processor rõ ràng cho từng công đoạn.
* Muốn thử zero-shot/few-shot generative extraction nhanh.
* Hệ thống dữ liệu đang ở GCP.

### Chọn Azure khi

* Hệ sinh thái hiện tại là Microsoft/Azure.
* Tài liệu Office xuất hiện nhiều.
* Cần private endpoint, managed identity và RBAC đồng bộ với Azure.
* Có yêu cầu chạy một số capability bằng container.
* Muốn compose hoặc route nhiều custom model.

Azure hiện hỗ trợ classifier trên PDF, ảnh và một số định dạng Office; custom classifier yêu cầu ít nhất hai lớp và năm mẫu cho mỗi lớp. Tài liệu Microsoft cũng khuyên thêm dữ liệu khi các lớp gần giống nhau và tạo lớp `other` cho tài liệu ngoài phạm vi. ([Microsoft Learn][5])

### Chọn AWS khi

* Hệ thống đã vận hành theo S3, Lambda, SQS, Step Functions hoặc EventBridge.
* Muốn các API extraction đơn giản và composable.
* Use case nằm gần invoice, ID, lending hoặc query-based extraction.
* Muốn bổ sung pipeline generative IDP bằng Bedrock Data Automation.

AWS Textract hỗ trợ text, form, table, query, expense, ID, lending và Custom Queries adapter; Bedrock Data Automation bổ sung phân loại, extraction, normalization và validation theo output nghiệp vụ. ([AWS Documentation][14])

---

# 13. Build, buy hay hybrid?

Khuyến nghị chung là **hybrid**:

## Mua hoặc dùng managed service cho

* OCR.
* Layout.
* Handwriting.
* Table detection.
* Prebuilt invoice/ID/receipt.
* Foundation model inference.
* Model hosting và autoscaling.

## Tự xây cho

* Intake gateway.
* Canonical document schema.
* Orchestration.
* Business validation.
* Confidence/risk policy.
* Human review UI.
* Integration với hệ thống nghiệp vụ.
* Audit.
* Dataset governance.
* Monitoring chất lượng.
* Cost control.
* Vendor abstraction.

Lợi thế cạnh tranh hiếm khi nằm ở việc doanh nghiệp tự viết OCR. Nó nằm ở cách hiểu nghiệp vụ, xử lý exception và biến kết quả thành hành động đáng tin cậy.

---

# 14. Operating model và tổ chức

## Vai trò

### Product owner

* Chịu KPI nghiệp vụ.
* Xác định phạm vi tài liệu.
* Phê duyệt threshold và mức tự động hóa.

### Document AI platform team

* Pipeline.
* API.
* Storage.
* Orchestration.
* Security.
* Observability.

### ML/AI team

* Dataset.
* Annotation.
* Model selection.
* Evaluation.
* Drift.
* Release.

### Business operations

* Human review.
* Reason codes.
* Phát hiện template mới.
* Xác nhận ground truth.

### Risk, legal và compliance

* PII.
* Retention.
* Data residency.
* Audit.
* Quyết định nào được tự động hóa.

### Data steward

* Schema.
* Master data.
* Data quality.
* Mapping với downstream systems.

## Phân quyền

Không nên để một người có thể đồng thời:

* Sửa ground truth.
* Train model.
* Deploy model.
* Phê duyệt kết quả nghiệp vụ.

Tách quyền để giảm gian lận và lỗi ngoài ý muốn.

---

# 15. Lộ trình triển khai đề xuất

## Giai đoạn 0: Discovery

* Chọn 2–3 loại tài liệu có volume cao.
* Thu thập representative samples.
* Xác định field schema.
* Xác định ground truth.
* Đo baseline xử lý thủ công.
* Xác định trường rủi ro cao.
* Xác định retention và compliance.

## Giai đoạn 1: Benchmark

Chạy cùng một tập tài liệu trên:

* Google.
* Azure.
* AWS.
* Có thể thêm một giải pháp chuyên ngành.

Đánh giá:

* Field-level accuracy.
* Split/classification accuracy.
* Table accuracy.
* Latency.
* Cost.
* Khả năng evidence.
* Security/deployment fit.
* Effort tích hợp.

Không benchmark bằng mười PDF đẹp do phòng marketing chọn. Dùng cả ảnh mờ, template hiếm, tài liệu thiếu trang và file mà nhân viên thật sự ghét xử lý.

## Giai đoạn 2: MVP

* Intake.
* Raw storage.
* Classify/extract.
* Canonical JSON.
* Business validation.
* Review UI.
* Một downstream integration.
* Dashboard cơ bản.

## Giai đoạn 3: Production hardening

* Queue và dead-letter.
* Idempotency.
* Private networking.
* Key management.
* Audit.
* Canary model release.
* SLA/SLO.
* Disaster recovery.
* Cost guardrail.
* Shadow evaluation.

## Giai đoạn 4: Scale

* Thêm loại tài liệu.
* Active learning.
* Field-level review.
* Auto-label.
* Generative extraction.
* Search/RAG.
* Fraud/anomaly detection.
* Multi-region nếu thực sự cần.

---

# 16. Các anti-pattern cần tránh

1. **OCR xong đẩy text vào database**, mất toàn bộ layout và evidence.

2. **Một prompt LLM xử lý tất cả tài liệu**, từ classification đến quyết định giải ngân.

3. **Một confidence threshold cho mọi trường**.

4. **Không có lớp unknown/other**.

5. **Không giữ file gốc hoặc hash**.

6. **Không ghi model version vào kết quả**.

7. **Cho downstream dùng trực tiếp JSON của vendor**.

8. **Trộn extraction với quyết định nghiệp vụ**.

9. **Dùng reviewer correction làm training data ngay lập tức**, không qua kiểm duyệt.

10. **Không có regression test cho model mới**.

11. **Đánh giá bằng accuracy trung bình**, che giấu lỗi nghiêm trọng ở trường tiền hoặc pháp lý.

12. **Tự động hóa 100% ngay từ đầu**.

13. **Không theo dõi chi phí theo loại tài liệu và từng bước pipeline**.

14. **Không có khả năng reprocess có kiểm soát**.

---

# 17. Kiến trúc khuyến nghị cuối cùng

Đối với phần lớn doanh nghiệp, thiết kế cân bằng nhất là:

* **Managed Document AI engine** của một cloud provider.
* **Event-driven asynchronous pipeline**.
* **Canonical document schema độc lập vendor**.
* **Classifier/splitter trước extractor**.
* **Kết hợp prebuilt + custom + generative models**, không ép một loại model giải mọi bài toán.
* **Business validation tách khỏi AI extraction**.
* **Field-level confidence và risk routing**.
* **Human review service độc lập**.
* **Immutable raw storage và evidence-level traceability**.
* **Versioning đầy đủ cho model, prompt, schema và rule**.
* **Evaluation bằng ground truth và KPI nghiệp vụ**.
* **Private networking, managed identity, KMS và audit log**.
* **Canary deployment, rollback và drift monitoring**.

Nói gọn theo công thức:

```text
Enterprise Document AI
=
OCR/Layout
+ Classification/Splitting
+ Extraction
+ Normalization
+ Business Validation
+ Human Review
+ Integration
+ Governance
+ Continuous Evaluation
```

Thiếu một trong các phần cuối thì vẫn có thể làm demo. Chỉ là production sẽ sớm biến thành một trung tâm nhập liệu thủ công đắt tiền, nhưng lần này có thêm hóa đơn cloud.

[1]: https://cloud.google.com/document-ai "Document AI | Google Cloud"
[2]: https://docs.cloud.google.com/document-ai/docs/reference/rest/v1/Document?utm_source=chatgpt.com "Document AI | Google Cloud Documentation"
[3]: https://docs.cloud.google.com/document-ai/docs/send-request?utm_source=chatgpt.com "Send a processing request | Document AI"
[4]: https://docs.aws.amazon.com/solutions/intelligent-document-processing-on-aws/ "docs.aws.amazon.com"
[5]: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/model-overview?view=doc-intel-4.0.0 "Document Processing Models - Document Intelligence - Foundry Tools | Microsoft Learn"
[6]: https://docs.cloud.google.com/document-ai/docs/ce-with-genai "Custom extractor with generative AI  |  Document AI  |  Google Cloud Documentation"
[7]: https://docs.cloud.google.com/document-ai/docs/ce-derived-signature?utm_source=chatgpt.com "Custom extractor with generative AI | Document AI"
[8]: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept/accuracy-confidence?view=doc-intel-4.0.0&utm_source=chatgpt.com "Interpret and improve model accuracy and confidence scores"
[9]: https://docs.aws.amazon.com/textract/latest/dg/textract-evaluating-improving-adapters.html?utm_source=chatgpt.com "Evaluating and improving your adapters - Amazon Textract"
[10]: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/train/custom-classifier?view=doc-intel-4.0.0 "Custom classification model - Document Intelligence - Foundry Tools | Microsoft Learn"
[11]: https://docs.aws.amazon.com/textract/latest/dg/textract-monitoring.html?utm_source=chatgpt.com "Monitoring Amazon Textract - AWS Documentation"
[12]: https://docs.cloud.google.com/document-ai/docs/security?utm_source=chatgpt.com "Document AI security and compliance"
[13]: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/faq?view=doc-intel-4.0.0&utm_source=chatgpt.com "Azure Document Intelligence in Foundry Tools (formerly ..."
[14]: https://docs.aws.amazon.com/textract/latest/dg/what-is.html "What is Amazon Textract? - Amazon Textract"
