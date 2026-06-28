// Three.js 3D 照片檢視器（mesh / 進階匯出路徑）。
// ───────────────────────────────────────────────────────────────────────
// 兩種視角，與視差模式手感對齊：
//  1) FB 3D Photo 視差（預設）：拖曳驅動，相機只在影像平面做小幅平移 + 輕微
//     lookAt 偏移，正面身歷其境、不繞到側面（側面為 2.5D 無資料區會露餡）。
//     按住拖才動、放開平滑回正——與 ParallaxViewer 一致。
//  2) 自由 Orbit（可選）：OrbitControls 自由旋轉/縮放，看真實 3D 結構（會看見
//     側面破洞，屬進階觀察用途）。
// 渲染與互動全在瀏覽器 WebGL 完成，後端不參與視角更新。
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export class Viewer {
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private renderer: THREE.WebGLRenderer;
  private current: THREE.Object3D | null = null;
  private loader = new GLTFLoader();

  // 視差幅度（依模型尺寸自適應，frameObject 設定）。
  private baseDistance = 6;          // 相機到中心的基準距離
  private panAmount = 0;             // 最大平移量（相機 X/Y 偏移）
  private readonly maxTiltDeg = 8;   // lookAt 目標偏移對應的最大視角（度）
  private target = new THREE.Vector3(0, 0, 0);   // 物體中心（lookAt 基準）
  private tiltOffset = 0;            // lookAt 目標的最大橫向偏移（依尺寸）

  // 拖曳狀態（與 ParallaxViewer 對齊）：目標位移 [-1,1]、其平滑值。
  private dragging = false;
  private dragStart = new THREE.Vector2();
  private dragTarget = new THREE.Vector2(0, 0);   // 拖曳量（放開歸零）
  private smoothed = new THREE.Vector2(0, 0);
  private readonly damping = 0.18;     // 放開回正阻尼（僅非拖曳時生效）
  private readonly dragScale = 3.5;    // 拖曳靈敏度（與視差模式一致）

  // 視角模式：false = FB 3D Photo 視差（預設），true = 自由 Orbit。
  private orbitMode = false;
  private controls: OrbitControls;

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

    // OrbitControls：預設停用（FB 視差模式接管互動），切到 orbit 才啟用。
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enabled = false;

    // 拖曳互動（FB 視差模式）：按住拖才動、放開回正——與 ParallaxViewer 同手感。
    const el = this.renderer.domElement;
    el.style.cursor = "grab";
    el.addEventListener("pointerdown", (e) => this.onDown(e));
    el.addEventListener("pointermove", (e) => this.onMove(e));
    el.addEventListener("pointerup", () => this.onUp());
    el.addEventListener("pointerleave", () => this.onUp());

    window.addEventListener("resize", () => this.onResize(container));
    this.animate();
  }

  /** 顯示/隱藏本檢視器的 canvas（模式切換用，避免兩個 canvas 疊放互蓋）。 */
  setVisible(visible: boolean): void {
    this.renderer.domElement.style.display = visible ? "block" : "none";
  }

  /** 移除場景中現有模型（模式切換 / 重新合成時清空）。 */
  clear(): void {
    if (this.current) {
      this.scene.remove(this.current);
      this.current = null;
    }
  }

  /**
   * 切換視角：false = FB 3D Photo 視差（拖曳小幅平移，預設）；
   * true = 自由 Orbit（可旋轉/縮放看真實 3D 結構，會露側面破洞）。
   */
  setOrbitMode(orbit: boolean): void {
    this.orbitMode = orbit;
    this.controls.enabled = orbit;
    const el = this.renderer.domElement;
    if (orbit) {
      // 切到 orbit：把相機重置到正面基準，控制器以 target 為中心。
      this.controls.target.copy(this.target);
      this.camera.position.set(this.target.x, this.target.y, this.target.z + this.baseDistance);
      this.controls.update();
      el.style.cursor = "default";
    } else {
      // 切回視差：歸零拖曳、相機回正面。
      this.dragTarget.set(0, 0);
      this.smoothed.set(0, 0);
      this.camera.position.set(this.target.x, this.target.y, this.target.z + this.baseDistance);
      this.camera.lookAt(this.target);
      el.style.cursor = "grab";
    }
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
   *
   * 解「浮雕感」的關鍵（與舊版差異）：
   *   舊版 baseDistance = (maxDim/2)/tan(fov/2) * 1.4，把整個 3D box 從遠處框住，
   *   配上極小平移量 → 看到的是近乎平面的正面 = 浮雕。
   *   新版相機拉近（係數 0.95，幾乎貼著照片框滿視野），平移幅度加大，拖曳驅動，
   *   讓近景與遠景在視差中明顯錯動 → 身歷其境而非浮雕。
   */
  private frameObject(obj: THREE.Object3D): void {
    const box = new THREE.Box3().setFromObject(obj);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());

    // 用「寬高」(x,y) 而非含深度的 maxDim 來定框距：避免深度把相機推遠而壓平視差。
    const frameDim = Math.max(size.x, size.y);
    const fov = (this.camera.fov * Math.PI) / 180;
    // 拉近：照片幾乎填滿視野（0.95），近景遠景錯動明顯，解浮雕感。
    this.baseDistance = (frameDim / 2) / Math.tan(fov / 2) * 0.95;

    // 視差幅度大幅加大（舊 0.06/0.04 → 0.18/0.10），拖曳時近遠景明顯錯位。
    this.panAmount = frameDim * 0.18;
    this.tiltOffset = frameDim * 0.10;

    this.target.copy(center);
    this.camera.position.set(center.x, center.y, center.z + this.baseDistance);
    this.camera.near = this.baseDistance / 100;
    this.camera.far = this.baseDistance * 100;
    this.camera.lookAt(this.target);
    this.camera.updateProjectionMatrix();

    // 同步 OrbitControls 中心（切到 orbit 時以此為軸）。
    this.controls.target.copy(this.target);
    this.controls.update();
  }

  private onResize(container: HTMLElement): void {
    const w = container.clientWidth;
    const h = container.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  // --- 拖曳驅動（FB 視差模式）---

  private onDown(e: PointerEvent): void {
    if (this.orbitMode) return;        // orbit 模式交給 OrbitControls
    this.dragging = true;
    this.dragStart.set(e.clientX, e.clientY);
    this.renderer.domElement.style.cursor = "grabbing";
  }

  private onMove(e: PointerEvent): void {
    if (this.orbitMode || !this.dragging) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const dx = ((e.clientX - this.dragStart.x) / rect.width) * this.dragScale;
    const dy = ((e.clientY - this.dragStart.y) / rect.height) * this.dragScale;
    this.dragTarget.set(
      THREE.MathUtils.clamp(dx, -1, 1),
      THREE.MathUtils.clamp(dy, -1, 1),
    );
  }

  private onUp(): void {
    if (this.orbitMode) return;
    this.dragging = false;
    this.dragTarget.set(0, 0);         // 放開 → 平滑回正
    this.renderer.domElement.style.cursor = "grab";
  }

  /** 套用視差：相機隨平滑後拖曳量做小幅平移 + 輕微 lookAt 偏移。 */
  private applyParallax(): void {
    // 拖曳中直接跟手（無阻尼）；放開後平滑回正——與 ParallaxViewer 一致。
    if (this.dragging) {
      this.smoothed.copy(this.dragTarget);
    } else {
      this.smoothed.lerp(this.dragTarget, this.damping);
    }

    const px = this.smoothed.x;
    const py = this.smoothed.y;

    // 相機在影像平面上平移（上下取負讓游標往上→看到更上方）。
    this.camera.position.set(
      this.target.x + px * this.panAmount,
      this.target.y - py * this.panAmount,
      this.target.z + this.baseDistance,
    );

    // lookAt 目標反向小幅偏移，形成輕微 tilt（強化視差深度感）。
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
    if (this.current) {
      if (this.orbitMode) {
        this.controls.update();        // OrbitControls 自行更新相機
      } else {
        this.applyParallax();
      }
    }
    this.renderer.render(this.scene, this.camera);
  };
}
