import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { useAppStore } from "../store";

const SELECTED_COLOR = new THREE.Color(0xffaa00);

// IFC GUIDs are 22 chars from a 64-char alphabet. IfcConvert may prefix the
// node name with strings like "product-" or include the express id; strip and
// pull out the trailing 22-char token if present.
const GUID_RE = /([0-9A-Za-z_$]{22})(?!.*[0-9A-Za-z_$]{22})/;
function guidFromName(name: string | undefined): string | null {
  if (!name) return null;
  const m = name.match(GUID_RE);
  return m ? m[1] : null;
}

interface Props {
  glbUrl: string | null;
}

export function Viewer({ glbUrl }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const meshByGuidRef = useRef<Map<string, THREE.Mesh[]>>(new Map());
  const originalColorRef = useRef<Map<THREE.Mesh, THREE.Color>>(new Map());
  const selectedGuid = useAppStore((s) => s.selectedGuid);
  const setSelectedGuid = useAppStore((s) => s.setSelectedGuid);

  // Scene setup — one-time
  const sceneRef = useRef<{
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer;
    controls: OrbitControls;
    modelGroup: THREE.Group;
    raycaster: THREE.Raycaster;
  } | null>(null);

  useEffect(() => {
    if (!mountRef.current) return;
    const mount = mountRef.current;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x202428);

    const camera = new THREE.PerspectiveCamera(
      50,
      mount.clientWidth / mount.clientHeight,
      0.1,
      10000
    );
    camera.position.set(30, 30, 30);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(50, 100, 50);
    scene.add(dir);

    const grid = new THREE.GridHelper(100, 50, 0x444444, 0x2a2a2a);
    scene.add(grid);

    const modelGroup = new THREE.Group();
    scene.add(modelGroup);

    const raycaster = new THREE.Raycaster();

    sceneRef.current = { scene, camera, renderer, controls, modelGroup, raycaster };

    const onResize = () => {
      if (!mount) return;
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    window.addEventListener("resize", onResize);

    let frame = 0;
    const loop = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };
    loop();

    const onClick = (ev: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((ev.clientX - rect.left) / rect.width) * 2 - 1,
        -((ev.clientY - rect.top) / rect.height) * 2 + 1
      );
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(modelGroup.children, true);
      for (const h of hits) {
        let obj: THREE.Object3D | null = h.object;
        while (obj) {
          const guid = guidFromName(obj.name);
          if (guid) {
            setSelectedGuid(guid);
            return;
          }
          obj = obj.parent;
        }
      }
      setSelectedGuid(null);
    };
    renderer.domElement.addEventListener("click", onClick);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      renderer.domElement.removeEventListener("click", onClick);
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, [setSelectedGuid]);

  // Load model when URL changes
  useEffect(() => {
    if (!glbUrl || !sceneRef.current) return;
    const { scene, camera, controls, modelGroup } = sceneRef.current;

    // Clear previous
    while (modelGroup.children.length) {
      const child = modelGroup.children[0];
      modelGroup.remove(child);
      child.traverse((o) => {
        if ((o as THREE.Mesh).isMesh) {
          const m = o as THREE.Mesh;
          m.geometry.dispose();
          const mat = m.material;
          if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
          else (mat as THREE.Material).dispose();
        }
      });
    }
    meshByGuidRef.current.clear();
    originalColorRef.current.clear();

    const loader = new GLTFLoader();
    loader.load(
      glbUrl,
      (gltf) => {
        const root = gltf.scene;
        // Index meshes by GUID, clone materials so we can recolor per-element.
        root.traverse((o) => {
          if (!(o as THREE.Mesh).isMesh) return;
          const mesh = o as THREE.Mesh;
          if (Array.isArray(mesh.material)) {
            mesh.material = mesh.material.map((m) => m.clone());
          } else {
            mesh.material = (mesh.material as THREE.Material).clone();
          }
          // GUID may live on the mesh or an ancestor — search up.
          let cursor: THREE.Object3D | null = mesh;
          let guid: string | null = null;
          while (cursor && !guid) {
            guid = guidFromName(cursor.name);
            cursor = cursor.parent;
          }
          if (guid) {
            const arr = meshByGuidRef.current.get(guid) ?? [];
            arr.push(mesh);
            meshByGuidRef.current.set(guid, arr);
          }
          const mat = mesh.material as THREE.MeshStandardMaterial;
          if (mat && mat.color) {
            originalColorRef.current.set(mesh, mat.color.clone());
          }
        });
        modelGroup.add(root);

        // Fit camera
        const box = new THREE.Box3().setFromObject(root);
        const size = box.getSize(new THREE.Vector3()).length() || 50;
        const center = box.getCenter(new THREE.Vector3());
        controls.target.copy(center);
        camera.position.copy(center).add(new THREE.Vector3(size, size, size));
        camera.near = size / 1000;
        camera.far = size * 100;
        camera.updateProjectionMatrix();
        controls.update();
        void scene;
      },
      undefined,
      (err) => {
        // eslint-disable-next-line no-console
        console.error("glTF load error", err);
      }
    );
  }, [glbUrl]);

  // Apply selection highlight
  useEffect(() => {
    // Reset all
    for (const [mesh, color] of originalColorRef.current.entries()) {
      const mat = mesh.material as THREE.MeshStandardMaterial;
      if (mat && mat.color) mat.color.copy(color);
    }
    if (!selectedGuid) return;
    const meshes = meshByGuidRef.current.get(selectedGuid);
    if (!meshes) return;
    for (const mesh of meshes) {
      const mat = mesh.material as THREE.MeshStandardMaterial;
      if (mat && mat.color) mat.color.copy(SELECTED_COLOR);
    }
  }, [selectedGuid]);

  return <div ref={mountRef} style={{ width: "100%", height: "100%" }} />;
}
