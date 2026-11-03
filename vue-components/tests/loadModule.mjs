import { createServer } from "vite";

import { glMatrixDir, vtkJsDir } from "../scripts/glMatrixDir.mjs";

let viteServer = null;

export async function loadModule(modulePath) {
  if (!viteServer) {
    viteServer = await createServer({
      configFile: false,
      root: process.cwd(),
      // Match vite.config.js so a bare "gl-matrix" import resolves to vtk.js's
      // copy under ssrLoadModule too, and tiled-vtkjs adapters resolve this
      // package's pinned vtk.js build.
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
      server: {
        middlewareMode: true,
        hmr: false,
      },
      appType: "custom",
    });
  }

  return viteServer.ssrLoadModule(modulePath);
}

export async function closeModuleLoader() {
  if (viteServer) {
    await viteServer.close();
    viteServer = null;
  }
}
