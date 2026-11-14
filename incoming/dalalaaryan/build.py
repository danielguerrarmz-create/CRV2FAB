"""Build dist/ : inline src/core.js + src/billet.js into src/page.html and copy the rhino3dm runtime."""
import pathlib, shutil
root = pathlib.Path(__file__).parent
page = (root / "src/page.html").read_text()
core = (root / "src/core.js").read_text() + "\n" + (root / "src/billet.js").read_text()
dist = root / "dist"; dist.mkdir(exist_ok=True)
(dist / "index.html").write_text(page.replace("/*__CORE__*/", core))
for f in ("rhino3dm.min.js", "rhino3dm.wasm"):
    shutil.copy(root / "vendor" / f, dist / f)
print("built", dist / "index.html")
