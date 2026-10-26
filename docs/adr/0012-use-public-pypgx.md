# ADR-0012: Dùng pypgx public làm engine star calling

- **Trạng thái:** Accepted, **được sửa bởi [ADR-0013](0013-personal-project.md)**
  (phạm vi cá nhân: một image, report từ pypgx/CPIC public, không validation lâm sàng)
- **Ngày:** 2026-10-26
- **Supersedes:** [ADR-0011](0011-rewrite-star-caller.md) (W1: caller first-party)
- **Amends:** [ADR-0001](0001-architecture.md), [ADR-0002](0002-assembly-grch37.md),
  [ADR-0004](0004-repo-image-management.md)

---

## 1. Bối cảnh

Quyết định: **dùng pypgx cho star calling** thay vì tự viết. Chốt bản **public pypgx
0.27.0** (PyPI, MIT), không dùng fork `pypgx-private`.
Input **luôn fully-phased** (imputed).

Hệ quả trực tiếp:

- pypgx 0.27.0 chạy được Python 3.12; dependency chỉ `fuc` + `scikit-learn`.
- VCF phased → `run_chip_pipeline` bỏ qua Beagle ⇒ **không cần Java**.
- Không phasing ⇒ **không cần panel 1KGP**, không cần `pypgx-bundle`.
- Không fork ⇒ **không cần `pypgx-private`, không pixi**; một toolchain `uv`.

> **Cảnh báo quan trọng:** bảng dữ liệu của public pypgx (0.27.0, 88 gene) **khác**
> bảng VN trong fork 0.21.0 (59 gene). Vì vậy kết quả star allele/phenotype **sẽ khác**
> bản đang chạy. Validation và sign-off lâm sàng là bắt buộc (mục 5). Nếu cần giữ đúng
> bảng VN, phải làm overlay/fork — quyết định riêng, không nằm trong ADR này.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| P1 | Engine: **`pypgx==0.27.0`** (PyPI) + `fuc` + `scikit-learn`; pin trong `uv.lock`. |
| P2 | **Không Java/Beagle/panel**: yêu cầu VCF fully-phased + không missing; nếu không → reject (`INPUT_UNPHASED`). |
| P3 | **Không `pypgx-private`, không `mini-vcf-to-star`**: viết adapter mỏng gọi pypgx API. |
| P4 | **Hai image, một repo, một `uv.lock`**: app (không pypgx) và pipeline (`--extra star`). Cùng Python 3.12. |
| P5 | Pipeline là **worker service** poll job `star`; app xử lý `report` (recommend Polars + assemble + render). |
| P6 | **Không overlay bảng VN ở MVP**: dùng bảng public; guideline tables vẫn là bộ VN (độc lập với star tables). |
| P7 | Output adapter chuẩn hoá về `star.csv` (`index,gene,Genotype,Phenotype,...`), giữ phenotype/activity do pypgx tính. |
| P8 | **Validation harness** so với output production hiện tại; diff theo gene; chặn release nếu lệch không giải thích. |

---

## 3. Kiến trúc

```
┌────────────┐      ┌──────────────────────────────┐
│ Browser    │─────▶│ pharmcow api (app image)      │  py3.12, không pypgx
│ htmx       │◀─────│ FastAPI · Jinja2 · RBAC       │
└────────────┘      └──────┬───────────────┬───────┘
                           │ SQL           │ S3
                    ┌──────▼───────┐  ┌────▼─────────────┐
                    │ PostgreSQL   │  │ S3/MinIO          │
                    │ run/job/...  │  │ vcf · csv · pdf   │
                    └──▲────────▲──┘  └────▲─────────────┘
                       │        │          │
        ┌──────────────┘        └──────────┐│
        │                                  ││
┌───────┴────────────┐        ┌────────────┴┴──────────────┐
│ worker (app image) │        │ pipeline (image +extra)     │
│ recommend Polars   │        │ QC bcftools → pypgx 58 gene │
│ assemble + render  │        │ → star.csv                  │
└────────────────────┘        └─────────────────────────────┘
```

Job:

```
upload → ingest (api)
  → job(star)      [pipeline]  QC + pypgx → star.csv, qc.json
  → job(report)    [app]       recommend (Polars) → assemble → render
  → READY → REVIEW → APPROVED
```

Một image app + một image pipeline, **cùng version, cùng `uv.lock`**, khác extras.
Có thể chạy một image duy nhất (bỏ extras) nếu muốn tối giản deploy.

---

## 4. Adapter pypgx

```
VCF indexed (phased)
  → bcftools view -g ^miss -Oz            # bỏ site missing
  → bcftools query -f '%GT\n' | check '|' # chặn unphased
  → pypgx run-chip-pipeline <gene> <out> <vcf> --assembly ...
      (consolidated → skip Beagle)
  → parse results.zip → star.csv
```

- Gene list: 58 gene của sản phẩm (giao với target gene của pypgx).
- `--assembly GRCh37|GRCh38` theo input.
- Chạy song song theo gene (process pool, giới hạn theo CPU/RAM).
- Không dùng `--impute`, không `--panel`.

Dependencies (extra `star`):

```
pypgx==0.27.0
fuc
scikit-learn
```

`bcftools` cài bằng apt trong image pipeline (không conda).

---

## 5. Validation bắt buộc

| Bước | Nội dung |
|---|---|
| 1 | Bộ golden ≥ 100 mẫu (GSA/APMRA, GRCh37/38, thiếu marker, hiếm) |
| 2 | Chạy production hiện tại (fork VN) và bản mới (pypgx public) offline |
| 3 | Diff theo gene: genotype, phenotype, activity score, callable |
| 4 | Phân loại lệch: do bảng khác / do phiên bản pypgx / do adapter |
| 5 | Ngưỡng: genotype ≥ 99% (kỳ vọng lệch ở gene VN-specific); sign-off từng nhóm |
| 6 | CI chạy lại khi đổi `pypgx` version hoặc `refdata/guideline` |

Nếu lệch do bảng VN và không chấp nhận được → mở ADR overlay/fork (copy bảng VN vào
image pypgx hoặc patch `load_*_table`), không sửa trực tiếp trong runtime.

---

## 6. Hệ quả

**Tích cực:**
- Không Java/panel/pixi/submodule; một toolchain `uv`, build nhanh.
- Upstream maintained (88 gene, cả hai build), có SVM SV detection cho WGS sau này.
- App image không chứa pypgx/scikit-learn.

**Tiêu cực / rủi ro:**
- **Khác bảng VN** → kết quả có thể khác; đây là rủi ro lâm sàng lớn nhất, phải
  validation + sign-off.
- pypgx public không có các tuỳ biến VN (nếu có) → một số phenotype/allele có thể đổi.
- VCF unphased bị từ chối; cần thông báo rõ và quy trình phase ngoài.
- `fuc` kéo matplotlib/seaborn/statsmodels → image pipeline ~1 GB.
- pypgx 0.27 chưa chắc tương thích pandas 3.x → pin `uv.lock`, test CI.

---

## 7. Khi nào xem lại

- Nếu diff VN quá lớn → overlay bảng VN hoặc quay lại fork (ADR mới).
- Nếu cần nhận VCF unphased → thêm bước phasing (container Beagle rời).
- Nếu cần CNV/SV cho WGS → pypgx có SVM CNV; cần input read-depth, ngoài phạm vi array.
