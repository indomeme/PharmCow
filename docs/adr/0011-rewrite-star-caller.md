# ADR-0011: Viết mới star caller — bỏ pypgx, Java, pixi

- **Trạng thái:** Superseded bởi [ADR-0012](0012-use-public-pypgx.md)
  (dùng pypgx public thay vì caller first-party). Các mục về VCF phased, validation
  oracle và refdata CSV/Polars vẫn còn giá trị tham khảo.
- **Ngày:** 2026-10-26
- **Supersedes:** [ADR-0007](0007-mvp-standalone.md), [ADR-0008](0008-pipeline-service.md),
  [ADR-0009](0009-toolchain-uv-pixi.md), [ADR-0010](0010-repo-relationships.md)
- **Amends:** [ADR-0001](0001-architecture.md), [ADR-0002](0002-assembly-grch37.md),
  [ADR-0004](0004-repo-image-management.md)

---

## 1. Bối cảnh

Quyết định: **viết mới star caller** cho phù hợp kiến trúc; không dùng
`mini-vcf-to-star`, không dùng `pypgx-private`. Ba câu trả lời đã chốt:

1. VCF đầu vào **luôn fully-phased** (imputed) → **không cần Beagle/Java**.
2. Guideline: dùng **Polars** (không pandas); dữ liệu dạng CSV canonical.
3. Bộ bảng VN hiện có **giữ lại**, port sang JSON/SQL.

Hệ quả: mất lý do tách pipeline image (Java), mất lý do có pixi (Python 3.9 +
pandas 1.1.5), mất lý do có submodule. Kiến trúc quay về **một image, một toolchain**.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| W1 | Star caller là **code first-party** trong `src/pharmcow/star/`; không phụ thuộc pypgx, không Java. |
| W2 | **Yêu cầu VCF fully-phased**. VCF unphased bị từ chối (`INPUT_UNPHASED`) hoặc phải phase ngoài hệ thống. |
| W3 | **Một image, một toolchain**: Python 3.12 + `uv`; pipeline là **role/command** trong worker, không phải service riêng. |
| W4 | **Bảng dữ liệu**: CSV canonical (`refdata/star/`, `refdata/guideline/`) + Parquet derived cho bảng lớn/precompute; **Polars** là engine runtime. |
| W5 | Port bộ bảng VN (allele/diplotype/phenotype/gene) vào `refdata/star/` kèm provenance, sha256, license note. |
| W6 | Output `star.csv` có thêm `coverage`, `callable`, `matched_variants`; gene không đủ dữ liệu → `callable=false`. |
| W7 | **CNV/SV ngoài phạm vi MVP**: CYP2D6/GSTM1/GSTT1 có thể chỉ gọi một phần; phải hiển thị rõ, không suy phenotype. |
| W8 | **Validation harness**: dùng pipeline cũ làm **oracle offline** trên bộ golden; so từng gene; chặn release nếu lệch. |
| W9 | GRCh37/GRCh38 hỗ trợ bằng **bảng toạ độ**, không cần panel 1KGP. |

---

## 3. Star caller mới

```
VCF (phased)
  → đọc region theo gene (pysam)
  → match core/tag variant theo (CHROM, POS, REF, ALT)
  → haplotype → diplotype → phenotype/activity score
  → star.csv: index,gene,Genotype,Phenotype,ActivityScore,Coverage,Callable
```

- Chuẩn hoá: chr-prefix, multiallelic (chọn đúng ALT), missing marker (đếm coverage).
- `Coverage` = số marker core/tag khớp / kỳ vọng; dưới ngưỡng (ví dụ 0.95) →
  `Callable=false`.
- Không dùng `pandas`; cấu trúc dữ liệu bằng dict/Polars khi cần.
- Hiệu năng: đọc theo region bằng index (`.tbi`/`.csi`), không scan toàn VCF.

**Bảng dữ liệu** (`refdata/star/`):

```
gene.csv              # gene, region GRCh37/38, method
allele.csv            # gene, star, core/tag variants theo assembly, function
diplotype.csv         # gene, diplotype, phenotype
activity.csv          # gene, allele, score
phenotype.csv         # phenotype → label vi/en
manifest.json         # version, git_sha, sha256 từng file, row counts
```

Nguồn: bộ bảng VN đang dùng trong `vgt-report-pgx`/pypgx fork. Việc port phải giữ
nguyên nội dung lâm sàng; chỉ đổi định dạng và tách khỏi code.

---

## 4. Guideline & Polars

- **CSV canonical** + Parquet derived:
  - `drug.csv`, `drug_recommendation.csv`, `drug_gene_source.csv`, `drug_group.csv`,
    `gene_pheno_combination.csv`, `popstat.csv` (từ `vgt-report-pgx`).
  - Build sinh `derived/drug_gene_pheno_combination.parquet` (cartesian product
    precompute) để runtime chỉ còn join.
- **`RefDataStore` port**:
  - `CsvPolarsStore` (MVP): load CSV/Parquet vào Polars một lần/process.
  - `PostgresStore` (sau): load cùng artifact vào schema `refdata` nếu cần admin/SQL.
- Version = sha của artifact; `run.versions.refdata` ghi lại.
- Lý do chọn CSV + Polars thay vì Postgres ngay: xem ADR-0001 §5.3.

---

## 5. Validation (bắt buộc)

Không được coi "viết mới" là thay thế hợp lệ nếu chưa đối chứng:

1. Bộ golden: ≥ 100 mẫu (GSA, APMRA, GRCh37, GRCh38, thiếu marker, hiếm).
2. Chạy pipeline cũ (image cũ) offline → `star_old.csv`.
3. So từng gene: diplotype, phenotype, activity score.
4. Ngưỡng: ≥ 99,5% cặp (sample, gene) khớp; mọi lệch phải phân loại
   (bug caller / khác bảng / khác định nghĩa) và có sign-off lâm sàng.
5. CI chạy harness này mỗi khi đổi `refdata/` hoặc `star/`.

Pipeline cũ **không** nằm trong runtime; chỉ dùng trong CI/validation.

---

## 6. Hệ quả

**Tích cực:**
- Một image (~350 MB), một toolchain (`uv`), build nhanh; không conda, không Java,
  không submodule.
- Không còn phụ thuộc fork `pypgx-private` (rủi ro cài nhầm public pypgx biến mất).
- Kiểm soát hoàn toàn logic gọi allele, dễ test, dễ mở rộng gene/assembly.
- Refdata CSV review được bằng diff, version bằng sha.

**Tiêu cực / rủi ro:**
- **Rủi ro lâm sàng lớn nhất**: tự viết caller phải được validate; sai một allele là
  sai report. Không có "pypgx đã kiểm chứng" làm lưới an toàn runtime nữa.
- CNV/SV (CYP2D6, GSTM1, GSTT1) không có trong MVP → một số gene chỉ gọi một phần;
  phải hiển thị `callable=false`, không được đoán.
- Bộ bảng VN là tài sản nội bộ: cần xác nhận quyền sử dụng và người chịu trách nhiệm
  nội dung.
- Polars khác pandas: team phải thống nhất API; không trộn hai thư viện.
- VCF unphased bị từ chối → cần thông báo rõ cho người dùng và quy trình phase ngoài.

---

## 7. Khi nào xem lại

- Nếu cần CNV/SV → bổ sung module (không quay lại pypgx).
- Nếu cần nhận VCF unphased → thêm bước phasing (container Beagle rời, không bake Java
  vào app image) hoặc từ chối có kiểm soát.
- Nếu guideline data tăng mạnh hoặc cần admin SQL → bật `PostgresStore` (cùng artifact).
