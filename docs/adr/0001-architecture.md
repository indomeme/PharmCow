# ADR-0001: Kiến trúc tổng thể PharmCOW

- **Trạng thái:** Superseded bởi [ADR-0013](0013-personal-project.md)
  (dự án cá nhân: một image, SQLite/local, report từ pypgx public)
- **Ngày:** 2026-10-26
- **Liên quan:** [ADR-0002](0002-assembly-grch37.md), [ADR-0003](0003-report-renderer-port.md),
  [ADR-0006](0006-drop-hla.md), [ADR-0012](0012-use-public-pypgx.md)

---

## 1. Bối cảnh

PharmCOW là hệ thống **độc lập**, viết mới: không dùng Mongo/SQS/`report-generator`/
`pdfexporter`/Keycloak của hệ thống cũ. Star calling dùng **public pypgx 0.27.0**
(ADR-0012); VCF đầu vào **luôn fully-phased** nên không cần Java/Beagle/panel.

| Thành phần | Vai trò | Cách dùng |
|---|---|---|
| pypgx 0.27.0 | Star allele + phenotype (58 gene của sản phẩm) | Engine trong pipeline image |
| Guideline VN | Tra cứu thuốc | CSV canonical + Polars |
| Report/PDF | Viết mới | Jinja2 + WeasyPrint |
| HLA | — | Archived (ADR-0006) |

Đặc điểm ảnh hưởng kiến trúc:

1. **Hai môi trường khác nhau về dependency, cùng Python 3.12**: app không cần pypgx;
   pipeline cần pypgx/fuc/scikit-learn. Một `uv.lock`, hai extras.
2. pypgx bỏ qua Beagle khi VCF fully-phased ⇒ không Java, không panel 1KGP.
3. Guideline nhỏ (~3k dòng) → CSV canonical + Polars; Postgres chỉ giữ state.
4. Report là data: `CanonicalResult` → HTML/PDF thuần; re-render không chạy lại caller.
5. Rủi ro lớn nhất: **public pypgx khác bảng VN** → phải validation + sign-off.

**Quyết định nghiệp vụ:** single-tenant; HLA ngoài phạm vi; report stack viết mới;
GRCh37 + GRCh38; dùng pypgx public.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| D1 | **Một repo, hai image, một `uv.lock`**: app (`pharmcow`) và pipeline (`pharmcow-pipeline`, `--extra star`). Cùng Python 3.12, cùng version. |
| D2 | **HLA ngoài phạm vi**: `CanonicalResult.hla.status = "not_requested"`; thuốc phụ thuộc HLA vào `not_evaluable`. |
| D3 | **Report là data**: pipeline sinh `star.csv`; app recommend + assemble + render. HTML/PDF là hàm thuần của `(result, template_version, locale)`. |
| D4 | **Queue Postgres** (`SKIP LOCKED`): job `star` (pipeline) và `report` (app). Không Redis. |
| D5 | **Postgres-only** cho state; guideline CSV/Parquet + Polars; không Mongo. |
| D6 | **Phased-only**: không nhận VCF unphased; không Java/Beagle/panel. |
| D7 | **Fail loud**: reject unphased/missing/thiếu marker; gene indeterminate → `callable=false`. |
| D8 | **Version mọi thứ**: image, pypgx, guideline, template. |

---

## 3. Kiến trúc

### 3.1 Sơ đồ

```
┌────────────┐  HTTPS      ┌───────────────────────────────────┐
│ Browser    │────────────▶│ pharmcow api (app image, py3.12)  │
│ htmx + SSE │◀────────────│ FastAPI · Jinja2 · RBAC           │
└────────────┘             └──────┬─────────────────┬──────────┘
                                  │ SQL             │ S3
                         ┌────────▼─────────┐  ┌────▼─────────────────┐
                         │ PostgreSQL       │  │ S3 / MinIO            │
                         │ run · job ·      │  │ vcf · csv · result    │
                         │ report · audit   │  │ html · pdf · logs     │
                         └───▲──────────▲───┘  └────▲─────────────────┘
                             │          │           │
              ┌──────────────┘          └───────────┐│
              │                                     ││
   ┌──────────┴──────────┐          ┌───────────────┴┴────────────┐
   │ worker (app image)  │          │ pipeline (image +extra star) │
   │ recommend (Polars)  │          │ QC bcftools → pypgx 58 gene  │
   │ assemble + render   │          │ → star.csv                   │
   └─────────────────────┘          └──────────────────────────────┘
```

Có thể deploy một image duy nhất (`uv sync --extra star`) nếu muốn tối giản; khi đó
cả hai role chạy từ cùng image. Mặc định vẫn tách để app không mang pypgx.

### 3.2 Job DAG

```
POST /v1/runs
  → ingest (api): header, sha, index, assembly, sample, phased?
  → job(star)   [pipeline]: bcftools QC + pypgx 58 gene → star.csv, qc.json
  → job(report) [app]: recommend (Polars) → assemble → render (per barcode)
  → READY → PENDING_REVIEW → APPROVED → ARCHIVED
```

`run` (1 VCF) → nhiều `report` (1 barcode). Job `star` chạy một lần cho cả VCF; job
`report` fan-out nội bộ theo barcode và enqueue render nếu cần.

### 3.3 Port

```python
class StarCaller(Protocol):
    def call(self, vcf: Artifact, assembly: Assembly) -> StarResult: ...

class RefDataStore(Protocol):
    def load(self, version: str) -> RefData: ...

class ReportRenderer(Protocol):
    def render(self, result: CanonicalResult, template: TemplateRef,
               locale: Locale) -> RenderOutput: ...
```

- `StarCaller` → adapter gọi pypgx (pipeline image).
- `RefDataStore` → `CsvPolarsStore` (MVP), `PostgresStore` (sau).
- `ReportRenderer` → `Jinja2WeasyPrintRenderer`.
- Không có `HlaCaller`.

---

## 4. Dữ liệu

### 4.1 PostgreSQL

```sql
app_user(id, email, password_hash, role, created_at, last_login_at)
api_key(id, name, key_hash, scopes, expires_at, last_used_at)   -- P4

sample(id, barcode, sex, age_group, site, meta jsonb, created_at)
upload(id, sample_id, object_key, sha256, bytes, assembly, n_samples,
       phased bool, qc jsonb, status, created_at)
run(id, upload_id, product_code, status, versions jsonb,
    error_code, error_detail, created_at, started_at, finished_at)
job(id, run_id, kind, status, attempts, available_at, lease_expires_at,
    payload jsonb, result jsonb, last_error, created_at, updated_at)
run_event(id, run_id, job_id, stage, status, detail jsonb, at)

report(id, sample_id, run_id, version, locale, product_code, status,
       result_key, result_sha256, summary jsonb,
       html_key, pdf_key, template_version,
       approved_by, approved_at, published_at)
report_template(id, key, version, locale, checksum, status, created_at)
refdata_bundle(id, version, object_key, sha256, manifest jsonb, active bool)
audit_log(id, actor_id, action, object_type, object_id, ip, ua, detail jsonb, at)
```

### 4.2 Refdata

```
refdata/
  guideline/{drug,drug_recommendation,drug_gene_source,drug_group,
             gene_pheno_combination,popstat}.csv
  derived/drug_gene_pheno_combination.parquet
  manifest.json        # version, git_sha, sha256, row counts
```

- Star tables **không** nằm ở đây: pypgx dùng bảng nội bộ của nó (ADR-0012).
- Guideline là bộ VN (giữ từ `vgt-report-pgx`), tách khỏi star tables.
- Artifact `pgx-refdata-{version}.tar.zst` → S3; `run.versions.refdata` ghi version+sha.

### 4.3 S3 layout

```
s3://pharmcow/{barcode}/{run_id}/
  input/sample.vcf.gz(.tbi)
  qc/qc.json
  work/{star.csv,recommend.csv,manifest.json}
  result/v1/result.json
  reports/v1/{report.html,report.pdf}
  logs/{job_id}.log
```

---

## 5. Vì sao chọn vậy

### 5.1 Hai image, một lock

pypgx + `fuc` kéo scikit-learn/matplotlib/statsmodels (~600 MB) — chỉ worker pipeline
cần. App image ~350 MB, không CVE surface của stack đó. Vẫn một `uv.lock`, một version;
pipeline image dùng `uv sync --extra star`.

### 5.2 Polars cho guideline

- Dữ liệu ~3k dòng, join/group ms; API typed, nhanh.
- Dùng cho recommend, validate/diff refdata, group report.
- Không dùng pandas; tránh trộn hai engine.

### 5.3 Guideline: CSV hay Postgres?

**Chọn CSV canonical + Polars**; Postgres là mirror tuỳ chọn.

| Tiêu chí | CSV + Polars | Postgres |
|---|---|---|
| Review lâm sàng | Diff CSV trong git | Diff qua seed/migration |
| Version | sha artifact | Cần cột/schema version |
| Runtime | Load ~10 ms | SQL join |
| Cập nhật hàng tháng | Thay artifact | Seed + swap |
| Admin search | Polars in-process | SQL mạnh hơn |
| Multi-consumer | Kém | Tốt |

Chuyển sang Postgres khi cần admin SQL/multi-consumer; load cùng artifact vào schema
`refdata`, CSV vẫn là nguồn chuẩn.

### 5.4 Bỏ Redis/Mongo

Hai loại job, volume thấp; Postgres đủ làm queue. Report ~50–200 KB → S3 + summary
JSONB.

---

## 6. API

| Method | Path | Mục đích |
|---|---|---|
| POST | `/v1/uploads` | presigned PUT + `upload_id` |
| POST | `/v1/uploads/{id}/complete` | xác nhận sha256 → enqueue star |
| POST | `/v1/runs` | `{upload_id, product_code}` |
| GET | `/v1/runs/{id}` | trạng thái, timeline, lỗi |
| GET | `/v1/runs/{id}/logs?job=` | tail log |
| GET | `/v1/samples/{barcode}/reports` | danh sách version |
| GET | `/v1/reports/{id}` | `CanonicalResult` |
| GET | `/v1/reports/{id}/html` | HTML (signed/inline) |
| GET | `/v1/reports/{id}/pdf` | 302 → signed URL |
| POST | `/v1/reports/{id}/rerender` | render lại với template version khác |
| POST | `/v1/reports/{id}/approve` | review + ký |
| POST | `/v1/samples/{barcode}/purge` | xoá theo yêu cầu dữ liệu |

Auth MVP: email + Argon2 + signed session cookie; role `viewer`/`operator`/
`reviewer`/`admin`. OIDC để sau.

---

## 7. UI (htmx)

- Server-render, không build JS: htmx + `htmx-ext-sse`, Alpine cho toggle.
- Dashboard, Upload, Run detail (timeline job, log), Report viewer (iframe, VI/EN, PDF),
  Admin (product, template, refdata version, user).
- **Gene coverage/callable matrix** sau QC; banner "Chưa phân tích HLA" + `not_evaluable`.
- CSS: Tailwind standalone CLI hoặc Pico.css; i18n Babel.

---

## 8. Tech stack & layout

| Layer | Chọn |
|---|---|
| Web | FastAPI + Uvicorn, Jinja2, htmx 2 + SSE, SQLAlchemy 2 async + asyncpg, Alembic |
| Data engine | **Polars** |
| Star engine | **pypgx 0.27.0** (pipeline extra) + bcftools (apt) |
| Queue | Postgres `SKIP LOCKED` |
| State DB | PostgreSQL 16 |
| Storage | S3 (prod) / MinIO (dev) |
| PDF | WeasyPrint + font nhúng |
| Package | `uv` (Python 3.12), một lock |
| Observability | OpenTelemetry, Prometheus, Sentry; log JSON có `run_id`/`job_id` |
| Deploy | Compose (dev) / ECS Fargate hoặc K8s (prod) |

```
PharmCOW/
  pyproject.toml / uv.lock          # core + [star] extra
  src/pharmcow/
    api/{app.py,routes/,deps.py}
    web/{templates/,static/}
    domain/{entities.py,ports.py,errors.py}
    db/{models.py,session.py,queue.py,migrations/}
    storage/{s3.py,presign.py}
    star/{pypgx_adapter.py,normalize.py}
    recommend/{engine.py,polars_store.py}
    report/{canonical.py,assemble.py,render.py,templates/}
    jobs/{worker.py,handlers.py}
    auth/{local.py,session.py}
  refdata/{guideline,derived,manifest.json}
  contracts/{star.schema.json,canonical-result.schema.json,fixtures/}
  deploy/{compose.yml,Dockerfile.app,Dockerfile.pipeline}
  tests/{unit,integration,e2e,golden/}
  docs/adr/
```

---

## 9. Sizing (ước tính — benchmark lại)

| Thành phần | CPU / RAM | Thời gian | Image |
|---|---|---|---|
| api | 1 / 2 GB | — | ~350 MB |
| worker (recommend/render) | 2 / 4 GB | < 1 phút/report | ~350 MB |
| pipeline star (58 gene, phased) | 4 / 8 GB | 1–4 phút | ~1 GB |

Không còn profile 32 GB (không JVM). Pipeline 1 job/replica; scale bằng replica.

---

## 10. Chất lượng & an toàn

- **Validation harness** (ADR-0012 §5): so với production hiện tại, diff theo gene,
  sign-off lâm sàng. CI chạy khi đổi pypgx/refdata.
- **Contract test**: `star.csv`/`recommend.csv` validate JSON Schema.
- **Selftest**: pypgx version, gene list 58, guideline row counts/sha.
- **Không "im lặng"**: gene indeterminate → "không kết luận"; thuốc HLA →
  `not_evaluable`; CNV ngoài phạm vi → cảnh báo CYP2D6/GSTM1/GSTT1.
- **Dữ liệu di truyền nhạy cảm** (NĐ 13/2023/NĐ-CP): mã hoá, tối thiểu hoá PII, audit,
  retention/purge, không log VCF/genotype.
- **Clinical governance**: `PENDING_REVIEW → APPROVED` có người ký; PDF gắn template
  version + QR verify; disclaimer.
- **License**: pypgx MIT; guideline CPIC/DPWG cần rà nếu mở bên thứ ba.

---

## 11. Roadmap

| Phase | Nội dung | Kết quả |
|---|---|---|
| **P0** (1 tuần) | skeleton (uv), compose (PG + MinIO), schema + queue, auth local, upload, ingest, refdata loader | upload + QC |
| **P1** (2 tuần) | pipeline adapter pypgx 58 gene (GRCh38), `star.csv`, validation 20 mẫu | star khớp/đã giải thích diff |
| **P2** (2 tuần) | GRCh37, recommend Polars, assemble, report HTML/PDF | end-to-end |
| **P3** (2 tuần) | review/approve, golden 100+ mẫu, observability, retention | sẵn sàng staging |
| **P4** | batch, API key/webhook, admin refdata, scale | production |

---

## 12. Hệ quả & rủi ro

**Chấp nhận:**
- Public pypgx khác bảng VN → kết quả có thể khác; validation là điều kiện go-live.
- Hai image (app/pipeline) nhưng một toolchain/lock.
- Guideline CSV ngoài DB.

**Rủi ro:**
1. Diff do bảng VN → nếu không chấp nhận, phải overlay/fork (ADR mới).
2. VCF unphased lọt vào → reject sớm; cần thông báo rõ.
3. pypgx/fuc nâng version đổi hành vi → pin + golden test.
4. WeasyPrint layout → test PDF text trong container.
5. Guideline đổi hành vi lâm sàng → version + diff review.
