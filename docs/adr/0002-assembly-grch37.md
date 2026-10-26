# ADR-0002: Hỗ trợ GRCh37 và GRCh38

- **Trạng thái:** Accepted
- **Ngày:** 2026-10-26
- **Liên quan:** [ADR-0001](0001-architecture.md), [ADR-0012](0012-use-public-pypgx.md)

---

## 1. Bối cảnh

pypgx 0.27.0 hỗ trợ cả GRCh37 và GRCh38 (`--assembly`), bảng allele/diplotype có toạ
độ cho cả hai build. Vì VCF đầu vào **fully-phased**, pipeline bỏ qua Beagle nên không
cần panel 1KGP, không cần Java, không liftover.

| Thành phần | GRCh38 | GRCh37 |
|---|---|---|
| pypgx (bảng nội bộ) | ✅ | ✅ |
| Star pipeline (phased) | ✅ | ✅ |
| Report | ✅ | ✅ (ghi rõ assembly) |

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| A1 | **Không liftover VCF.** Truyền `--assembly` đúng cho pypgx. |
| A2 | **Detect assembly** ở ingest: contig length + `##reference` + overlap marker; user xác nhận nếu mơ hồ. |
| A3 | QC chuẩn hoá **chr-prefix** (pypgx tự xử lý) và **bỏ site missing** trước khi gọi. |
| A4 | **Report ghi rõ assembly**; không so sánh/không trộn version khác build. |
| A5 | **Test đối chứng cross-build** là điều kiện bắt buộc. |

---

## 3. Chi tiết

### 3.1 Detect assembly

```
if contig lengths khớp GRCh37 (chr1=249.250.621, chr2=243.199.373): GRCh37
if contig lengths khớp GRCh38 (chr1=248.956.422, chr2=242.193.529): GRCh38
else: đếm overlap vị trí với bảng marker GRCh37 vs GRCh38 → chọn cao hơn
nếu vẫn mơ hồ: yêu cầu user chọn, run.status = NEEDS_ASSEMBLY
```

Alias: `hg19/b37/GRCh37` → `GRCh37`; `hg38/GRCh38` → `GRCh38`; còn lại reject
`ASSEMBLY_UNKNOWN`.

### 3.2 Star pipeline

- `pypgx run-chip-pipeline <gene> <out> <vcf> --assembly <build> --force`.
- VCF phải index (`.tbi`/`.csi`); nếu thiếu, tạo index trước.
- QC: `bcftools view -g ^miss -Oz` + check toàn bộ GT có `|` (phased).
- Không `--impute`, không `--panel`.
- Coverage/callable: gene không đủ marker → pypgx trả indeterminate; adapter đánh dấu
  `callable=false`.

### 3.3 Report

- `result.assay.assembly` hiển thị đầu report + metadata.
- VKORC1: thống nhất quy ước hiển thị (`-1639 A/G`), không phụ thuộc assembly.

---

## 4. Acceptance criteria

| Test | Ngưỡng |
|---|---|
| Cùng mẫu DNA, VCF GRCh37 vs GRCh38 → genotype/phenotype | ≥ 99,5% cặp (gene, sample) khớp; lệch phải giải thích |
| Assembly detection | 20 VCF hỗn hợp (chr prefix, hg19, hg38, header sai) → đúng 100% |
| Star output vs production hiện tại | Diff được phân loại; sign-off (ADR-0012 §5) |
| Report | 100% report có `assembly` + hiển thị UI/PDF |

---

## 5. Hệ quả

**Tích cực:**
- Không panel/liftover/Java → build nhẹ, ít lỗi.
- Assembly là thuộc tính xuyên suốt (upload → run → result → report).
- pypgx đã hỗ trợ cả hai build, không cần code riêng.

**Tiêu cực / rủi ro:**
- pypgx public có thể khác bảng VN ở một số allele của một build.
- VCF trộn assembly hoặc contig lạ → reject.
- Phải kiểm tra index/phased trước khi gọi để tránh pypgx rơi vào Beagle (không có Java).
