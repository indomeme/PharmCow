# ADR-0009: Toolchain — uv cho app, pixi cho pipeline

- **Trạng thái:** Superseded bởi [ADR-0011](0011-rewrite-star-caller.md)
  (không còn pipeline env Python 3.9 → chỉ dùng `uv`)
- **Ngày:** 2026-10-26
- **Liên quan:** [ADR-0001](0001-architecture.md), [ADR-0004](0004-repo-image-management.md),
  [ADR-0008](0008-pipeline-service.md)

---

## 1. Bối cảnh

Câu hỏi: tại sao vừa `uv` vừa `pixi`? Có phải mỗi image phải cài cả hai?

**Không.** Sau khi tách pipeline (ADR-0008), mỗi image có đúng **một** toolchain:

| Image | Tool | Python | Nguồn package |
|---|---|---|---|
| `pharmcow` (api + worker) | **uv** | 3.12 | PyPI |
| `pharmcow-pipeline` (qc/star/recommend) | **pixi** | 3.9 | conda-forge + bioconda + PyPI path deps |

`uv`/`pixi` là **build-time**. Runtime image chỉ chứa `.venv` (app) hoặc
`.pixi/envs/default` (pipeline), không cần binary `uv`/`pixi` để chạy.

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| T1 | App image dùng **uv** (`uv sync --frozen`), lock `uv.lock`. |
| T2 | Pipeline image dùng **pixi** (`pixi install --frozen`), lock `pixi.lock`. |
| T3 | Không image nào cài cả hai; không trộn lock. |
| T4 | Runtime không phụ thuộc `uv`/`pixi`; entrypoint là `pharmcow` / `pipeline`. |
| T5 | Dev: app `uv sync` (giây); pipeline `pixi install` (phút). Không cần conda cho người chỉ sửa app. |
| T6 | CI: hai job build độc lập, mỗi job chỉ cài một tool. |

---

## 3. Vì sao không dùng một tool cho cả hai?

### 3.1 Vì sao pipeline cần pixi (không dùng uv)

- Cần **binary không phải Python**: `bcftools` (và htslib), Java (có thể qua apt), cùng
  các package bioconda.
- `pypgx` + `fuc` kéo `pyranges`, `sorted_nearest`, `ncls`, `pysam`, `biopython` —
  stack đã được **validate bằng `pixi.lock`** trong `mini-vcf-to-star`
  (`Dockerfile.v2` đang chạy production). Đổi sang uv = revalidate toàn bộ,
  không có lợi ích tương xứng.
- Cần pin Python 3.9 + `pandas==1.1.5` (pypgx fork); conda solve ổn định cho ràng buộc
  này, và `pixi.lock` đã có sẵn.
- `pixi` hỗ trợ `pypi-dependencies` cho path dep `pypgx-private` và `mini-vcf-to-star`.

### 3.2 Vì sao app dùng uv (không dùng pixi)

- Toàn bộ dependency là PyPI wheels (FastAPI, SQLAlchemy, asyncpg, WeasyPrint,
  Jinja2); không cần conda/bioconda.
- `uv sync` nhanh hơn solve conda; dev loop tốt hơn; `uv.lock` gọn.
- Không kéo theo conda/mamba vào image app (nhỏ, ít CVE).

### 3.3 Có thể dùng pixi cho cả hai không?

Có — pixi quản lý được cả PyPI. Khi đó chỉ còn một tool/lock, nhưng:
- app dev chậm hơn (solve/lock của pixi, tải conda metadata);
- image app phải cài pixi (hoặc multi-stage copy env) dù không cần conda;
- mất lợi thế `uv` cho team web.

### 3.4 Có thể dùng uv cho cả hai không?

Chỉ khi pipeline không còn cần binary bioconda: `bcftools`/Java cài bằng apt, toàn bộ
Python deps có wheel py3.9 tương thích. Hiện `pypgx`/`fuc`/`pysam` chưa được validate
theo hướng đó → **không làm ở MVP**.

---

## 4. Hệ quả

**Tích cực:**
- Mỗi image một tool, một lock, một CI job → dễ debug, image nhỏ.
- App image không có conda; pipeline image không có uv.
- Người chỉ làm web không cần cài pixi/conda.

**Tiêu cực:**
- Repo có hai lock file (`uv.lock`, `pipeline/pixi.lock`) → phải bump đúng chỗ.
- Hai "ngôn ngữ" build trong một repo; onboarding cần đọc ADR này.
- Nếu sau này muốn một tool duy nhất, phải chọn pixi-cho-tất-cả (khả thi) và chấp
  nhận dev chậm hơn — hoặc chứng minh pipeline chạy được thuần PyPI.

---

## 5. Ghi chú triển khai

- Dockerfile app: copy `uv` từ image chính thức, `uv sync --frozen`; có thể dùng
  multi-stage để runtime không chứa `uv`.
- Dockerfile pipeline: copy `pixi` từ image chính thức, `pixi install --frozen`;
  runtime chỉ cần `.pixi/envs/default` trên `PATH`.
- Không commit `.venv`/`.pixi`; `.dockerignore` loại cả hai.
