# ADR-0013: Personal project — pypgx + CPIC public, một image tối giản

- **Trạng thái:** Accepted
- **Ngày:** 2026-10-26
- **Supersedes:** [ADR-0001](0001-architecture.md), [ADR-0004](0004-repo-image-management.md)
- **Amends:** [ADR-0012](0012-use-public-pypgx.md), [ADR-0003](0003-report-renderer-port.md)
- **Liên quan:** [ADR-0002](0002-assembly-grch37.md), [ADR-0006](0006-drop-hla.md)

---

## 1. Bối cảnh

Đây là **dự án cá nhân**, không dùng cho lâm sàng. Ưu tiên:

- Dùng **repo/kết quả public** (pypgx public, dữ liệu CPIC/PharmGKB public).
- Không fork VN, không port bảng VN, không validation/sign-off lâm sàng.
- Tối giản vận hành: một repo, một image, chạy local.

Phát hiện quan trọng: **pypgx 0.27.0 đã chứa sẵn dữ liệu khuyến nghị CPIC**:

| Table | Rows | Nội dung |
|---|---|---|
| `recommendation-table.csv` | 724 | `Drug, Gene1, Phenotype1, Gene2, Phenotype2, Recommendation` |
| `cpic-table.csv` | 518 | gene–drug, CPIC level, guideline URL, PMID |
| `phenotype-table.csv` | 74 | phenotype + risk label |
| `diplotype-table.csv` | 23.301 | diplotype → phenotype |

API public: `pypgx.get_recommendation(drug, gene1, pheno1, gene2?, pheno2?)`,
`pypgx.load_recommendation_table()`, `pypgx.load_cpic_table()`.

⇒ **Không cần `vgt-report-pgx`, không cần guideline DB VN.** Toàn bộ report có thể
dựng từ pypgx + CPIC public.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| S1 | **Một repo, một image, một process**: FastAPI + htmx + background worker thread. Chạy local. |
| S2 | **pypgx 0.27.0 public**; VCF phased; không Java/Beagle/panel/pixi. |
| S3 | **Report từ dữ liệu public của pypgx**: recommendation + cpic + phenotype tables; không `vgt-report-pgx`. |
| S4 | **SQLite + local filesystem** mặc định; Postgres/S3 là tuỳ chọn qua config (cùng interface). |
| S5 | **Không auth/RBAC/review/approve/audit**; chỉ disclaimer "research/educational". |
| S6 | **Job in-process** (`ThreadPoolExecutor`), trạng thái lưu DB; không Redis/SQS. |
| S7 | **Không validation harness vs production**; chỉ smoke test + golden nhỏ. |
| S8 | Giữ attribution CPIC/PharmGKB + license pypgx (MIT) trong report/README. |
| S9 | Mọi mở rộng (VN tables, HLA, multi-user) cần ADR mới — không thêm "phòng xa". |

---

## 3. Kiến trúc

```
Browser (htmx)
   │ upload VCF (+ .tbi)
   ▼
FastAPI (một process)
   ├─ lưu file: data/uploads/{run_id}/
   ├─ tạo run + thread nền
   │     ├─ QC: index, assembly, phased, missing (bcftools/pysam)
   │     ├─ pypgx run-chip-pipeline × 58 gene → results.zip
   │     ├─ parse → per-sample genotype/phenotype
   │     ├─ recommend: pypgx.get_recommendation(...) + cpic metadata
   │     └─ render: Jinja2 → HTML; WeasyPrint → PDF
   ├─ SQLite: run/report
   └─ serve report HTML/PDF
```

Không queue service, không object storage bắt buộc, không auth.

---

## 4. Luồng

```
POST /upload            → lưu file, tạo run(status=queued)
  background:
    QC          → fail: status=failed, error rõ
    star        → 58 gene
    recommend   → drug + phenotype → recommendation + CPIC level/URL
    render      → report.html, report.pdf
  status=done
GET /runs/{id}          → poll trạng thái (htmx every 2s)
GET /runs/{id}/report   → HTML
GET /runs/{id}/report.pdf
```

---

## 5. Dữ liệu (SQLite)

```sql
run(
  id text pk, filename text, sha256 text, assembly text,
  n_samples int, phased bool, status text, stage text,
  error text, params json, created_at, finished_at
)
sample(
  id text pk, run_id text, barcode text,
  star_json text,            -- gene → {genotype, phenotype, callable}
  rec_json text              -- drug → {recommendation, cpic_level, url, genes}
)
report(
  id text pk, run_id text, sample_id text,
  html_path text, pdf_path text, created_at
)
```

- `data/uploads/{run_id}/sample.vcf.gz(.tbi)`
- `data/reports/{run_id}/{barcode}.html|.pdf`
- Không lưu VCF lâu hơn cần thiết; có nút xoá run.

Nếu bật Postgres: cùng schema qua SQLAlchemy; nếu bật S3: thay `LocalStorage` bằng
`S3Storage` (cùng interface).

---

## 6. Report

Nội dung tối giản (tiếng Anh):

1. Header: file, barcode, assembly, ngày, disclaimer.
2. Gene table: gene, diplotype, phenotype, callable.
3. Drug table: drug, gene(s)+phenotype, recommendation, CPIC level, guideline link.
4. Ghi chú gene indeterminate/không gọi được.

Nguồn:
- genotype/phenotype: pypgx.
- recommendation: `pypgx.get_recommendation`.
- CPIC level/URL: `pypgx.load_cpic_table` join theo (gene, drug).
- risk label: `phenotype-table` (optional).

Không cần dịch VI, không cần nhóm thuốc, không cần `not_evaluable` phức tạp; chỉ
hiển thị "No recommendation found" nếu không khớp.

---

## 7. Tech stack

| Layer | Chọn |
|---|---|
| Web | FastAPI + Jinja2 + htmx |
| Store | SQLite (default) / Postgres optional |
| Files | local `data/` (default) / S3 optional |
| Star | pypgx 0.27.0 |
| QC | bcftools (apt) hoặc pysam |
| PDF | WeasyPrint |
| Package | `uv`, Python 3.12, một image |
| Test | pytest + smoke VCF |

Image ~1 GB (pypgx + fuc + scikit-learn + WeasyPrint). Một container, một lệnh.

---

## 8. Đã bỏ so với thiết kế trước

| Bỏ | Lý do |
|---|---|
| `vgt-report-pgx`, guideline DB VN | pypgx có recommendation/CPIC public |
| Polars cho guideline | 724 dòng, không cần |
| Hai image + queue Postgres | một process là đủ |
| S3/MinIO, Redis | local filesystem |
| Auth, RBAC, review/approve, audit | cá nhân |
| Validation harness vs production | không lâm sàng |
| HLA, VN tables, GRCh37 panel | ngoài phạm vi |

Giữ: GRCh37/38 (`--assembly`), htmx UI, report HTML/PDF, disclaimer.

---

## 9. Rủi ro & lưu ý

1. **Không dùng cho lâm sàng**; kết quả phụ thuộc pypgx public + CPIC, có thể khác
   bản VN. Ghi disclaimer rõ.
2. **VCF phải phased + indexed**; nếu không, báo lỗi rõ (không có Java để phase).
3. pypgx/fuc nâng version có thể đổi kết quả → pin `uv.lock`, test smoke.
4. CPIC/PharmGKB content có license riêng → giữ attribution, không thương mại hoá.
5. WeasyPrint cần font; nhúng Noto để PDF ổn định.
6. Job chạy trong process: restart giữa chừng → đánh dấu `failed` khi start lại.

---

## 10. Roadmap (gọn)

| Bước | Nội dung |
|---|---|
| 1 | skeleton FastAPI + htmx + SQLite, upload, QC, chạy pypgx 1 gene |
| 2 | 58 gene + parse + report HTML |
| 3 | recommendation + CPIC metadata + PDF |
| 4 | GRCh37, xoá run, disclaimer, đóng gói Docker |
```
