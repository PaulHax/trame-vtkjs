// One Gaussian realization and alpha pass per view, shared by its tile members.
import vtkForwardPass from "@kitware/vtk.js/Rendering/OpenGL/ForwardPass";
import {
  createGaussianAlphaPass,
  createGaussianContentAdapterFactory,
} from "tiled-vtkjs/tiles3d/vtk";
import { createGaussianSortWorkerBackend } from "tiled-vtkjs/tiles3d";

export function createGaussianSceneRuntime(options = {}) {
  const factory = createGaussianContentAdapterFactory({
    resourceBudgetBytes: options.resourceBudgetBytes,
    createSortBackend: () => {
      let backend = null;
      let disposed = false;
      return {
        sort(job) {
          if (disposed)
            return Promise.reject(
              new DOMException("Sort disposed", "AbortError"),
            );
          backend ??= createGaussianSortWorkerBackend(
            new Worker("/__trame_vtkjs/js/gaussianSortWorker.js", {
              type: "module",
            }),
          );
          return backend.sort(job);
        },
        dispose() {
          disposed = true;
          backend?.dispose();
          backend = null;
        },
      };
    },
  });
  const renderers = new Map();
  let window = null;
  let originalPasses = null;
  let alphaPass = null;
  let forwardPass = null;
  let active = false;

  function restore() {
    if (active && !window?.isDeleted?.())
      window?.setRenderPasses?.(originalPasses);
    active = false;
  }

  return {
    createContentAdapter(adapterOptions) {
      const renderer =
        adapterOptions.renderer.realizationRenderer ?? adapterOptions.renderer;
      const adapter = factory({
        ...adapterOptions,
        realizationRenderer: renderer,
      });
      renderers.set(renderer, (renderers.get(renderer) ?? 0) + 1);
      let disposed = false;
      return {
        ...adapter,
        dispose() {
          if (disposed) return;
          disposed = true;
          adapter.dispose();
          const count = renderers.get(renderer) - 1;
          if (count) renderers.set(renderer, count);
          else renderers.delete(renderer);
        },
      };
    },
    beforeRender(nextWindow, currentRenderers) {
      if (nextWindow !== window) {
        restore();
        forwardPass?.delete();
        alphaPass?.delete();
        forwardPass = null;
        alphaPass = null;
        window = nextWindow;
        originalPasses = window?.getRenderPasses?.() ?? [];
      }
      const needed = currentRenderers.some(
        (renderer) => (factory.stats(renderer)?.displayedSplats ?? 0) > 0,
      );
      if (!needed || !window?.setRenderPasses) {
        restore();
        return;
      }
      if (!forwardPass) {
        alphaPass = createGaussianAlphaPass(() => window.getContext());
        forwardPass = vtkForwardPass.newInstance({
          translucentPass: alphaPass,
        });
      }
      if (!active) {
        window.setRenderPasses([forwardPass]);
        active = true;
      }
    },
    stats() {
      return [...renderers.keys()]
        .map((renderer) => factory.stats(renderer))
        .filter(Boolean);
    },
    dispose() {
      restore();
      for (const renderer of renderers.keys()) factory.dispose(renderer);
      renderers.clear();
      forwardPass?.delete();
      alphaPass?.delete();
      forwardPass = null;
      alphaPass = null;
      window = null;
    },
  };
}
