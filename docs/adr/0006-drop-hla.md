# ADR-0006: Bỏ HLA khỏi phạm vi PharmCOW

- **Trạng thái:** Accepted
- **Ngày:** 2026-10-26
- **Supersedes:** [ADR-0001](0001-architecture.md) (D2 và mọi mục HLA),
  [ADR-0002](0002-assembly-grch37.md) (phần HLA GRCh37)
- **Liên quan:** [ADR-0003](0003-report-renderer-port.md), [ADR-0005](0005-repo-topology-after-hla.md)

---

## 1. Bối cảnh

Thiết kế ban đầu (ADR-0001/0002) đưa HLA vào như một stage tuỳ chọn, kèm kế hoạch
làm panel map GRCh37. Ba lý do khiến quyết định thay đổi:

1. **Phạm vi sản phẩm**: report PGx giá trị chính nằm ở star allele + guideline;
   HLA chỉ phục vụ một nhóm thuốc nhỏ (carbamazepine, allopurinol, abacavir…).
2. **Chi phí validation**: model HLA chỉ đúng với panel GSAv3/APMRA96; hỗ trợ GRCh37
   cần panel map + đối chứng genotype (ADR-0002) — ước tính 2–3 tuần, trong khi
   giá trị/độ phủ thấp.
3. **Rủi ro sai âm thầm**: `load_vcf_file` điền 0 cho marker thiếu và chỉ raise khi
   overlap < 50%; kết quả HLA có thể vô nghĩa mà pipeline vẫn xanh.

Quyết định: **bỏ HLA khỏi PharmCOW**. Repo `vgt-hla-imputation` vẫn tồn tại cho các
pipeline legacy/PCR bên ngoài PharmCOW.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| H1 | PharmCOW **không gọi HLA**. Không có stage `hla_condition`/`hla_call`, không có image HLA trong DAG và trong `manifest.yaml`. |
| H2 | Giữ repo `vgt-hla-imputation` ở trạng thái **archived**; không xoá, không đưa vào release lock. Pipeline legacy dùng tiếp tag/image cũ. |
| H3 | `CanonicalResult.hla` **vẫn giữ** với `status = "not_requested"` để schema/renderer ổn định và dễ bật lại; DB mới không cần cột `hla_*`. |
| H4 | Thuốc phụ thuộc HLA đưa vào `not_evaluable` với lý do `HLA_NOT_IN_SCOPE` — **không** bị bỏ khỏi report và **không** ngầm hiểu là "âm tính". |
| H5 | Product config phải được rà lại: hoặc giữ thuốc HLA kèm nhãn "chưa đánh giá", hoặc loại khỏi gói. Quyết định theo từng product, ghi trong config version. |
| H6 | ADR-0002: **huỷ** phần HLA GRCh37; GRCh37 cho star vẫn giữ nguyên. |
| H7 | Port `HlaCaller` bị xoá. Muốn bật lại HLA phải có ADR mới + đánh giá lại validation/GRCh37. |

---

## 3. Thay đổi cụ thể

| Hạng mục | Trước | Sau |
|---|---|---|
| DAG | `… → qc → star_call + hla_call → merge_hla → recommend → …` | `… → qc → star_call → recommend → assemble → render` |
| Port | `StarCaller`, `HlaCaller`, `RecommendationEngine`, `ReportRenderer` | `StarCaller`, `RecommendationEngine`, `ReportRenderer` |
| `RecommendationEngine` | `recommend(star, hla, product)` | `recommend(star, product)` |
| API `POST /v1/runs` | `{upload_id, product_code, hla}` | `{upload_id, product_code}` |
| DB `run` | có `hla_mode` | bỏ `hla_mode` |
| Storage | `stages/03_hla/...`, `stages/04_report/...` | `stages/03_report/...` |
| Manifest/refdata | `hla_model`, `hla_panel` | bỏ |
| Sizing | có dòng `hla_call` | bỏ |
| Roadmap | P2/P3 có việc HLA | dồn thời gian cho GRCh37 star + review/PDF |
| Golden test | fixture `with_hla`, `low_coverage` | chỉ còn `without_hla` (mặc định), `grch37`, `indeterminate`, `multi_sample` |
| Product config | 22 nhóm / 187 thuốc | rà nhóm có thuốc HLA, thêm nhãn `not_evaluable` |

**Giữ nguyên có chủ đích:**
- Field `hla` trong `CanonicalResult` (status `not_requested`).
- Fixture `with_hla` trong repo test (chỉ không chạy mặc định) để có thể kiểm tra
  renderer khi HLA quay lại.

---

## 4. An toàn lâm sàng

Đây là phần **bắt buộc**, không phải tuỳ chọn:

- Report phải hiển thị rõ "Chưa phân tích HLA" ở phần đầu và trong mục thuốc liên quan.
- Danh sách `not_evaluable` phải nêu tên thuốc + lý do; API trả cùng dữ liệu.
- Không được dùng câu "không phát hiện allele nguy cơ" khi HLA chưa chạy.
- Nếu product bán gói có thuốc HLA (carbamazepine, allopurinol, abacavir…), phải có
  xác nhận của owner sản phẩm rằng gói đó chấp nhận "không đánh giá HLA", hoặc loại
  thuốc khỏi gói.

---

## 5. Legacy & archive

- Repo/image HLA vẫn được giữ cho pipeline microarray/PCR cũ; không nằm trong
  `manifest.yaml` của PharmCOW và không được orchestrator gọi.
- Vẫn phải xử lý nợ bảo mật của repo này: token Bitbucket trong `Dockerfile` cần
  rotate + xoá (ADR-0004, mục 10) dù repo archive.
- Không xoá tag/image cũ; đặt lifecycle "keep last N releases".

---

## 6. Điều kiện bật lại HLA

Chỉ xem xét lại khi có đủ:

1. Yêu cầu sản phẩm cụ thể (khách hàng/gói) cho thuốc phụ thuộc HLA.
2. Panel map cho **cả** GRCh37 và GRCh38 đã validate (≥ 98% concordance top-2).
3. Model xuất được confidence + coverage, và pipeline fail khi coverage < 95%.
4. ADR mới ghi rõ phạm vi, product nào bật, cách hiển thị.

---

## 7. Hệ quả

**Tích cực:**
- Giảm 1 image (~1–3 GB), 1 repo runtime, 1 nhóm test chậm.
- Bỏ ~2–3 tuần công việc GRCh37 HLA; roadmap ngắn hơn.
- Giảm rủi ro sai âm thầm — loại bỏ hẳn nguồn sai không kiểm soát được.

**Tiêu cực:**
- Một số thuốc không còn kết luận được → phải nói rõ trong report, có thể ảnh hưởng
  gói sản phẩm.
- Nếu sau này bật lại, phải làm lại validation + panel map (không còn "miễn phí").
- Phải giữ field `hla` trong schema/DB để tương thích report cũ — nợ nhỏ, có chủ đích.
