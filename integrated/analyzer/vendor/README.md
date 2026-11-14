# vendor/

Third-party files shipped with the analyzer so the built page makes no network requests. Each library is the
exact version the original drop loaded from a CDN; nothing was upgraded. Approved by Daniel on 2026-11-14.

Each file was extracted from the package's official npm tarball (`registry.npmjs.org`) without running any
install scripts. Each tarball's sha512 matched the `dist.integrity` the registry publishes for that version, and
the sha256 of every file below matches the same file inside that tarball.

| Package | Version | Source tarball | File here | Bytes | sha256 |
|---|---|---|---|---|---|
| three | 0.160.0 | https://registry.npmjs.org/three/-/three-0.160.0.tgz | `three/build/three.module.js` | 1272972 | `76dea8151bc9352aef3528b4262e249b2604f62543828328db978d060d61a495` |
| three | 0.160.0 | same | `three/examples/jsm/controls/OrbitControls.js` | 29868 | `5a44a9e86a2a0fb11933eed69bc2cd33c76a496854c1aed6ed776efa87d7b064` |
| three | 0.160.0 | same | `three/LICENSE` (MIT) | 1081 | `852e0e8699169bf9f6fdc6bda3e682d078dcbc738b5d33e74df594721bff271d` |
| jspdf | 2.5.1 | https://registry.npmjs.org/jspdf/-/jspdf-2.5.1.tgz | `jspdf/jspdf.umd.min.js` (package path `dist/jspdf.umd.min.js`) | 364463 | `98ccf17aa10c20bb1301762618fcc9b6ab3a4e7f26b6071d64d0b41154df3875` |
| jspdf | 2.5.1 | same | `jspdf/LICENSE` (MIT) | 1142 | `2d26bfab8a36d2250602c7a7597237e180c5cd3517acc108126e3cb399f483c8` |
| fflate | 0.8.2 | https://registry.npmjs.org/fflate/-/fflate-0.8.2.tgz | `fflate/umd/index.js` | 32665 | `c3b34f2e9f5e74d4d7d64e01cac7a0c01954c6c406414d42185c7b53d6875ddf` |
| fflate | 0.8.2 | same | `fflate/LICENSE` (MIT) | 1069 | `805f6cb28bb8b6d3a0badd83c93bccd9671fa01a3b4b92b7042b0743325ac243` |
| rhino3dm | 8.35.0 | from the original drop (see `rhino3dm.package.json`) | `rhino3dm.min.js`, `rhino3dm.wasm` | | |

Paths inside each folder mirror the package layout, except jsPDF's file, which sits at the folder root because
the repo ignores every `dist/` folder. For three.js, `three/addons/...` in the page's import map resolves to
`three/examples/jsm/...` exactly as on the CDN. OrbitControls imports only from `three`.

jsPDF 2.5.1 has published security advisories; an upgrade needs its own decision (DEBT D-011). Its optional
helpers (html2canvas, dompurify, canvg) are not shipped and are only loaded by features the analyzer does not use.
jsPDF also contains a pdfobject CDN address used only by `output('pdfobjectnewwindow')`; the analyzer calls
`output('arraybuffer')`, so it is never requested.
