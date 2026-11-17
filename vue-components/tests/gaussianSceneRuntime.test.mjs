import assert from "node:assert/strict";
import { after, test } from "node:test";
import { closeModuleLoader, loadModule } from "./loadModule.mjs";

after(closeModuleLoader);

test("layer appearance wrappers share the physical Gaussian renderer and release it together", async () => {
  const { createGaussianSceneRuntime } = await loadModule(
    "/src/components/gaussianSceneRuntime.js",
  );
  const { createMeshAppearanceRenderer } = await loadModule(
    "/src/components/meshAppearance.js",
  );
  const { createStreamedSceneCoordinator, createMemoryPool } = await loadModule(
    "/node_modules/tiled-vtkjs/dist/core.js",
  );
  const actors = new Set();
  const renderer = {
    addActor: (actor) => actors.add(actor),
    removeActor: (actor) => actors.delete(actor),
  };
  const first = createMeshAppearanceRenderer(renderer, () => ({
    opacity: 0.8,
  }));
  const second = createMeshAppearanceRenderer(renderer, () => ({
    opacity: 0.4,
  }));
  const memory = createMemoryPool();
  const coordinator = createStreamedSceneCoordinator({
    memory,
    scheduleRender() {},
  });
  const runtime = createGaussianSceneRuntime();
  const a = runtime.createContentAdapter(
    coordinator.context(first.renderer, 1),
  );
  const b = runtime.createContentAdapter(
    coordinator.context(second.renderer, 1),
  );
  assert.equal(runtime.stats().length, 1);
  assert.equal(actors.size, 1);
  a.dispose();
  assert.equal(actors.size, 1);
  assert.equal(runtime.stats().length, 1);
  b.dispose();
  assert.equal(actors.size, 0);
  assert.deepEqual(runtime.stats(), []);
  runtime.dispose();
  coordinator.dispose();
  assert.equal(memory.stats().owners, 0);
});
