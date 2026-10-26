# ADR-0007: MVP standalone — một repo, một backend thống nhất

- **Trạng thái:** Superseded bởi [ADR-0011](0011-rewrite-star-caller.md)
  (bỏ pypgx/Java → quay lại một image, uv only)
- **Ngày:** 2026-10-26
- **Supersedes:** [ADR-0003](0003-report-renderer-port.md) (tái sử dụng report stack cũ),
  [ADR-0005](0005-repo-topology-after-hla.md) (polyrepo)
- **Amends:** [ADR-0001](0001-architecture.md), [ADR-0004](0004-repo-image-management.md)
- **Liên quan:** [ADR-0002](0002-assembly-grch37.md), [ADR-0006](0006-drop-hla.md),
  [ADR-0008](0008-pipeline-service.md)
- **Ghi chú:** V2/V3/§4/§5.1 dưới đây là quyết định ban đầu (một image). Bản hiện hành:
  [ADR-0001](0001-architecture.md); lý do tách pipeline: [ADR-0008](0008-pipeline-service.md).

---

## 1. Bối cảnh

Ba thay đổi so với thiết kế trước:

1. **Tách biệt hệ thống cũ**: không dùng chung Mongo `report.kit_result`, SQS,
   `report-generator` (Go), `pdfexporter`, Keycloak của hệ thống cũ.
2. **Report/PDF viết lại tối giản**: không cần adapter tương thích legacy, không
   shadow mode, không projection Mongo.
3. **MVP gom vào repo `PharmCOW`** như một backend thống nhất; HLA đã bỏ (ADR-0006).

Hệ quả: các quyết định "tái sử dụng report stack" (ADR-0003) và "polyrepo" (ADR-0005)
không còn đúng cho MVP.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| V1 | **Một repo `PharmCOW`** là nguồn sự thật duy nhất cho web, worker, pipeline adapter, report engine, template, contract. |
| V2 | **Một repo, hai image** (sửa bởi ADR-0008): `pharmcow` (app) + `pharmcow-pipeline` (Java/pypgx); ba process: api, worker, pipeline. |
| V3 | App env (`uv`, 3.12) và pipeline env (`pixi`, 3.9 + Java) nằm ở **hai image riêng**; pipeline là worker service poll job Postgres. |
| V4 | **Postgres-only** cho state + report metadata; `result.json` lưu S3, `summary jsonb` trong Postgres. **Không dùng Mongo** trong MVP. |
| V5 | **Queue bằng Postgres** (`SELECT … FOR UPDATE SKIP LOCKED`), không Redis ở MVP. |
| V6 | **Renderer native**: Jinja2 → HTML → PDF bằng WeasyPrint, chạy trong worker; không service ngoài. |
| V7 | **Giữ `vgt-report-pgx` làm recommendation engine** trong pipeline env (tra cứu guideline); chỉ **viết lại assembly + render**. |
| V8 | **Auth local** (email + Argon2 + session cookie + RBAC). OIDC/Keycloak để sau. |
| V9 | Refdata: pypgx panel **bake** vào pipeline image; guideline DB là **artifact S3** versioned (`--db`) để update không rebuild (ADR-0008). |
| V10 | **Job contract** (`job` table + CLI) cho phép đổi sang job-per-run/HTTP façade sau này mà không đổi code nghiệp vụ. |

---

## 3. Repo layout

```
PharmCOW/
  pyproject.toml / uv.lock            # app: Python 3.12, uv
  src/pharmcow/
    api/{app.py,routes/,deps.py}
    web/{templates/,static/}          # htmx UI
    domain/{entities.py,ports.py,errors.py}
    db/{models.py,session.py,queue.py, migrations/}
    storage/{s3.py,presign.py}
    jobs/{kinds.py,queue.py}          # job kinds + scheduler
    pipelines/{star.py,recommend.py,contract.py}
    report/{canonical.py,assemble.py,render.py,templates/}
    auth/{local.py,session.py}
    settings.py
  pipeline/
    pixi.toml / pixi.lock             # Python 3.9 + bcftools + java + pypgx + vgt-report-pgx
    vendor/mini-vcf-to-star/          # pinned submodule (hoặc wheel)
    vendor/pypgx-private/             # pinned submodule/wheel 0.21.0+vn
    vendor/vgt-report-pgx/            # pinned submodule (dùng cho query + DB)
    cli.py                            # entrypoint: qc | run | selftest | --version
    Dockerfile                        # image pharmcow-pipeline (ADR-0008)
  contracts/
    pipeline-output.schema.json
    fixtures/
  deploy/{compose.yml,Dockerfile.app}
  tests/{unit,integration,e2e}
  docs/adr/
```

Quy tắc import: `src/pharmcow/**` không import `pipeline/**`; giao tiếp duy nhất qua
bảng `job` (Postgres) + file output. `report/**` không import `pipelines/**`.

---

## 4. Luồng chạy

```
Browser (htmx)
   │ presigned PUT
   ▼
S3/MinIO ──▶ FastAPI api ──▶ Postgres (enqueue job)
                               │
                ┌──────────────┴───────────────┐
                ▼                              ▼
        worker (assemble/render)      pipeline service (qc/run)
                │                              │
                │                    mini-vcf-to-star + vgt-report-pgx
                │                              │  star.csv, recommend/…, manifest.json
                ▼                              ▼
        CanonicalResult → HTML/PDF        S3 outputs
                │
                ▼
        S3: result.json, report.html, report.pdf
        Postgres: report row (version, keys, status)
```

Stage trong `run`:

```
ingest (app: header, assembly, sha, index, sample)
  → qc (pipeline: normalize, marker coverage)  ── fail ──▶ REJECTED
  → star + recommend (pipeline)
  → assemble (app)
  → render (app)
  → READY → PENDING_REVIEW → APPROVED → ARCHIVED
```

---

## 5. Vì sao chọn vậy

### 5.1 Một image hay hai image?

**Quyết định cuối: hai image** — [ADR-0008](0008-pipeline-service.md), vì Java/JVM,
profile RAM 16–32 GB, bảo mật và vòng đời release. Bảng dưới giữ phân tích ban đầu:

| | Một image (ban đầu) | Hai image (chốt) |
|---|---|---|
| Deploy | 1 ECR repo, 1 task definition | 2 ECR repo, 3 service (api/worker/pipeline) |
| Dev | 1 app service + DB | compose thêm 1 service pipeline (cùng repo) |
| Web pod | ~2 GB (Java + panel) | ~350 MB, không Java |
| Scale | web kéo theo image nặng | pipeline scale độc lập, instance RAM lớn |
| Cô lập lỗi | Java OOM ảnh hưởng worker | container pipeline riêng |
| Vòng đời | pypgx đổi hiếm nhưng buộc rebuild web | pipeline rebuild riêng |

Pipeline là **worker service poll Postgres**, không cần executor/docker socket, nên dev
vẫn là `docker compose up`; không phải gọi Docker/ECS ngay từ đầu.

### 5.2 Bỏ Mongo

Lý do Mongo tồn tại trong thiết kế cũ là **tương thích `report-generator`** đọc
`kit_result`. Hệ thống mới không còn consumer đó. Report document ~50–200 KB, đọc
theo `(barcode, version)`, không cần schema động → **Postgres JSONB + S3** đủ và bớt
một hệ quản trị. Nếu sau này cần document store, thêm sau `ReportRepository`.

### 5.3 Bỏ Redis

Chỉ có 2–3 loại job, volume thấp; Postgres đã là nguồn sự thật. Queue bằng
`SKIP LOCKED` + `lease_expires_at` giữ được tính transactional, không cần thêm service.
Khi cần scheduling/rate-limit/priority phức tạp → Celery + Redis.

### 5.4 WeasyPrint

- Thuần Python, không binary ngoài (khác wkhtmltopdf), không cần Chromium.
- Hỗ trợ CSS Paged Media: `@page`, page number, header/footer, tránh `break-inside`.
- Đủ cho report dạng section + bảng; không cần JS.
- Font nhúng từ repo (Noto Sans Vietnamese) để PDF deterministic.
- Nếu design cần CSS phức tạp (grid/flex nâng cao) → đổi sang Chromium headless
  trong `render.py`, không đổi template.

### 5.5 Giữ `vgt-report-pgx`

Phần tra cứu guideline (195 thuốc / 1.434 recommendation / 22 nhóm) là tài sản đã
được kiểm chứng; viết lại là rủi ro không cần thiết cho MVP. Ta chỉ thay:
- assembly (CSV → `CanonicalResult`) — thay `report_parser/report.py` cũ;
- render (Jinja2 + WeasyPrint) — thay `report-generator` + `pdfexporter`;
- bỏ Mongo/SQS.

---

## 6. Contract pipeline CLI

```bash
cli qc  --vcf <path|s3> --assembly auto --out <dir>
cli run --vcf <path|s3> --assembly GRCh37|GRCh38 --product <code> \
        --out <dir> [--db <path>] [--threads N]
cli selftest
cli --version
```

Output:

| File | Nội dung |
|---|---|
| `qc.json` | assembly, phased, coverage từng gene, sample list, lỗi |
| `star.csv` | `index,gene,Genotype,Phenotype` (+ cột phụ) |
| `recommend/{barcode}.csv` | recommendation theo thuốc (nhóm, category, VI/EN, percentage…) |
| `recommend/{barcode}_overview.csv` | gene → genotype/phenotype VI/EN |
| `manifest.json` | version pypgx/tables/panel/guideline DB/assembly/hai image |

Exit code taxonomy: `0 OK`, `2 INPUT_INVALID`, `3 ASSEMBLY_UNSUPPORTED`,
`4 COVERAGE_LOW`, `5 TOOL_FAILED`, `6 OOM`, `7 TIMEOUT`, `8 INTERNAL`.
Worker map sang `job.result.error_code`.

---

## 7. Khi nào xem lại

- **Job-per-run (ECS RunTask/K8s Job)** khi: > 50 job/ngày, cần spot hoặc right-size
  RAM theo từng VCF thay vì theo replica.
- **HTTP façade** khi: hệ thống cũ/đối tác cần gọi star calling trực tiếp.
- **Tách report image** khi guideline DB đổi thường xuyên đến mức rebuild pipeline
  image thành nút thắt (dù `--db` đã tách dữ liệu, code `vgt-report-pgx` vẫn nằm trong
  pipeline image).
- **Thêm Mongo** khi: cần lưu report document schema-flexible cho consumer ngoài,
  hoặc report > 1 MB và query phi cấu trúc.
- **Thêm Redis** khi: > 100 job/giờ, cần priority/rate-limit/scheduling.
- **Viết lại recommendation engine** khi: cần sửa logic tra cứu/DB schema; đó là
  quyết định riêng, không nằm trong MVP.

---

## 8. Hệ quả

**Tích cực:**
- Một repo, một version, hai image → triển khai và debug đơn giản.
- Bỏ 3 hệ thống phụ (Mongo, Redis, SQS/Go service) và 2 repo pipeline.
- Renderer viết mới toàn quyền kiểm soát layout/PDF, không phụ thuộc wkhtmltopdf.

**Tiêu cực:**
- Hai image; pipeline ~1.7 GB, app ~350 MB (Java/panel chỉ nằm ở pipeline).
- Guideline DB là artifact S3 → thêm bước publish/verify (đổi lại: không rebuild image).
- Recommendation engine vẫn phụ thuộc `vgt-report-pgx` (pandas 1.1.5) → pipeline env
  bị pin Python 3.9; app env độc lập 3.12.
- Hai image phải giữ contract CLI + schema ổn định; test tích hợp bắt buộc.
