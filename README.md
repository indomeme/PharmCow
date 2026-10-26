# PharmCOW

**Personal PGx report generator** — upload VCF đã imputation, gọi star allele bằng
**pypgx 0.27.0 public**, tra khuyến nghị CPIC có sẵn trong pypgx, xuất report
HTML/PDF.

> ⚠️ **Không dùng cho lâm sàng.** Đây là dự án cá nhân/học tập; kết quả phụ thuộc
> pypgx public + CPIC, không phải bản VN đã kiểm chứng. Mọi kết luận y tế cần bác sĩ.

## Trạng thái scaffold

Đã chạy end-to-end trên VCF phased (1–2 sample, gene giới hạn khi dev):

- upload + QC (assembly, phased, missing), background job, poll trạng thái bằng htmx
- pypgx 0.27 cho danh sách gene (`PHARMCOW_GENES` để giới hạn; mặc định 58)
- recommendation từ `pypgx.load_recommendation_table()` + `cpic-table`
- report HTML + PDF (WeasyPrint), SQLite + local `data/`
- `pharmcow selftest`, `pytest` (7 test)

Chưa có: auth, queue ngoài process, retry, đo full 58 gene trên bộ mẫu lớn.

## Kiến trúc

```
Browser (htmx)
  → FastAPI (một process, một image)
      ├─ upload VCF (+ .tbi) → data/uploads/{run_id}/
      ├─ background thread:
      │    QC (index, assembly, phased, missing)
      │    pypgx run-chip-pipeline × 58 gene
      │    parse → genotype/phenotype
      │    recommend: pypgx.get_recommendation + cpic-table
      │    render: Jinja2 → HTML, WeasyPrint → PDF
      └─ SQLite + data/reports/{run_id}/
```

Không Postgres/Redis/S3 bắt buộc, không auth, không queue service.

## Stack

| Layer | Chọn |
|---|---|
| Web | FastAPI + Jinja2 + htmx |
| DB | SQLite (default), Postgres optional |
| Files | local `data/` (default), S3 optional |
| Star | pypgx 0.27.0 (public) |
| QC | bcftools |
| PDF | WeasyPrint + Noto fonts |
| Package | `uv`, Python 3.12, một image |

## Chạy

```bash
make sync          # uv sync --extra star --extra dev
make serve         # http://127.0.0.1:8000
make test
make selftest
```

Hoặc trực tiếp:

```bash
uv sync --extra star
uv run pharmcow serve --reload
# mở http://127.0.0.1:8000
```

Docker:

```bash
make docker
docker run -p 8000:8000 -v "$PWD/data:/data" pharmcow
```

Yêu cầu VCF: **bgzip + index (.tbi/.csi)**, **fully-phased**, GRCh37 hoặc GRCh38.

### Troubleshooting

- **`sorted_nearest` build fails (`Python.h: No such file`)** — cài `python3-dev`/`python3.12-dev`,
  hoặc dùng Python do uv quản lý:
  `uv python install 3.12 && uv sync --python 3.12 --extra star`.
- **pypgx lỗi `setting an array element with a sequence`** — pypgx 0.27 chưa tương thích
  pandas 3; repo đã pin `pandas<3`, đừng nâng.
- **Unphased VCF** — bị từ chối (`INPUT_UNPHASED`); phase trước khi upload.
- **PDF lỗi** — cần pango/cairo/gdk-pixbuf; Dockerfile đã cài, trên host cài
  `libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0`.

## Report lấy từ đâu

pypgx 0.27.0 có sẵn dữ liệu public:

| Table | Rows | Dùng cho |
|---|---|---|
| `recommendation-table.csv` | 724 | `pypgx.get_recommendation(...)` |
| `cpic-table.csv` | 518 | CPIC level + guideline URL |
| `phenotype-table.csv` | 74 | risk label |
| `diplotype-table.csv` | 23.301 | diplotype → phenotype |

Không dùng `vgt-report-pgx`, không port bảng VN, không cần guideline DB riêng.

## Phạm vi

| Có | Không |
|---|---|
| Star allele + phenotype (58 gene) | HLA |
| Recommendation CPIC public | CNV/SV (array/imputed) |
| Report HTML/PDF | Clinical validation, sign-off |
| GRCh37/GRCh38 | Multi-user, auth, audit |
| SQLite + local files | Mongo/Redis/SQS/Java |

## ADR

| ADR | Trạng thái | Nội dung |
|---|---|---|
| [ADR-0013](docs/adr/0013-personal-project.md) | **current** | Phạm vi cá nhân: 1 image, SQLite/local, pypgx+CPIC public |
| [ADR-0012](docs/adr/0012-use-public-pypgx.md) | current (engine) | Dùng pypgx public 0.27.0, phased-only |
| [ADR-0002](docs/adr/0002-assembly-grch37.md) | current | GRCh37 + GRCh38 |
| [ADR-0003](docs/adr/0003-report-renderer-port.md) | current | Renderer Jinja2 + WeasyPrint |
| [ADR-0006](docs/adr/0006-drop-hla.md) | current | Bỏ HLA |
| [ADR-0001](docs/adr/0001-architecture.md), [0004](docs/adr/0004-repo-image-management.md), [0007](docs/adr/0007-mvp-standalone.md), [0008](docs/adr/0008-pipeline-service.md), [0009](docs/adr/0009-toolchain-uv-pixi.md), [0010](docs/adr/0010-repo-relationships.md), [0011](docs/adr/0011-rewrite-star-caller.md) | superseded | Lịch sử quyết định |

Mẫu: [Dockerfile](docs/templates/Dockerfile.template),
[manifest](docs/templates/manifest.example.yaml).

## Layout

```
src/pharmcow/
  api/          # routes + upload + SSE/poll
  web/          # templates htmx + report templates
  star/         # adapter pypgx + parse results
  recommend/    # pypgx recommendation + cpic metadata
  report/       # canonical result + render HTML/PDF
  jobs/         # background thread + status
  db/           # SQLAlchemy + SQLite
  storage/      # local (default) / s3 (optional)
data/           # uploads, reports, pharmcow.db
tests/          # smoke + golden nhỏ
docs/adr/
```

## Giới hạn & lưu ý

- Kết quả có thể khác bản VN (fork 0.21.0) do bảng public khác.
- VCF unphased bị từ chối (không có Java/Beagle).
- Gene indeterminate → hiển thị "no call"; không suy phenotype.
- CPIC/PharmGKB content giữ attribution; không dùng thương mại.
