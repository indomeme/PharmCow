# ADR-0008: Tách pipeline (Java/pypgx) thành service riêng

- **Trạng thái:** Superseded bởi [ADR-0011](0011-rewrite-star-caller.md)
  (không còn Java/pypgx → không cần pipeline image riêng)
- **Ngày:** 2026-10-26
- **Supersedes:** [ADR-0007](0007-mvp-standalone.md) V2/V3 (một image)
- **Liên quan:** [ADR-0001](0001-architecture.md), [ADR-0004](0004-repo-image-management.md)

---

## 1. Bối cảnh

`vcf-to-star` kéo theo: JVM/Beagle (`java -Xmx2g` × 58 gene), panel 1KG ~190 MB/assembly,
pypgx + pandas 1.1.5 (Python 3.9), và profile RAM dao động 16–32 GB tuỳ VCF đã phased
hay chưa. Đưa tất cả vào image của web app là sai về:

- **Bảo mật**: bề mặt CVE của JVM/pypgx không nên nằm trong container phục vụ HTTP.
- **Vận hành**: web pod ~2 GB, autoscale kéo theo Java; pipeline cần instance RAM lớn.
- **Vòng đời**: pypgx/panel đổi rất ít; web đổi hàng ngày.
- **Cô lập lỗi**: một job OOM/Java crash không được làm chết web.

Quyết định: **tách pipeline thành service riêng**. Vẫn **một repo**, hai image.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| S1 | **Một repo, hai image**: `pharmcow` (app) và `pharmcow-pipeline` (Java/pypgx). Cùng version, build từ cùng commit. |
| S2 | `pharmcow-pipeline` là **worker service** (long-running, không phải HTTP service) poll job từ Postgres, chạy CLI, ghi kết quả. |
| S3 | Pipeline chứa **qc + star + recommend** (đều py3.9). Guideline DB là **artifact S3 versioned**, truyền qua `--db` → update DB không rebuild image. |
| S4 | App image **không có Java/pandas 1.1.5**, ~350 MB: FastAPI + htmx + assemble + WeasyPrint. |
| S5 | Giao tiếp duy nhất qua **bảng `job`** (Postgres) + file trong S3; pipeline chỉ có quyền `SELECT/UPDATE job`. |
| S6 | Job có `kind` (`qc`, `run`, `assemble`, `render`) và `profile` (`standard`, `heavy`); pipeline chỉ nhận `qc`/`run`. |
| S7 | Pipeline chạy **1 job/replica** (đã dùng `Pool(15)` bên trong); scale bằng số replica, sau này tách deployment theo `profile`. |
| S8 | **Không** Docker-in-Docker, **không** ECS RunTask ở MVP; prod = 3 service (api, worker, pipeline). |

---

## 3. Vì sao worker service, không phải HTTP service?

| | Worker service (chọn) | HTTP service | Job-per-run (ECS/K8s) |
|---|---|---|---|
| Độ phức tạp | Thấp: poll PG | Phải thiết kế API, auth, timeout, async | Cần quyền RunTask/Docker socket |
| Job dài 15–40 phút | Bình thường | Dễ timeout/connection drop | Bình thường |
| Right-sizing RAM | Theo replica/profile | Theo replica | Theo từng job (tốt nhất) |
| Idle cost | Có (1 replica) | Có | Không |
| Cô lập lỗi | Container restart, lease hết hạn | Tương tự | Tốt nhất |
| MVP | ✅ | ❌ | ❌ (để P4) |

HTTP service chỉ cần khi **hệ thống khác** muốn gọi trực tiếp star calling. Khi đó thêm
façade `POST /v1/run` quanh cùng image, không đổi pipeline.

---

## 4. Kiến trúc

```
┌────────────┐        ┌──────────────────────┐
│ Browser    │───────▶│ pharmcow-api         │  (image app, py3.12)
│ htmx       │◀───────│ FastAPI + Jinja2      │
└────────────┘        └───────┬──────────────┘
                              │ enqueue job (Postgres)
                     ┌────────▼─────────┐        ┌────────────────────┐
                     │ PostgreSQL       │◀───────│ pharmcow-worker    │  (image app)
                     │ job · run ·report│        │ assemble + render  │
                     └────────▲─────────┘        └─────────┬──────────┘
                              │ SKIP LOCKED                 │ HTML/PDF
                     ┌────────┴─────────┐                   ▼
                     │ pharmcow-pipeline│             S3 / MinIO
                     │ (image pipeline) │─────────────▶  vcf, csv,
                     │ qc + star +      │                result.json
                     │ recommend        │
                     └──────────────────┘
```

Luồng job:

```
POST /v1/runs
  → job(kind=qc)     → pipeline: normalize + coverage + split barcode
  → job(kind=run)    → pipeline: star.csv + recommend/{barcode}.csv + manifest.json
  → job(kind=assemble, per barcode) → app: CSV → CanonicalResult
  → job(kind=render) → app: Jinja2 → HTML → PDF
  → report READY
```

`run` (1 VCF) → nhiều `report` (1 barcode). Pipeline chạy 1 lần cho cả VCF; app fan-out
report.

---

## 5. Contract

### 5.1 Bảng `job`

```sql
job(
  id uuid pk,
  run_id uuid,
  kind text,            -- qc | run | assemble | render
  profile text,         -- standard | heavy
  status text,          -- queued | running | done | failed
  attempts int,
  available_at timestamptz,
  lease_expires_at timestamptz,
  payload jsonb,        -- {vcf, assembly, product, out, barcode?}
  result jsonb,         -- {keys, versions, error_code}
  last_error text,
  created_at, updated_at
)
```

- Claim: `SELECT … WHERE status='queued' AND kind = ANY(...) AND available_at <= now()
  ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1`.
- Heartbeat mỗi 30 s cập nhật `lease_expires_at`; chết → lease hết hạn → replica khác nhận.
- `attempts` tối đa 2; lỗi `OOM`/`TIMEOUT` không retry tự động.

### 5.2 CLI

```bash
pipeline qc  --vcf s3://... --assembly auto --out s3://.../qc/
pipeline run --vcf s3://... --assembly GRCh37|GRCh38 --product PGX_CLINICAL \
             --db s3://.../pgx-db/2026.10.0 --out s3://.../pipeline/ --threads 8
pipeline selftest
```

Output: `qc.json`, `star.csv`, `recommend/{barcode}.csv`,
`recommend/{barcode}_overview.csv`, `manifest.json`.

Exit code → `job.result.error_code`: `0 OK`, `2 INPUT_INVALID`, `3 ASSEMBLY_UNSUPPORTED`,
`4 COVERAGE_LOW`, `5 TOOL_FAILED`, `6 OOM`, `7 TIMEOUT`, `8 INTERNAL`.

CLI nhận cả path local và `s3://` (boto3, MinIO endpoint qua env khi dev).

### 5.3 Guideline DB artifact

```
s3://pharmcow-refdata/pgx-db/2026.10.0/
  manifest.json      # version, git_sha, sha256 từng file, row counts
  tables/*.csv
  metadata/*.csv|json
```

Pipeline tải về `/tmp/pgx-db`, verify sha, set `--db`. Không bake vào image.

---

## 6. Resource profile

| Profile | dùng khi | CPU/RAM | Ghi chú |
|---|---|---|---|
| `standard` | VCF đã phased | 8 / 16 GB | Beagle bị skip |
| `heavy` | VCF chưa phased | 16 / 32 GB | 58 × JVM `-Xmx2g`; `-t 6` |

MVP: một deployment `pipeline` cấu hình `standard`; job `heavy` xếp hàng chờ hoặc chạy
deployment thứ hai (cùng image, env `PROFILE=heavy`). P4 tách deployment theo profile.

---

## 7. Vận hành

- **Dev**: `docker compose up` gồm postgres, minio, api, worker, pipeline. Không cần
  Docker socket.
- **Prod**: 3 ECS service (api, worker, pipeline) + RDS + S3. Pipeline service dùng
  instance memory-optimized; không expose port.
- **Quyền**: task role của pipeline chỉ đọc/ghi prefix `s3://pharmcow/{barcode}/{run}/`
  và DB role chỉ `SELECT/UPDATE job`.
- **Log**: stdout JSON + `run_event`; log dài đẩy S3.
- **Timeout**: `qc` 10 phút, `run` 60 phút; vượt → kill + `TIMEOUT`.
- **Scale**: pipeline replica = số job song song; mỗi replica 1 job.

---

## 8. Hệ quả

**Tích cực:**
- App image nhỏ, không Java; pipeline độc lập scale/theo dõi.
- DB update không rebuild image (artifact S3).
- Không cần Docker socket/RunTask ở MVP.
- Vẫn một repo, một version, một CI.

**Tiêu cực:**
- Pipeline service cần quyền DB (giới hạn ở `job`) → thêm một điểm truy cập DB.
- Idle cost của replica pipeline.
- Long job cần heartbeat/lease đúng; nếu sai dễ chạy trùng.
- Hai image phải giữ tương thích contract (star CSV); cần contract test.
- Khi cần right-sizing theo job → phải chuyển sang job-per-run (P4).

---

## 9. Khi nào đổi

- **HTTP façade**: khi hệ thống cũ/đối tác cần gọi star calling trực tiếp.
- **Job-per-run**: khi volume > 50 job/ngày hoặc cần spot/right-sizing theo từng VCF.
- **Tách report image**: khi guideline DB đổi hàng tuần đến mức rebuild pipeline image
  thành nút thắt (dù đã có `--db`, code `vgt-report-pgx` vẫn nằm trong pipeline image).
