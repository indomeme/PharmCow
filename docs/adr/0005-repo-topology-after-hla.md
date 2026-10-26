# ADR-0005: Tổ chức repo sau khi bỏ HLA — monorepo hay polyrepo?

- **Trạng thái:** Superseded bởi [ADR-0007](0007-mvp-standalone.md)
- **Ngày:** 2026-10-26
- **Ghi chú:** Quyết định polyrepo bên dưới **không còn áp dụng cho MVP** — ADR-0007
  chọn monorepo (một repo, một image). Nội dung giữ lại làm phân tích cho tương lai
  nếu phải tách pipeline/report ra.
- **Liên quan:** [ADR-0001](0001-architecture.md), [ADR-0004](0004-repo-image-management.md),
  [ADR-0006](0006-drop-hla.md)
- **Điều chỉnh:** ADR-0004 đề xuất repo `pgx-contracts` riêng; ADR này thu gọn
  contracts vào `PharmCOW` cho đến khi có consumer bên ngoài.

---

## 1. Bối cảnh

Đã chốt **bỏ HLA khỏi DAG** ([ADR-0006](0006-drop-hla.md)): runtime chỉ còn
`star_call` và report. Report sẽ được làm lại/thay thế trong tương lai gần. Câu hỏi:
có nên gộp `mini-vcf-to-star` + `vgt-report-pgx` (+ platform) vào một repo?

Hiện trạng: 3 repo pipeline độc lập (Bitbucket `tysud`), mỗi repo có `pixi.lock`,
Jenkinsfile, ECR repo riêng; platform `PharmCOW` là repo thứ 4.

Điểm dễ bị đánh giá sai: **số lượng stage không phải tiêu chí chọn repo**. Ba stage
hay hai stage không quan trọng bằng 5 tiêu chí dưới đây.

---

## 2. Tiêu chí quyết định

| Tiêu chí | Câu hỏi |
|---|---|
| C1. Toolchain | Có buộc phải cùng môi trường build/runtime không? |
| C2. Nhịp release | Có thường release cùng nhau không? |
| C3. Vòng đời | Thành phần nào sắp bị thay thế/rewrite? |
| C4. Sở hữu | Có cùng người/team chịu trách nhiệm không? |
| C5. Chi phí thay đổi | Một thay đổi xuyên suốt có cần atomic không? |

---

## 3. Quyết định

**Giữ polyrepo: 3 repo active + 1 archived.**

| Repo | Trạng thái | Image |
|---|---|---|
| `mini-vcf-to-star` | active, ổn định | `mini-vcf-to-star` (Java + pypgx + panel) |
| `vgt-report-pgx` | active, **chuyển tiếp** | `vgt-report-pgx` (pandas + guideline DB) |
| `PharmCOW` | active, thay đổi nhanh | web + worker + `contracts/` + `manifest.yaml` |
| `vgt-hla-imputation` | **archived** (không còn trong DAG) | giữ tag cũ cho pipeline legacy/PCR |

Điểm cuối (dự kiến 6–12 tháng): `vgt-report-pgx` có thể **tan vào `PharmCOW`** dưới
dạng package Python (`pgx_report`) hoặc service nội bộ, không phải gộp vào repo star.

---

## 4. Lý do

| Tiêu chí | star | report | Kết luận |
|---|---|---|---|
| C1. Toolchain | Python 3.9 + **Java** + panel 187 MB/assembly + bioconda | Python 3.9 + pandas, không Java, image nhỏ | Gần nhau nhưng star nặng gấp ~4×; gộp image làm report phải mang Java/panel vô ích |
| C2. Nhịp release | Rất thấp (đổi pypgx fork/bảng allele) | Cao (guideline DB hàng tháng) | Gộp ⇒ mỗi lần update DB phải rebuild image 1,65 GB hoặc path-filter CI |
| C3. Vòng đời | Ổn định | **Sắp bị thay thế** (ADR-0003) | Gộp report vào star sẽ trói phần sắp bị bỏ vào phần ổn định |
| C4. Sở hữu | Team pipeline | Team report/product | Hai owner khác nhau → CODEOWNERS + review khác nhau |
| C5. Thay đổi xuyên suốt | Hiếm: format CSV ổn định | Hiếm | Contract + fixture giải quyết, không cần atomic PR |

**Điểm mấu chốt:** gộp repo **không** làm interface biến mất. Star và report vẫn là
hai image riêng, vẫn phải test contract. Monorepo chỉ tiết kiệm một PR bump version —
đổi lại là CI path-filter, tag theo prefix, lịch sử git phải migrate, và mất khả năng
release/rollback độc lập. Không đáng.

**Platform càng không nên gộp:** Python 3.12 (web) vs 3.9 (pipeline), deploy service
vs job, bề mặt bảo mật khác nhau, nhịp thay đổi hàng ngày.

---

## 5. Phương án đã cân nhắc

| Phương án | Vì sao loại |
|---|---|
| **A. Một repo, một image** (star + report + web) | Xung đột Python/Java, image ~2 GB, không retry/scale riêng, không rollback riêng |
| **B. Một repo, nhiều image** (star + report chung repo) | Khả thi về kỹ thuật, nhưng C2/C3/C4 xấu; phải path-filter CI và tag prefix; lợi ích chỉ là atomic bump |
| **C. Polyrepo 3 active + 1 archived** | **Chọn** |
| **D. Polyrepo + repo `pgx-contracts` riêng** | Thêm repo cho team nhỏ; gộp contracts vào `PharmCOW` là đủ |

---

## 6. Nếu vẫn muốn gộp: làm cho đúng

Chỉ nên gộp khi **star và report thực sự release cùng nhau** và **cùng owner**. Khi đó:

```
pgx-pipelines/
  pixi.toml                 # [feature.star], [feature.report], [environments]
  pipelines/star/           # image 1
  pipelines/report/         # image 2
  contracts/                # schema + fixture dùng chung
  deploy/
```

- Tag theo prefix: `star-v1.2.0`, `report-v2.6.0` (không dùng một `v1.2.0` chung).
- CI **path filter**: đổi `pipelines/report/**` không rebuild star.
- `CODEOWNERS` theo thư mục; review độc lập.
- `pixi` multi-environment (`pixi -e star`, `pixi -e report`), không trộn dependency.
- Vẫn giữ 2 image + contract test; manifest vẫn là release lock.

Nếu không đáp ứng được 4 điều trên → không gộp.

---

## 7. Bỏ HLA thì thay đổi gì

| Hạng mục | Thay đổi |
|---|---|
| DAG | `ingest → qc → star_call → recommend → assemble → render` (bỏ `hla_condition`, `hla_call`, `merge_hla`) |
| Port | Xoá `HlaCaller`; `RecommendationEngine.recommend(star, product)` |
| `CanonicalResult` | `hla.status = "not_requested"` cố định; **giữ field** để report cũ vẫn đọc được |
| DB | Giữ cột `hla_*` (nullable) vì report version cũ tham chiếu; không xoá |
| Refdata/manifest | Bỏ `hla_model`, `hla_panel`; image HLA ra khỏi manifest |
| Product | Thuốc phụ thuộc HLA (carbamazepine, allopurinol, abacavir, phenytoin…) phải vào `not_evaluable` kèm lý do "chưa phân tích HLA", **không** biến mất khỏi report |
| ADR-0002 | Phần HLA GRCh37 **huỷ** (ADR-0006); GRCh37 cho star vẫn giữ |
| Repo HLA | Không xoá (pipeline legacy/PCR còn dùng), archive + giữ tag/image cũ |

Cảnh báo lâm sàng: bỏ HLA mà vẫn bán gói có thuốc cần HLA → phải nói rõ phạm vi, hoặc
loại các thuốc đó khỏi product config. Không được để report im lặng.

---

## 8. Khi nào xem lại quyết định

Đo trong 3–6 tháng:

- > 30% PR phải sửa **cả** star và report → cân nhắc gộp.
- Release star và report luôn đi cặp → cân nhắc gộp.
- Report trở thành thư viện Python thuần, không còn image riêng → **đưa vào PharmCOW**,
  không gộp vào star.
- Team ≤ 2 người và chi phí bump manifest > chi phí migrate → gộp.

Ngược lại, nếu report được rewrite thành service riêng có lifecycle riêng → càng phải
tách.

---

## 9. Hệ quả

**Tích cực:**
- Star ổn định không bị kéo theo thay đổi report/DB.
- Report rewrite không ảnh hưởng image star.
- Rollback/release độc lập; manifest vẫn là release lock duy nhất.
- Bỏ HLA giảm 1 image, 1 repo runtime, ~2–3 tuần công việc GRCh37 HLA.

**Tiêu cực:**
- Vẫn phải làm contract test + bump manifest khi format đổi.
- Ba pipeline repo + platform = 4 CI, 4 ECR repo (chấp nhận được).
- Nếu team quá nhỏ, chi phí vận hành polyrepo có thể lớn hơn lợi ích → xem mục 8.
