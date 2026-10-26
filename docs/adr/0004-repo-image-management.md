# ADR-0004: Quản lý image & version trong monorepo

- **Trạng thái:** Superseded bởi [ADR-0013](0013-personal-project.md)
  (một image duy nhất cho dự án cá nhân)
- **Ngày:** 2026-10-26
- **Liên quan:** [ADR-0001](0001-architecture.md), [ADR-0012](0012-use-public-pypgx.md)

---

## 1. Bối cảnh

Một repo, **hai image** (app và pipeline), **một `uv.lock`**, cùng Python 3.12. Khác
biệt duy nhất là pipeline cài thêm extra `star` (pypgx/fuc/scikit-learn) + `bcftools`.
Không còn Java/pixi/submodule.

| Vấn đề cũ | Trạng thái mới |
|---|---|
| Không tag/release | Bắt buộc tag từ P0 |
| Tag image mutable | Chỉ `sha-<7>` + `vX.Y.Z`, immutable |
| Credential trong Dockerfile | Không còn Dockerfile legacy trong repo mới |
| Dep ngoài VCS | Không submodule/vendor; pypgx từ PyPI |
| Context phình | `.dockerignore` loại `.git`, `.venv`, `tests/`, `refdata` |
| Version đọc runtime | `ARG VERSION` + OCI labels |

---

## 2. Quyết định

| # | Quyết định |
|---|---|
| M1 | **Một repo, một version (`0.x.y`), hai image**: `pharmcow` (app) + `pharmcow-pipeline` (`--extra star`). |
| M2 | **Một toolchain** `uv` + Python 3.12; không pixi/conda/Java. |
| M3 | **Tag bất biến cả hai image**: `sha-<7>` mọi build; `vX.Y.Z` cho release; promote bằng **digest**. |
| M4 | **Build một lần**, promote dev → staging → prod; không rebuild. |
| M5 | **Refdata là artifact** (`pgx-refdata-{version}.tar.zst` + sha) — không bake. |
| M6 | **Không credential trong Dockerfile/ảnh**; không `git clone` lúc build. |
| M7 | Image tự mô tả: `pharmcow --version`, `pharmcow selftest`, OCI labels, SBOM. |
| M8 | `manifest.yaml` ghi **hai digest + refdata version/sha**. |
| M9 | pypgx pin **0.27.0**; `fuc`/`scikit-learn` pin qua `uv.lock`. |

---

## 3. Versioning

```
pharmcow:sha-1a2b3c4            pharmcow-pipeline:sha-1a2b3c4
pharmcow:v0.1.0                 pharmcow-pipeline:v0.1.0
```

- Bật **immutable tags** trên ECR; `sha-*` 90 ngày, `v*` vĩnh viễn.
- Hai image **luôn cùng version**; CI chặn nếu tag lệch.
- Bump: MAJOR khi đổi `CanonicalResult`/`star.csv` contract; MINOR khi thêm
  gene/product, đổi pypgx/refdata (kết quả có thể đổi); PATCH cho bugfix/deps.
- `run.versions` + `work/manifest.json`: image, pypgx, contract, assembly, refdata
  version+sha, template.

---

## 4. Build

### 4.1 App image (`deploy/Dockerfile.app`)

```dockerfile
FROM ubuntu:24.04@sha256:<pin>
ARG GIT_SHA=unknown VERSION=0.0.0
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates tini libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
      libgdk-pixbuf-2.0-0 shared-mime-info fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY --from=ghcr.io/astral-sh/uv:0.5.13 /uv /usr/local/bin/uv
RUN uv sync --frozen --no-dev            # core: không pypgx
ENV PATH=/app/.venv/bin:$PATH VGT_VERSION=$VERSION VGT_GIT_SHA=$GIT_SHA
USER 10001
ENTRYPOINT ["tini","--"]
CMD ["pharmcow","api"]
```

### 4.2 Pipeline image (`pipeline/Dockerfile`)

```dockerfile
FROM ubuntu:24.04@sha256:<pin>
ARG GIT_SHA=unknown VERSION=0.0.0
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates tini bcftools \
    && rm -rf /var/lib/apt/lists/*
# bcftools: QC missing + phase check. KHÔNG Java: QC chặn unphased trước pypgx.

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY --from=ghcr.io/astral-sh/uv:0.5.13 /uv /usr/local/bin/uv
RUN uv sync --frozen --no-dev --extra star
ENV PATH=/app/.venv/bin:$PATH VGT_VERSION=$VERSION VGT_GIT_SHA=$GIT_SHA
USER 10001
ENTRYPOINT ["tini","--"]
CMD ["pharmcow","worker","--role","pipeline"]
```

- `pypgx`/`fuc`/`scikit-learn` từ PyPI, pin qua `uv.lock`; không conda.
- Không bake refdata; tải artifact theo version khi start.
- `.dockerignore`: `.git`, `.venv`, `.pytest_cache`, `tests/`, `docs/`, `refdata/`.

---

## 5. CI/CD

```
commit main → lint + unit + contract
   → build app + pipeline (sha-<7>)
   → smoke: pharmcow --version; pipeline selftest; fixture 1 sample
   → validation harness (diff vs production) — gate
   → SBOM/trivy
   → push sha-<7> (cả hai)
        └─ release: tag vX.Y.Z → push vX.Y.Z + cập nhật manifest
             └─ deploy staging (digest) → VCF thật, golden
                  └─ deploy prod (cùng digest)
```

- Rollback = deploy digest cũ của **cả hai** image + refdata version cũ.
- Không build từ working copy; không `:latest` cho prod.

---

## 6. Refdata

```
refdata/{guideline,derived,manifest.json}
→ tar.zst → s3://pharmcow-refdata/pgx-refdata-{version}.tar.zst
```

- CI riêng validate row counts, sha, diff guideline.
- App/pipeline tải theo version trong manifest; verify sha trước load.
- Đổi guideline chỉ bump refdata version, không rebuild image.

---

## 7. Repo legacy

| Việc | Lý do |
|---|---|
| **Rotate** token Bitbucket trong 2 Dockerfile cũ | đã lộ trong layer history + git |
| Tag commit legacy đang chạy | mốc tái lập cho hệ thống cũ |
| Archive `vgt-hla-imputation` | ADR-0006 |
| Không xoá image/tag cũ | hệ thống cũ còn dùng |

---

## 8. Hệ quả

**Tích cực:**
- Một lock/version, hai image rõ vai trò; app không mang pypgx.
- Không Java/pixi/conda; build nhanh.
- Refdata update không rebuild image.

**Tiêu cực / rủi ro:**
- Hai ECR repo + hai build; CI lâu hơn một chút.
- Pipeline image ~1 GB (scikit-learn/matplotlib từ `fuc`).
- Validation harness là gate bắt buộc, tốn công.
- Nếu sau này cần unphased/CNV → thêm dependency/binary, phải cân nhắc lại image.
