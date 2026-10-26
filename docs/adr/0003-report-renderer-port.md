# ADR-0003: Report renderer tối giản (native)

- **Trạng thái:** Accepted (thay thế phiên bản "tái sử dụng legacy")
- **Ngày:** 2026-10-26
- **Liên quan:** [ADR-0001](0001-architecture.md), [ADR-0007](0007-mvp-standalone.md)

---

## 1. Bối cảnh

Report stack cũ (`report-generator` Go + `pdfexporter` + Mongo `kit_result` + SQS +
template wkhtmltopdf) không còn dùng vì hệ thống mới tách biệt. MVP cần:

- một `CanonicalResult` ổn định làm nguồn sự thật;
- HTML cho web view và PDF cho tải/ký, **cùng một template**;
- re-render khi đổi template mà không chạy lại pipeline;
- không service ngoài, không Mongo, không SQS.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| R1 | `CanonicalResult` (JSON, `schema_version`) là sản phẩm thật; lưu S3 + trỏ từ Postgres. |
| R2 | `ReportRenderer` là port, chỉ **một** implementation: `Jinja2WeasyPrintRenderer`. |
| R3 | HTML web và PDF dùng **cùng template** + CSS `@media screen` / `@media print`. |
| R4 | Template có version + checksum trong `report_template`; report tham chiếu version. |
| R5 | Re-render = `(result.json, template_version)`; không cần pipeline. |
| R6 | PDF deterministic: font nhúng, không timestamp động trong nội dung, metadata cố định. |
| R7 | Không có adapter legacy, không Mongo projection, không shadow mode. |

---

## 3. `CanonicalResult` v1

```json
{
  "schema_version": "1.0",
  "report_id": "01J...",
  "subject": { "barcode": "5516724531600083027580", "sex": "F", "age_group": "adult" },
  "assay": { "assembly": "GRCh38", "product_code": "PGX_CLINICAL", "panel": "GSAv3" },
  "hla": { "status": "not_requested" },
  "genes": [
    { "gene": "CYP2C19", "diplotype": "*2/*3", "phenotype": "poor_metabolizer",
      "activity_score": 0.0, "callable": true }
  ],
  "recommendations": [
    { "drug": "clopidogrel", "drug_group": "ANTITHROMBOTIC AGENTS",
      "category": "Avoid", "gene_phenotype": "CYP2C19 *2/*3",
      "recommendation": { "vi": "...", "en": "..." },
      "population_percent": 0.012, "source": "CPIC" }
  ],
  "not_evaluable": [
    { "drug": "carbamazepine", "reason": "HLA_NOT_IN_SCOPE" }
  ],
  "qc": {
    "variants": 5123456, "phased": true,
    "gene_coverage": { "CYP2D6": 0.98, "GSTM1": 0.71 },
    "indeterminate": ["CYP2D6"]
  },
  "versions": {
    "pgx_db": "2026.10.0", "pypgx": "0.21.0+vn",
    "image": "v0.1.0", "template": "clinical_2026_01"
  },
  "disclaimers": ["..."],
  "generated_at": "2026-10-26T10:00:00Z"
}
```

Quy tắc:
- `hla.status = "not_requested"` (ADR-0006). Enum giữ giá trị cũ để đọc report legacy
  nếu cần, nhưng PharmCOW không sinh ra giá trị khác.
- `genes[].callable = false` khi indeterminate/thiếu marker → renderer hiển thị
  "không kết luận", không suy phenotype.
- Không có HTML/text trong `CanonicalResult`; chỉ dữ liệu + template ref.
- `not_evaluable` bắt buộc có khi thiếu HLA/CNV.

---

## 4. Render

```python
class ReportRenderer(Protocol):
    def render(self, result: CanonicalResult, template: TemplateRef,
               locale: Locale) -> RenderOutput: ...
```

- `template` resolve từ `report_template` (key, version, checksum); thiếu checksum
  khớp → fail.
- Render HTML bằng Jinja2 (autoescape), asset từ `src/pharmcow/web/static`.
- PDF: `weasyprint.HTML(string=html, base_url=...).write_pdf()`.
- Font: Noto Sans/Serif Vietnamese nhúng trong repo, khai báo `@font-face` đường dẫn
  tương đối để PDF giống nhau giữa dev/prod.
- CSS Paged Media: `@page { size: A4; margin: ... }`, header/footer, `counter(page)`,
  `break-inside: avoid` cho bảng thuốc, `break-before: page` cho section.
- Ảnh/QR: sinh bằng Python (QR verify link) hoặc SVG inline, không phụ thuộc JS.
- i18n: chọn locale ở request; template dùng `t()` với catalog vi/en.

Cấu trúc template (gợi ý):

```
report/
  base.html            # layout chung screen + print
  clinical/
    v1/report.html     # bìa, tóm tắt gene, nhóm thuốc, not_evaluable, disclaimer
    v1/report.css
  partials/{drug_table.html,gene_table.html,header.html,footer.html}
  assets/{fonts/,logo.svg,qr_placeholder.svg}
```

---

## 5. Version & re-render

- `report_template(key, version, checksum, locale, status)`.
- `report.template_version` + `report.result_sha256` lưu cùng report.
- `POST /v1/reports/{id}/rerender {template_version}` → render lại, tạo version mới,
  giữ nguyên `result.json`.
- Rollback = chọn template version cũ.
- Không sửa template version đã dùng cho report `APPROVED`; tạo version mới.

---

## 6. Kiểm thử

| Fixture | Nội dung |
|---|---|
| `default` | 10–15 thuốc, 1 gene indeterminate, HLA `not_requested` |
| `not_evaluable` | có thuốc HLA + lý do |
| `grch37` | assembly GRCh37, VKORC1 |
| `multi_sample` | 20 barcode, render riêng từng report |
| `long` | 50+ thuốc, kiểm tra page break |

Mỗi fixture: snapshot text PDF (không so pixel), số trang, thứ tự section, và HTML
snapshot. Diff ngoài snapshot = fail CI. PDF phải mở được bằng `pypdf` và có metadata
`Title/Author/Subject` cố định.

---

## 7. Hệ quả

**Tích cực:**
- Một template cho web + PDF; sửa layout một chỗ.
- Không service ngoài; render trong worker, vài giây/report.
- Re-render không tốn compute pipeline.
- Toàn quyền kiểm soát thiết kế report (không bị giới hạn bởi template cũ).

**Tiêu cực / rủi ro:**
- WeasyPrint không hỗ trợ đầy đủ flex/grid → template phải dùng table/column.
- Font/asset sai đường dẫn → PDF lỗi; test trong container, không chỉ trên host.
- Template mới phải được review lâm sàng trước khi dùng cho report chính thức.
- Nếu sau này cần HTML phức tạp/JS → đổi sang Chromium trong `render.py`, giữ nguyên
  `CanonicalResult` và template contract.
