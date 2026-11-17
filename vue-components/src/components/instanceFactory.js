// Builds the vtk.js instance for a node's wire type. Synthetic types are named
// here so their wire identity cannot drift from the class they instantiate;
// every other type is a stock vtk.js class in vtk.js's own type table.
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkPointSpriteMapper from "@kitware/vtk.js/Rendering/Core/PointSpriteMapper";
import vtkObjectManager from "@kitware/vtk.js/Rendering/Misc/SynchronizableRenderWindow/ObjectManager";

import { newInstance as newProjectedTextureMapper } from "./projectedTextureMapper";

const SYNTHETIC_FACTORIES = Object.freeze({
  vtkStreamedSceneActor: vtkActor.newInstance,
  vtkProjectedTextureMapper: newProjectedTextureMapper,
  // The Python wire contract admits only simple points for this native VTK
  // mapper. Its CSS sizing belongs to PointSpriteMapper; tile splats construct
  // the separate anisotropic Gaussian mapper through their content adapter.
  vtkPointGaussianMapper: vtkPointSpriteMapper.newInstance,
});

export function buildInstance(type) {
  const factory = SYNTHETIC_FACTORIES[type];
  return factory ? factory() : (vtkObjectManager.build(type) ?? null);
}
