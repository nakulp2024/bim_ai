import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import type { GeometryManifest } from "./types";

/** RGBA, 0..1. Alpha below 1 renders translucent; alpha 0 hides the element. */
export type Rgba = readonly [number, number, number, number];

/**
 * The 4D scene: the whole model drawn from one set of shared vertex buffers.
 *
 * It is split across two meshes on purpose. A single mesh with per-vertex
 * alpha cannot render "ghosted future work" correctly: with depth writes on,
 * a translucent wall drawn first hides the built columns behind it. So solid
 * elements go in an opaque mesh, translucent ones in a second mesh drawn
 * afterwards without depth writes, and both share the same position, normal
 * and colour attributes. Moving an element between them only rewrites index
 * lists, and only when an element actually crosses over.
 */
export class FourDScene {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private raycaster = new THREE.Raycaster();
  private resizeObserver: ResizeObserver;
  private frame = 0;

  private manifest: GeometryManifest | null = null;
  private colors: THREE.BufferAttribute | null = null;
  private opaque: THREE.Mesh | null = null;
  private ghost: THREE.Mesh | null = null;
  private allIndices: Uint32Array = new Uint32Array(0);
  private opaqueIndex: Uint32Array = new Uint32Array(0);
  private ghostIndex: Uint32Array = new Uint32Array(0);

  /** Per element: 0 hidden, 1 opaque, 2 ghost. Used to skip needless rebuilds. */
  private membership: Uint8Array = new Uint8Array(0);
  /** Per element: the RGBA last written, to skip rewriting unchanged vertices. */
  private painted: Float32Array = new Float32Array(0);
  /** Sorted vertex starts, for mapping a picked vertex back to its element. */
  private vertexStarts: Int32Array = new Int32Array(0);

  constructor(private container: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0xf1f5f9);
    container.appendChild(this.renderer.domElement);

    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10_000);
    this.camera.position.set(40, 30, 40);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.1;

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x94a3b8, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(1, 2, 1.5);
    this.scene.add(sun);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.loop();
  }

  // --- lifecycle -------------------------------------------------------------

  load(manifest: GeometryManifest, buffer: ArrayBuffer): void {
    this.clearModel();
    this.manifest = manifest;
    const { positions, indices } = manifest.buffers;
    if (!positions.length || !indices.length) return;

    const position = new THREE.BufferAttribute(
      new Float32Array(buffer, positions.offset, positions.length),
      3,
    );
    this.allIndices = new Uint32Array(buffer, indices.offset, indices.length);

    // Normals are computed once here rather than shipped: the server sends
    // positions and indices only, a third less to download.
    const normalSource = new THREE.BufferGeometry();
    normalSource.setAttribute("position", position);
    normalSource.setIndex(new THREE.BufferAttribute(this.allIndices, 1));
    normalSource.computeVertexNormals();
    const normal = normalSource.getAttribute("normal") as THREE.BufferAttribute;

    const vertexCount = positions.length / 3;
    this.colors = new THREE.BufferAttribute(new Float32Array(vertexCount * 4), 4);
    this.colors.setUsage(THREE.DynamicDrawUsage);

    this.opaqueIndex = new Uint32Array(indices.length);
    this.ghostIndex = new Uint32Array(indices.length);

    const build = (index: Uint32Array, material: THREE.Material) => {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", position);
      geometry.setAttribute("normal", normal);
      geometry.setAttribute("color", this.colors!);
      const attribute = new THREE.BufferAttribute(index, 1);
      attribute.setUsage(THREE.DynamicDrawUsage);
      geometry.setIndex(attribute);
      geometry.setDrawRange(0, 0);
      geometry.boundingSphere = new THREE.Sphere(
        new THREE.Vector3(),
        new THREE.Vector3(...manifest.bounds.max).distanceTo(
          new THREE.Vector3(...manifest.bounds.min),
        ),
      );
      return new THREE.Mesh(geometry, material);
    };

    this.opaque = build(
      this.opaqueIndex,
      new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide }),
    );
    this.ghost = build(
      this.ghostIndex,
      new THREE.MeshLambertMaterial({
        vertexColors: true,
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
      }),
    );
    // Translucent work must draw after the solid work it sits in front of.
    this.ghost.renderOrder = 1;
    this.scene.add(this.opaque, this.ghost);

    const count = manifest.elements.length;
    this.membership = new Uint8Array(count).fill(255); // forces the first rebuild
    this.painted = new Float32Array(count * 4).fill(-1);
    this.vertexStarts = Int32Array.from(manifest.elements, (e) => e.vertex_start);
    normalSource.dispose();

    this.frameAll();
  }

  dispose(): void {
    cancelAnimationFrame(this.frame);
    this.resizeObserver.disconnect();
    this.clearModel();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  private clearModel(): void {
    for (const mesh of [this.opaque, this.ghost]) {
      if (!mesh) continue;
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
    }
    this.opaque = this.ghost = null;
    this.manifest = null;
  }

  // --- painting ----------------------------------------------------------------

  /**
   * Colour every element. ``colorOf`` is called once per element index and
   * returns RGBA; only elements whose colour changed have their vertices
   * rewritten, and the index lists are only rebuilt when an element moves
   * between solid, translucent and hidden.
   */
  paint(colorOf: (elementIndex: number) => Rgba): void {
    const manifest = this.manifest;
    const colors = this.colors;
    if (!manifest || !colors || !this.opaque || !this.ghost) return;

    const data = colors.array as Float32Array;
    let colorsDirty = false;
    let membershipDirty = false;

    manifest.elements.forEach((element, index) => {
      const [r, g, b, a] = colorOf(index);
      const slot = index * 4;
      if (
        this.painted[slot] !== r ||
        this.painted[slot + 1] !== g ||
        this.painted[slot + 2] !== b ||
        this.painted[slot + 3] !== a
      ) {
        this.painted.set([r, g, b, a], slot);
        const start = element.vertex_start * 4;
        const end = start + element.vertex_count * 4;
        for (let i = start; i < end; i += 4) {
          data[i] = r;
          data[i + 1] = g;
          data[i + 2] = b;
          data[i + 3] = a;
        }
        colorsDirty = true;
      }
      const group = a <= 0 ? 0 : a >= 1 ? 1 : 2;
      if (this.membership[index] !== group) {
        this.membership[index] = group;
        membershipDirty = true;
      }
    });

    if (colorsDirty) colors.needsUpdate = true;
    if (membershipDirty) this.rebuildIndices();
  }

  private rebuildIndices(): void {
    const manifest = this.manifest!;
    let opaqueCount = 0;
    let ghostCount = 0;
    manifest.elements.forEach((element, index) => {
      const group = this.membership[index];
      if (group === 0) return;
      const slice = this.allIndices.subarray(
        element.index_start,
        element.index_start + element.index_count,
      );
      if (group === 1) {
        this.opaqueIndex.set(slice, opaqueCount);
        opaqueCount += slice.length;
      } else {
        this.ghostIndex.set(slice, ghostCount);
        ghostCount += slice.length;
      }
    });
    for (const [mesh, count] of [
      [this.opaque!, opaqueCount],
      [this.ghost!, ghostCount],
    ] as const) {
      const index = mesh.geometry.getIndex()!;
      index.needsUpdate = true;
      // Upload only the populated range rather than the whole array.
      index.clearUpdateRanges();
      index.addUpdateRange(0, count);
      mesh.geometry.setDrawRange(0, count);
    }
  }

  // --- interaction -----------------------------------------------------------------

  /** Element index under a pointer event, or null. */
  pick(event: { clientX: number; clientY: number }): number | null {
    if (!this.opaque || !this.ghost) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(pointer, this.camera);
    // Solid work first: clicking through a ghost onto a built column should
    // select the column.
    for (const mesh of [this.opaque, this.ghost]) {
      const hit = this.raycaster.intersectObject(mesh, false)[0];
      if (hit?.face) return this.elementForVertex(hit.face.a);
    }
    return null;
  }

  private elementForVertex(vertex: number): number | null {
    let low = 0;
    let high = this.vertexStarts.length - 1;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (this.vertexStarts[middle] <= vertex) low = middle + 1;
      else high = middle - 1;
    }
    return high >= 0 ? high : null;
  }

  frameAll(): void {
    if (!this.manifest) return;
    this.frameBox(this.manifest.bounds.min, this.manifest.bounds.max);
  }

  frameElement(index: number): void {
    const element = this.manifest?.elements[index];
    if (element) this.frameBox(element.bbox.min, element.bbox.max, 2.2);
  }

  private frameBox(
    min: readonly [number, number, number],
    max: readonly [number, number, number],
    padding = 1.0,
  ): void {
    const box = new THREE.Box3(new THREE.Vector3(...min), new THREE.Vector3(...max));
    const centre = box.getCenter(new THREE.Vector3());
    const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.5);
    // Fit against whichever field of view is narrower; in a wide viewport
    // that is the vertical one, in a tall one the horizontal.
    const vertical = (this.camera.fov * Math.PI) / 180;
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * this.camera.aspect);
    const distance = (radius * padding) / Math.sin(Math.min(vertical, horizontal) / 2);
    // A three-quarter view from the south-east reads best for buildings.
    const direction = new THREE.Vector3(1, 0.75, 1).normalize();
    this.camera.position.copy(centre).addScaledVector(direction, distance);
    this.camera.near = Math.max(distance / 1000, 0.01);
    this.camera.far = distance * 100;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(centre);
    this.controls.update();
  }

  // --- rendering -------------------------------------------------------------------

  private resize(): void {
    const { clientWidth: width, clientHeight: height } = this.container;
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  private loop = (): void => {
    this.frame = requestAnimationFrame(this.loop);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };
}
