// Three.js 3D 照片檢視器：載入後端回傳的 .glb，以「滑鼠位置驅動的受限視差」
// 呈現 Facebook 3D Photo 式手感——相機固定在影像正前方中央，僅隨游標做小幅
// 平移 + 輕微 lookAt 偏移，不繞球、不旋到側面（側面為 2.5D 無資料區，會露餡）。
// 渲染與互動全在瀏覽器 WebGL 完成，後端不參與視角更新。
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

export class Viewer {
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private renderer: THREE.WebGLRenderer;
  private current: THREE.Object3D | null = null;
  private loader = new GLTFLoader();

  // 視差狀態：游標正規化座標 [-1,1]，與其平滑後的值（damping）。
  private pointer = new THREE.Vector2(0, 0);     // 目標
  private smoothed = new THREE.Vector2(0, 0);    // 當前（lerp 趨近 pointer）
  private readonly damping = 0.08;

  // 視差幅度（依模型尺寸自適應，frameObject 設定）。
  private baseDistance = 6;     // 相機到中心的基準距離
  private panAmount = 0;        // 最大平移量（相機 X/Y 偏移）
  private readonly maxTiltDeg = 6;   // lookAt 目標偏移對應的最大視角（度）
  private target = new THREE.Vector3(0, 0, 0);   // 物體中心（lookAt 基準）
  private tiltOffset = 0;       // lookAt 目標的最大橫向偏移（依尺寸）

  constructor(container: HTMLElement) {
    const w = container.clientWidth;
    const h = container.clientHeight;

    this.scene.background = new THREE.Color(0x12151b);

    this.camera = new THREE.PerspectiveCamera(50, w / h, 0.01, 1000);
    this.camera.position.set(0, 0, this.baseDistance);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(this.renderer.domElement);

    // 光照：環境光 + 主方向光，讓網格法線呈現立體感
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(1, 1, 2);
    this.scene.add(dir);

    // 滑鼠位置 → 視差目標（正規化到 [-1,1]，中心為 0）。
    const el = this.renderer.domElement;
    el.addEventListener("pointermove", (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const ny = ((e.clientY - rect.top) / rect.height) * 2 - 1;
      this.pointer.set(nx, ny);
    });
    // 游標離開 → 平滑滑回正面（目標歸零）。
    el.addEventListener("pointerleave", () => this.pointer.set(0, 0));

    window.addEventListener("resize", () => this.onResize(container));
    this.animate();
  }

  /** 載入 .glb（ArrayBuffer），替換場景中現有模型並重新置中相機。 */
  async loadGlb(glb: ArrayBuffer): Promise<void> {
    const gltf = await this.loader.parseAsync(glb, "");
    const model = gltf.scene;

    // 頂點色需明確啟用，並用對光照有反應的材質
    model.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.isMesh) {
        mesh.material = new THREE.MeshStandardMaterial({
          vertexColors: true,
          roughness: 0.95,
          metalness: 0.0,
          side: THREE.DoubleSide,
        });
      }
    });

    if (this.current) this.scene.remove(this.current);
    this.current = model;
    this.scene.add(model);

    this.frameObject(model);
  }

  /**
   * 把相機置於影像正前方中央，並依模型尺寸設定視差幅度。
   * 不同於繞球：相機看向 center，只在 X/Y 做小幅平移做出 parallax。
   */
  private frameObject(obj: THREE.Object3D): void {
    const box = new THREE.Box3().setFromObject(obj);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());

    const maxDim = Math.max(size.x, size.y, size.z);
    const fov = (this.camera.fov * Math.PI) / 180;
    // 距離略放大，讓整張照片落在視野內、邊緣不出框。
    this.baseDistance = (maxDim / 2) / Math.tan(fov / 2) * 1.4;

    // 視差幅度：相機平移與 lookAt 偏移皆取模型尺寸的一小部分，
    // 確保大小不同的照片視差強度一致、且不會繞到看見側面破洞。
    this.panAmount = maxDim * 0.06;
    this.tiltOffset = maxDim * 0.04;

    this.target.copy(center);
    this.camera.position.set(center.x, center.y, center.z + this.baseDistance);
    this.camera.near = this.baseDistance / 100;
    this.camera.far = this.baseDistance * 100;
    this.camera.lookAt(this.target);
    this.camera.updateProjectionMatrix();
  }

  private onResize(container: HTMLElement): void {
    const w = container.clientWidth;
    const h = container.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  /** 套用視差：相機隨平滑後游標做小幅平移 + 輕微 lookAt 偏移。 */
  private applyParallax(): void {
    // damping：smoothed 緩慢趨近 pointer（離開時 pointer=0 → 滑回正面）。
    this.smoothed.lerp(this.pointer, this.damping);

    const px = this.smoothed.x;
    const py = this.smoothed.y;

    // 相機在影像平面上小幅平移（左右 / 上下；上下取負讓游標往上→看到更上方）。
    this.camera.position.set(
      this.target.x + px * this.panAmount,
      this.target.y - py * this.panAmount,
      this.target.z + this.baseDistance,
    );

    // lookAt 目標反向小幅偏移，形成輕微 tilt（視差深度感），上限受 maxTiltDeg 暗示。
    const k = Math.tan((this.maxTiltDeg * Math.PI) / 180);
    const look = new THREE.Vector3(
      this.target.x - px * this.tiltOffset * k * 10,
      this.target.y + py * this.tiltOffset * k * 10,
      this.target.z,
    );
    this.camera.lookAt(look);
  }

  private animate = (): void => {
    requestAnimationFrame(this.animate);
    if (this.current) this.applyParallax();
    this.renderer.render(this.scene, this.camera);
  };
}
