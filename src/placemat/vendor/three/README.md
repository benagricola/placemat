three.js 0.186.1 (MIT, `LICENSE` beside it), vendored for the studio's 3D view (`studio_3d.js`); served from `/3d/lib/<token>/`, loaded only when 3D is opened.

- `OrbitControls.js`: `examples/jsm/controls/OrbitControls.js`, unchanged.
- `three.module.min.js`, `three.core.min.js`: made from the package's `build/three.module.js` and `build/three.core.js` (the release ships no minified
  build) with `esbuild --minify --format=esm --legal-comments=inline`, after changing the module's import of `./three.core.js` to `./three.core.min.js`.
  The `@license` comment is kept in each.

To update: take the new release from npm, redo the two steps above, keep the licence file.
