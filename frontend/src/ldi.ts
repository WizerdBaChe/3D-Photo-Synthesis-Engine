// LDI（Layered Depth Image）補洞檢視器 —— Facebook 3D Photo 縱深路徑。
// ───────────────────────────────────────────────────────────────────────
// 設計（依業界 FB 3D Photo / Alan Zucconi 視差 shader 修正後）：
//   渲染採**連續逐像素 depth 位移**（與視差模式相同、已驗證乾淨無紙板感）——
//   depth 平滑連續 → UV 位移漸變 → 沒有「前景整塊被拔出」的紙板抽離感。
//   LDI 的多層只在**被前景掀開的 disocclusion 處**發揮作用：當連續位移取樣落到
//   「比原處明顯更近」的前景（= 露出了本該是背景的破洞）時，改取後端**預先 inpaint
//   填好的背景底層** `uBg`，而非視差模式那種「往鄰近退步找既有背景」的近似。
//   → 同時拿到「連續無紙板」(視差模式優點) + 「破洞填真實內容」(LDI 優點)。
//
// 與視差模式並存：本檔不動 parallax.ts；main.ts 以獨立「LDI 模式」切換。
// depth 約定（與後端一致）：[0,1] 灰階、值大=遠；以 0.5 為中性面。
import * as THREE from "three";

const VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

// 連續位移（同視差模式）：signedDepth = 0.5 - depth；offset = uMouse*signedDepth*強度*邊界衰減。
// disocclusion 修正：取樣處 depth 明顯比原處近 → 取到前景 → 改取預填背景底 uBg（同一 sampleUv）。
const FRAG = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform sampler2D uImage;     // 原圖 RGB
  uniform sampler2D uDepth;     // 原圖正規化 depth（0=近,1=遠）
  uniform sampler2D uBg;        // 預先補洞的背景底層 RGB
  uniform vec2  uMouse;
  uniform float uIntensity;
  uniform vec2  uTexel;         // 1/depthSize，取鄰格算梯度
  uniform float uEdgeFalloff;   // 邊界衰減（越大邊界越早壓住、紙板/鬼影越少）

  void main() {
    float depth = texture2D(uDepth, vUv).r;

    // 邊界衰減：物件邊界（深度梯度大）處把位移壓近 0，避免邊緣硬切。
    float dx = texture2D(uDepth, vUv + vec2(uTexel.x, 0.0)).r
             - texture2D(uDepth, vUv - vec2(uTexel.x, 0.0)).r;
    float dy = texture2D(uDepth, vUv + vec2(0.0, uTexel.y)).r
             - texture2D(uDepth, vUv - vec2(0.0, uTexel.y)).r;
    float grad = length(vec2(dx, dy));
    float falloff = 1.0 / (1.0 + uEdgeFalloff * grad);

    float signedDepth = 0.5 - depth;                // >0 近於中性面
    vec2 offset = uMouse * signedDepth * uIntensity * falloff;
    vec2 sampleUv = clamp(vUv + offset, 0.0, 1.0);

    // disocclusion：取樣處比原處明顯更近 = 取到不該出現的前景（破洞）→ 取預填背景。
    float sampledDepth = texture2D(uDepth, sampleUv).r;
    if (sampledDepth < depth - 0.06) {
      gl_FragColor = texture2D(uBg, sampleUv);
      return;
    }
    gl_FragColor = texture2D(uImage, sampleUv);
  }
`;

interface LDILayerData {
  color: string;
  depth: string;
  alpha: string;
  depthMin: number;
  depthMax: number;
}

export class LDIViewer {
  private scene = new THREE.Scene();
  private camera: THREE.OrthographicCamera;
  private renderer: THREE.WebGLRenderer;
  private material: THREE.ShaderMaterial;
  private mesh: THREE.Mesh | null = null;
  private container: HTMLElement;

  // 拖曳狀態（與 ParallaxViewer 完全同手感）。
  private dragging = false;
  private dragStart = new THREE.Vector2();
  private target = new THREE.Vector2(0, 0);
  private smoothed = new THREE.Vector2(0, 0);
  private readonly damping = 0.18;
  private readonly dragScale = 3.5;
  private imageAspect = 1;

  constructor(container: HTMLElement) {
    this.container = container;
    const w = container.clientWidth;
    const h = container.clientHeight;

    this.scene.background = new THREE.Color(0x12151b);
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 10);
    this.camera.position.z = 1;

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.domElement.style.display = "none";   // 預設隱藏（視差為預設模式）
    container.appendChild(this.renderer.domElement);

    this.renderer.debug.onShaderError = (gl, _prog, vs, fs) => {
      console.error(
        "[LDIViewer] shader 編譯失敗\nVERTEX:\n",
        gl.getShaderInfoLog(vs),
        "\nFRAGMENT:\n",
        gl.getShaderInfoLog(fs),
      );
    };

    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: {
        uImage: { value: null },
        uDepth: { value: null },
        uBg: { value: null },
        uMouse: { value: new THREE.Vector2(0, 0) },
        uIntensity: { value: 0.06 },
        uTexel: { value: new THREE.Vector2(1 / 1024, 1 / 1024) },
        uEdgeFalloff: { value: 6.0 },
      },
    });

    const el = this.renderer.domElement;
    el.style.cursor = "grab";
    el.addEventListener("pointerdown", (e) => this.onDown(e));
    el.addEventListener("pointermove", (e) => this.onMove(e));
    el.addEventListener("pointerup", () => this.onUp());
    el.addEventListener("pointerleave", () => this.onUp());

    window.addEventListener("resize", () => this.onResize());
    this.animate();
  }

  setVisible(visible: boolean): void {
    this.renderer.domElement.style.display = visible ? "block" : "none";
  }

  /** 移除已載入的 quad（模式切換 / 重新合成時清空，避免殘留舊圖）。 */
  clear(): void {
    if (this.mesh) {
      this.scene.remove(this.mesh);
      this.mesh = null;
    }
    this.target.set(0, 0);
    this.smoothed.set(0, 0);
  }

  setIntensity(v: number): void {
    this.material.uniforms.uIntensity.value = v;
  }

  setEdgeFalloff(v: number): void {
    this.material.uniforms.uEdgeFalloff.value = v;
  }

  /**
   * 載入 LDI 資料：rgbUrl/depthUrl = 原圖（連續位移用）、bgUrl = 預填背景底層。
   * layers 保留供未來標準化 / .ldi（本連續渲染器不直接用）。
   */
  async loadLDI(
    rgbUrl: string,
    depthUrl: string,
    bgUrl: string,
    width: number,
    height: number,
    _layers?: LDILayerData[],
  ): Promise<void> {
    const loader = new THREE.TextureLoader();
    const [img, depth, bg] = await Promise.all([
      loader.loadAsync(rgbUrl),
      loader.loadAsync(depthUrl),
      loader.loadAsync(bgUrl),
    ]);
    img.colorSpace = THREE.SRGBColorSpace;
    bg.colorSpace = THREE.SRGBColorSpace;
    for (const t of [img, depth, bg]) {
      t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
      t.needsUpdate = true;
    }

    const u = this.material.uniforms;
    u.uImage.value = img;
    u.uDepth.value = depth;
    u.uBg.value = bg;
    (u.uTexel.value as THREE.Vector2).set(
      1 / depth.image.width,
      1 / depth.image.height,
    );

    if (this.mesh) this.scene.remove(this.mesh);
    const aspect = width / height;
    const geo = new THREE.PlaneGeometry(2 * aspect, 2);
    this.mesh = new THREE.Mesh(geo, this.material);
    this.scene.add(this.mesh);

    this.imageAspect = aspect;
    this.onResize();
  }

  private onResize(): void {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    this.renderer.setSize(w, h);

    const viewAspect = w / h;
    if (viewAspect > this.imageAspect) {
      this.camera.top = 1;
      this.camera.bottom = -1;
      this.camera.right = viewAspect;
      this.camera.left = -viewAspect;
    } else {
      this.camera.left = -this.imageAspect;
      this.camera.right = this.imageAspect;
      this.camera.top = this.imageAspect / viewAspect;
      this.camera.bottom = -this.imageAspect / viewAspect;
    }
    this.camera.updateProjectionMatrix();
  }

  private onDown(e: PointerEvent): void {
    this.dragging = true;
    this.dragStart.set(e.clientX, e.clientY);
    this.renderer.domElement.style.cursor = "grabbing";
  }

  private onMove(e: PointerEvent): void {
    if (!this.dragging) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const dx = ((e.clientX - this.dragStart.x) / rect.width) * this.dragScale;
    const dy = ((e.clientY - this.dragStart.y) / rect.height) * this.dragScale;
    this.target.set(
      THREE.MathUtils.clamp(dx, -1, 1),
      THREE.MathUtils.clamp(dy, -1, 1),
    );
  }

  private onUp(): void {
    this.dragging = false;
    this.target.set(0, 0);
    this.renderer.domElement.style.cursor = "grab";
  }

  private animate = (): void => {
    requestAnimationFrame(this.animate);
    if (this.dragging) {
      this.smoothed.copy(this.target);
    } else {
      this.smoothed.lerp(this.target, this.damping);
    }
    (this.material.uniforms.uMouse.value as THREE.Vector2).copy(this.smoothed);
    this.renderer.render(this.scene, this.camera);
  };
}
