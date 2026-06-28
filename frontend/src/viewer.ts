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
  private baseDistance = 6;          // 相機站位到 mesh 正面的距離
  private cameraZ = 6;               // 相機的世界 Z（= frontZ + baseDistance）
  private panAmount = 0;             // 最大平移量（相機 X/Y 偏移）
  private readonly maxTiltDeg = 8;   // lookAt 目標偏移對應的最大視角（度）
  private target = new THREE.Vector3(0, 0, 0);   // lookAt 基準（正面稍往內）
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
      this.camera.position.set(this.target.x, this.target.y, this.cameraZ);
      this.controls.update();
      el.style.cursor = "default";
    } else {
      // 切回視差：歸零拖曳、相機回正面。
      this.dragTarget.set(0, 0);
      this.smoothed.set(0, 0);
      this.camera.position.set(this.target.x, this.target.y, this.cameraZ);
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
   * 把相機貼近 mesh 的「正面（近平面）」中央，營造「鏡頭在場景內、只見照片內容」
   * 的視差檢視感（對齊 ParallaxViewer），而非「從遠處看一個 3D 物件擺件」。
   *
   * 為什麼要貼著正面而非框住整個 box：
   *   反投影後的 mesh 是個透視「視錐」——近平面內容窄、遠平面（後牆）被透視撐到
   *   約 4 倍寬。若用整體 bbox 寬度(=遠平面寬)定框距，相機會被推到視錐外，整個
   *   房間 box（含地板/天花/左右牆輪廓）全入鏡 → 就是「遠看 3D 物件」的觀感。
   *   改為：相機貼到 box「最靠近觀者那一面」(front = 最大 Z) 前方一小段，框距只
   *   依「正面內容尺寸」估算 → 後方較寬的牆面自然填滿並溢出視野、box 輪廓落在框外，
   *   視角一動近景遠景明顯錯動 = 身歷其境。
   */
  private frameObject(obj: THREE.Object3D): void {
    const box = new THREE.Box3().setFromObject(obj);
    const size = box.getSize(new THREE.Vector3());

    // mesh 座標系：Z = -Z_cam，故「最靠近觀者的正面」= box 的 max.z。
    const frontZ = box.max.z;

    // 關鍵（解「攝影機歪」）：原始拍照的光軸就是 X=0, Y=0 這條線
    //   （反投影 X=(U-cx)Z/fx、Y=-(V-cy)Z/fy，影像中心 U=cx,V=cy → X=Y=0 對所有深度）。
    //   先前對準 bbox center 之所以歪，是因為視錐近窄遠寬、bbox 質心被遠平面拉偏離光軸。
    //   要重現 FB「就是原相機那一眼」，相機站位與 lookAt 都必須落在光軸 X=0,Y=0 上、
    //   視線正對 −Z，畫面才會像視差模式一樣「正」。
    const frontDim = size.y * 0.4;     // 以近平面內容尺度為框高（解「遠看 3D 物件」）
    const fov = (this.camera.fov * Math.PI) / 180;
    this.baseDistance = (frontDim / 2) / Math.tan(fov / 2);

    // 視差平移幅度：相對正面內容尺寸，拖曳時近景（前景物件）與後牆明顯相對位移。
    this.panAmount = frontDim * 0.22;
    this.tiltOffset = frontDim * 0.12;

    // lookAt 目標：落在光軸上（X=0,Y=0），正對 −Z，往內一小段聚焦主體平面。
    this.target.set(0, 0, frontZ - size.z * 0.15);

    // 相機站在光軸上、正面前方 baseDistance 處（X=0,Y=0 → 視線垂直正對，不歪）。
    this.cameraZ = frontZ + this.baseDistance;
    this.camera.position.set(0, 0, this.cameraZ);
    this.camera.near = Math.max(this.baseDistance / 100, 0.001);
    this.camera.far = (this.baseDistance + size.z) * 100;
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
      this.cameraZ,
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
