// LDI（Layered Depth Image）多層補洞檢視器 —— Facebook 3D Photo 縱深路徑。
// ───────────────────────────────────────────────────────────────────────
// 與「視差模式」(parallax.ts) 的差異：
//   視差 = 單層平面 + 在 shader 內近似補洞（只能改取既有鄰近背景，填不了真正
//          缺失的內容）。
//   LDI  = 後端把場景沿 depth 斷崖切成多層 RGBA+depth，**背景層的 disocclusion
//          破洞已被預先 inpaint 填好**。本檢視器把各層由遠到近疊加、各層按自身
//          depth 做視差位移、用 alpha 合成 —— 前景滑開時，露出的就是預填好的
//          背景層，從而補掉小角度視差下的空洞（這是 FB 3D Photo 的真正縱深來源）。
//
// 與視差模式並存：本檔不動 parallax.ts；main.ts 以獨立「LDI 模式」切換。
// depth 約定（與後端一致）：[0,1] 灰階、值大=遠；近度 = (1 - depth)，位移正比近度。
import * as THREE from "three";

// 後端 num_layers 限 2~3，這裡上限取 3。
// 重要：WebGL/GLSL ES 對「sampler 陣列以變數索引」「動態迴圈上限」相容性差，
// 過往以陣列 + 迴圈寫法在部分驅動會編譯失敗 → 整片空白（檢視視窗沒內容）。
// 故改為**完全展開的具名 uniform**（uColor0/1/2…），直線合成，全 WebGL 版本皆穩。
const MAX_LAYERS = 3;

const VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

// 由遠到近 over 合成（近層蓋遠層）；每層按自身 depth 做 UV 位移（位移正比近度
// 1-depth）→ 前景滑開時露出已預填的背景層。各層以 uActiveN 決定是否參與（未用層=0）。
const FRAG = /* glsl */ `
  precision highp float;
  varying vec2 vUv;

  uniform sampler2D uColor0;
  uniform sampler2D uDepth0;
  uniform sampler2D uAlpha0;
  uniform sampler2D uColor1;
  uniform sampler2D uDepth1;
  uniform sampler2D uAlpha1;
  uniform sampler2D uColor2;
  uniform sampler2D uDepth2;
  uniform sampler2D uAlpha2;
  uniform float uActive1;     // 1.0 = 第 1 層有效（layer 數 >= 2）
  uniform float uActive2;     // 1.0 = 第 2 層有效（layer 數 >= 3）
  uniform vec2  uMouse;
  uniform float uIntensity;

  // 對單層取樣：依該層 depth 位移後取色與 alpha。
  vec3 sampleLayer(sampler2D colTex, sampler2D depTex, sampler2D alpTex,
                   vec2 uv, out float a) {
    float d = texture2D(depTex, uv).r;            // 0=近, 1=遠
    vec2 off = uMouse * (1.0 - d) * uIntensity;   // 近層位移大、遠層小
    vec2 suv = clamp(uv + off, 0.0, 1.0);
    a = texture2D(alpTex, suv).r;
    return texture2D(colTex, suv).rgb;
  }

  void main() {
    // 從最遠（layer2，若有）→ 中（layer1，若有）→ 最近（layer0）依序 over 合成。
    vec3 rgb = vec3(0.0);
    float a;

    // 最遠：優先 layer2（3 層時），否則 layer1（2 層時的背景底），否則 layer0。
    if (uActive2 > 0.5) {
      rgb = sampleLayer(uColor2, uDepth2, uAlpha2, vUv, a);   // 背景底（alpha 全 1）
    } else if (uActive1 > 0.5) {
      rgb = sampleLayer(uColor1, uDepth1, uAlpha1, vUv, a);
    } else {
      rgb = sampleLayer(uColor0, uDepth0, uAlpha0, vUv, a);
      gl_FragColor = vec4(rgb, 1.0);
      return;
    }

    // 中層（3 層時的 layer1）疊上。
    if (uActive2 > 0.5 && uActive1 > 0.5) {
      vec3 c1 = sampleLayer(uColor1, uDepth1, uAlpha1, vUv, a);
      rgb = mix(rgb, c1, a);
    }

    // 最近層（layer0）疊上。
    vec3 c0 = sampleLayer(uColor0, uDepth0, uAlpha0, vUv, a);
    rgb = mix(rgb, c0, a);

    gl_FragColor = vec4(rgb, 1.0);
  }
`;

interface LDILayerData {
  color: string;   // data URL
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

  // 拖曳狀態（與 ParallaxViewer 同手感）。
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

    // 多層 shader 若在某驅動編譯失敗會整片空白（難以察覺）。掛上錯誤回呼，
    // 把 GLSL 編譯錯誤的 infoLog 丟到 console，便於定位而非靜默空白。
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
        uColor0: { value: null }, uDepth0: { value: null }, uAlpha0: { value: null },
        uColor1: { value: null }, uDepth1: { value: null }, uAlpha1: { value: null },
        uColor2: { value: null }, uDepth2: { value: null }, uAlpha2: { value: null },
        uActive1: { value: 0 },
        uActive2: { value: 0 },
        uMouse: { value: new THREE.Vector2(0, 0) },
        uIntensity: { value: 0.06 },
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

  setIntensity(v: number): void {
    this.material.uniforms.uIntensity.value = v;
  }

  /** 載入多層 LDI（layers 由近到遠），鋪到 quad。 */
  async loadLDI(layers: LDILayerData[], width: number, height: number): Promise<void> {
    const n = Math.min(layers.length, MAX_LAYERS);
    const loader = new THREE.TextureLoader();

    // 載入每層三張圖（color/depth/alpha）。
    const tex: { c: THREE.Texture; d: THREE.Texture; a: THREE.Texture }[] = [];
    for (let i = 0; i < n; i++) {
      const [c, d, a] = await Promise.all([
        loader.loadAsync(layers[i].color),
        loader.loadAsync(layers[i].depth),
        loader.loadAsync(layers[i].alpha),
      ]);
      c.colorSpace = THREE.SRGBColorSpace;
      for (const t of [c, d, a]) {
        t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
        t.needsUpdate = true;
      }
      tex.push({ c, d, a });
    }

    const u = this.material.uniforms;
    // 未用的層位以第一層佔位（避免 sampler 為 null 在某些驅動報錯），
    // 並用 uActive1/2 關閉其參與合成。
    const slot = (i: number) => tex[Math.min(i, n - 1)];
    u.uColor0.value = slot(0).c; u.uDepth0.value = slot(0).d; u.uAlpha0.value = slot(0).a;
    u.uColor1.value = slot(1).c; u.uDepth1.value = slot(1).d; u.uAlpha1.value = slot(1).a;
    u.uColor2.value = slot(2).c; u.uDepth2.value = slot(2).d; u.uAlpha2.value = slot(2).a;
    u.uActive1.value = n >= 2 ? 1 : 0;
    u.uActive2.value = n >= 3 ? 1 : 0;

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
