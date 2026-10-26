from __future__ import annotations

import argparse
import shutil
import sys

from pharmcow import __version__


def _selftest(require_star: bool = False) -> int:
    ok = True
    print(f"pharmcow {__version__}")
    try:
        from importlib.metadata import version as pkg_version

        import pypgx

        print(f"pypgx {pkg_version('pypgx')}")
        rec = pypgx.load_recommendation_table()
        cpic = pypgx.load_cpic_table()
        print(f"recommendation rows: {len(rec)}; cpic rows: {len(cpic)}")
    except Exception as exc:  # noqa: BLE001
        print(f"pypgx: NOT AVAILABLE ({exc})")
        print("  install with: uv sync --extra star")
        ok = False if require_star else ok

    bcf = shutil.which("bcftools")
    print(f"bcftools: {bcf or 'NOT FOUND (sampled QC fallback)'}")

    try:
        import weasyprint

        print(f"weasyprint: {weasyprint.__version__}")
    except Exception as exc:  # noqa: BLE001
        print(f"weasyprint: NOT AVAILABLE ({exc}) — HTML still works")

    from pharmcow.settings import settings

    print(f"data dir: {settings.data_dir.resolve()}")
    return 0 if ok else 1


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "pharmcow.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pharmcow", description="Personal PGx report generator")
    parser.add_argument("--version", action="version", version=f"pharmcow {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    st = sub.add_parser("selftest", help="check dependencies and data")
    st.add_argument("--require-star", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    if args.command == "selftest":
        return _selftest(require_star=args.require_star)
    return 1


if __name__ == "__main__":
    sys.exit(main())
