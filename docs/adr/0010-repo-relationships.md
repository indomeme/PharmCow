# ADR-0010: Quan hệ repo — submodule, subtree hay wheel

- **Trạng thái:** Superseded bởi [ADR-0011](0011-rewrite-star-caller.md)
  (không còn dependency repo ngoài → không cần submodule)
- **Ngày:** 2026-10-26
- **Liên quan:** [ADR-0004](0004-repo-image-management.md),
  [ADR-0007](0007-mvp-standalone.md), [ADR-0009](0009-toolchain-uv-pixi.md)

---

## 1. Bối cảnh

PharmCOW cần code từ ba repo cũ (`mini-vcf-to-star`, `pypgx-private`,
`vgt-report-pgx`). Câu hỏi: có thể dùng repo này làm **repo con** của repo kia không?

Trả lời ngắn: **được**, nhưng hướng phụ thuộc phải theo hướng build/deploy:

> Source dependency (code) có thể là submodule.
> Deploy dependency phải là **image digest**, không phải submodule.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| R1 | `PharmCOW` là **repo gốc (top-level)**. Không đưa PharmCOW làm submodule của repo khác; repo deploy/umbrella chỉ tham chiếu **image digest** trong `manifest.yaml`. |
| R2 | Code legacy vào PharmCOW qua **`vendor/` phẳng, một tầng**: `vendor/mini-vcf-to-star`, `vendor/pypgx-private`, `vendor/vgt-report-pgx` — mỗi cái là submodule pin SHA. **Không lồng submodule trong submodule.** |
| R3 | `pypgx-private` là **submodule trực tiếp của PharmCOW**, không kế thừa từ `mini-vcf-to-star` (vì repo kia đang `.gitignore` nó). |
| R4 | Khi ổn định, chuyển Python dep sang **wheel nội bộ** (`pypgx-vn`, `mini-vcf-to-star`); submodule chỉ giữ cho thứ chưa đóng gói được. |
| R5 | CI checkout submodule bằng **deploy key/SSH**, không token trong Dockerfile; image không giữ `.git`. |
| R6 | SHA của từng submodule ghi vào `run.versions`/`manifest.json` để tái lập. |

---

## 3. Vì sao không làm ngược (PharmCOW là con của repo khác)?

- Repo umbrella (deploy/config) chỉ cần biết **image digest + refdata version** để
  promote/rollback; pin source SHA không giúp rollback runtime.
- Nếu PharmCOW là submodule của umbrella, mọi thay đổi code phải qua 2 PR (repo con +
  bump pointer), CI/CD khó, và `git clone` mặc định không kéo code.
- Image đã là artifact bất biến; dùng digest là đủ và đúng bản chất deploy.

Ngoại lệ: nếu có repo "monorepo của nhiều sản phẩm" thật sự (nhiều app dùng chung
library), có thể dùng `git subtree`/workspace thay vì submodule.

---

## 4. So sánh cơ chế

| Cách | Ưu | Nhược | Khi nào |
|---|---|---|---|
| **Submodule** (chọn MVP) | Pin SHA rõ; giữ repo upstream độc lập; không copy code | Người mới quên `--recurse-submodules`; CI cần quyền; nested rất khó | Upstream còn dùng cho hệ thống cũ |
| **Subtree** | Repo tự chứa; clone/build đơn giản; history gộp | Update upstream thủ công (`subtree pull`); repo to | Muốn self-contained, sắp bỏ upstream |
| **Vendor copy** | Đơn giản nhất; build không cần mạng | Drift; mất history; review khó | Chốt code, không theo upstream |
| **Wheel nội bộ** | Dependency chuẩn; CI sạch; version rõ | Cần private index + release process | Dep Python ổn định (pypgx, star) |
| **CI checkout đa repo** | Không submodule; linh hoạt | Không "một repo" đúng nghĩa; cấu hình CI phức tạp | Nhiều repo, ít người |

---

## 5. Layout đề xuất

```
PharmCOW/
  .gitmodules
  pipeline/
    pixi.toml            # pypgx = { path = "../vendor/pypgx-private" }
                         # mini-vcf-to-star = { path = "../vendor/mini-vcf-to-star" }
    vendor/
      mini-vcf-to-star/  # submodule, pin SHA
      pypgx-private/     # submodule, pin SHA (0.21.0+vn)
      vgt-report-pgx/    # submodule, pin SHA (code query; DB là artifact S3)
```

- Tất cả submodule ở **một tầng**, không có `.gitmodules` lồng nhau.
- Panel 1KGP **không** là submodule (quá lớn): tải theo tag `pypgx-bundle` + checksum
  ở build, hoặc copy từ cache CI.
- Guideline DB **không** là submodule: là artifact S3 versioned (ADR-0008).

---

## 6. Cạm bẫy phải xử lý

1. **Clone thiếu submodule**: dev phải `git clone --recurse-submodules` hoặc
   `git submodule update --init`; ghi trong README + Makefile/`justfile`.
2. **CI private**: deploy key phải đọc được cả 3 repo; hoặc dùng SSH agent mount
   (`--mount=type=ssh`) — không đưa token vào Dockerfile.
3. **Docker build**: submodule phải được checkout **trước** khi `docker build`; nếu
   không, `COPY vendor` sẽ thiếu file. CI: checkout → build.
4. **`.dockerignore`**: loại `**/.git` (file `.git` trong submodule) và `.pixi`,
   `.venv`, `tests/`.
5. **Pin SHA, không pin branch**: submodule tự nhiên pin commit; đừng `git submodule
   update --remote` trong CI.
6. **`pypgx-private` bị gitignore ở repo star**: đừng trông vào nó "đi kèm" khi
   submodule hóa `mini-vcf-to-star`; khai báo riêng ở PharmCOW.
7. **Không sửa code trong submodule** (sẽ tạo commit mồ côi): mọi patch phải lên repo
   gốc rồi bump pointer.
8. **Rollback**: dùng image digest, không dùng SHA submodule.

---

## 7. Lộ trình

| Giai đoạn | Cách |
|---|---|
| MVP | Submodule phẳng cho 3 repo; CI checkout + build; SHA ghi vào manifest. |
| Khi pypgx/star ổn định | Đóng gói wheel `pypgx-vn`, `mini-vcf-to-star`; bỏ submodule tương ứng. |
| Khi tách hẳn hệ thống cũ | Chuyển `mini-vcf-to-star` sang subtree/vendor trong PharmCOW, hoặc giữ wheel. |

---

## 8. Hệ quả

**Tích cực:**
- Một repo sản phẩm, upstream vẫn độc lập cho hệ thống cũ.
- Pin SHA rõ ràng, không copy code, không drift.
- Đường nâng cấp lên wheel rõ ràng.

**Tiêu cực:**
- Submodule là điểm ma sát với người mới và CI.
- Private repo cần quản lý deploy key.
- Nested submodule (nếu phát sinh) rất khó debug — cấm.
