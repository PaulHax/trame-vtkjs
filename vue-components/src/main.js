import components from "./components";

export { default as VtkJsLocal } from "./components/VtkJsLocal";
export { default as VtkJsShared } from "./components/VtkJsShared";

// Publishes window.trameVtkjs.glMatrix ({ mat4, vec3 }) on load.
import "./glMatrix";

export function install(Vue) {
  Object.keys(components).forEach((name) => {
    Vue.component(name, components[name]);
  });
}
