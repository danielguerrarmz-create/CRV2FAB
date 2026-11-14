"""Build dist/ : inline src/core.js + src/billet.js + src/helpers.js into src/page.html and copy the rhino3dm runtime."""
import pathlib, shutil
root = pathlib.Path(__file__).parent
page = (root / "src/page.html").read_text(encoding="utf-8")
core = "\n".join((root / "src" / f).read_text(encoding="utf-8") for f in ("core.js", "billet.js", "helpers.js"))
dist = root / "dist"; dist.mkdir(exist_ok=True)
(dist / "index.html").write_text(page.replace("/*__CORE__*/", core), encoding="utf-8")
for f in ("rhino3dm.min.js", "rhino3dm.wasm"):
    shutil.copy(root / "vendor" / f, dist / f)
print("built", dist / "index.html")
