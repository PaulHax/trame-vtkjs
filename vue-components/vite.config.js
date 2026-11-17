import { copyFileSync, mkdirSync } from "node:fs";
import { build } from "vite";
import { createRequire } from "node:module";
import { resolve } from "node:path";

import { glMatrixDir, vtkJsDir } from "./scripts/glMatrixDir.mjs";

const require = createRequire(import.meta.url);
const tiles3dWorkerSource = require.resolve(
  "tiled-vtkjs/tiles3d/decode-worker",
);

const gaussianSortWorkerSource = require.resolve(
  "tiled-vtkjs/tiles3d/gaussian-sort-worker",
);

const tiles3dCodecSources = new Map(
  [
    "draco_wasm_wrapper.js",
    "draco_decoder.wasm",
    "basis_encoder.js",
    "basis_encoder.wasm",
  ].map((name) => [
    name,
    require.resolve(`tiled-vtkjs/tiles3d/codecs/${name}`),
  ]),
);

const stageTiles3dRuntime = {
  name: "stage-tiles3d-runtime",
  async writeBundle(outputOptions) {
    copyFileSync(
      tiles3dWorkerSource,
      resolve(outputOptions.dir, "tiles3dDecodeWorker.classic.js"),
    );
    // The library worker imports hashed shared chunks. Bundle its graph into
    // one served module so copying the entry cannot leave missing imports.
    await build({
      configFile: false,
      build: {
        outDir: outputOptions.dir,
        emptyOutDir: false,
        lib: {
          entry: gaussianSortWorkerSource,
          formats: ["es"],
          fileName: () => "gaussianSortWorker.js",
        },
        rollupOptions: { output: { inlineDynamicImports: true } },
      },
    });
    const codecDirectory = resolve(outputOptions.dir, "../wasm/tiles3d");
    mkdirSync(codecDirectory, { recursive: true });
    for (const [name, source] of tiles3dCodecSources) {
      copyFileSync(source, resolve(codecDirectory, name));
    }
  },
};

export default {
  base: "./",
  plugins: [stageTiles3dRuntime],
  // Resolve the bare "gl-matrix" specifier (used by src/glMatrix.js and vtk.js
  // itself) to the single copy vtk.js depends on. Dedupe @kitware/vtk.js so
  // tiled-vtkjs adapters and linked packages resolve the pinned fork at
  // node_modules/@kitware/vtk.js.
  resolve: {
    alias: {
      "gl-matrix": glMatrixDir,
      "@kitware/vtk.js": vtkJsDir,
    },
    dedupe: ["@kitware/vtk.js"],
  },
  ssr: {
    noExternal: ["tiled-vtkjs"],
  },
  build: {
    lib: {
      entry: "./src/main.js",
      name: "trame_vtkjs",
      formats: ["umd"],
      fileName: "trame_vtkjs",
    },
    rollupOptions: {
      external: ["vue"],
      output: {
        globals: {
          vue: "Vue",
        },
      },
    },
    outDir: "../src/trame_vtkjs/module/serve/js",
    assetsDir: ".",
  },
};
