"""
Export docs to static HTML.
Run: python -c "import sys; sys.path.insert(0,'src'); from nos.web.export_docs import main; main()"
"""
import sys
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from nos.app import create_app
from nos.web.docs_loader import load_all_docs


def main():
    app = create_app()
    with app.app_context(), app.test_request_context("/docs"):
        docs = load_all_docs()
        try:
            import importlib.metadata
            version = importlib.metadata.version("nos")
        except Exception:
            version = "0.1.0"
        html = app.jinja_env.get_template("docs/docs.html").render(
            docs=docs, version=version, app_title="nOS"
        )
        out = Path(app.static_folder) / "docs.html"
        out.write_text(html, encoding="utf-8")
    print(f"Exported {len(docs)} docs to {out}")


if __name__ == "__main__":
    main()
