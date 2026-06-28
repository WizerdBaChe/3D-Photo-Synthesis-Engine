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

// GLSL 迴圈需編譯期固定上限；後端 num_layers 限 2~3，這裡上限取 3。
const MAX_LAYERS = 3;

const VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

// 由遠到近疊加各層；每層按自身 depth 做 UV 位移、用 alpha 合成（near 蓋 far）。
// 近層位移大、遠層位移小 → 前景滑開時露出已預填的背景層。
const FRAG = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform sampler2D uColor[${MAX_LAYERS}];
  uniform sampler2D uDepth[${MAX_LAYERS}];
  uniform sampler2D uAlpha[${MAX_LAYERS}];
  uniform int   uNumLayers;
  uniform vec2  uMouse;
  uniform float uIntensity;

  // 取第 i 層在位移後的取樣（GLSL 不支援以變數索引 sampler 陣列 → 展開）。
  vec4 sampleLayer(int idx, vec2 uv, out float a) {
    vec2 off;
    float d;
    vec4 c;
    // idx 對應「由近到遠」：idx=0 最近。位移正比近度 (1-depth)。
    #define LAYER(I) if (idx == I) { \
        d = texture2D(uDepth[I], uv).r; \
        off = uMouse * (1.0 - d) * uIntensity; \
        vec2 suv = clamp(uv + off, 0.0, 1.0); \
        c = texture2D(uColor[I], suv); \
        a = texture2D(uAlpha[I], suv).r; \
        return c; }
    LAYER(0)
    LAYER(1)
    LAYER(2)
    a = 0.0;
    return vec4(0.0);
  }

  void main() {
    // 從最遠層往最近層合成（over 運算：近層蓋遠層）。
    vec3 rgb = vec3(0.0);
    for (int i = ${MAX_LAYERS} - 1; i >= 0; i--) {
      if (i >= uNumLayers) continue;
      float a;
      vec4 c = sampleLayer(i, vUv, a);
      rgb = mix(rgb, c.rgb, a);
    }
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

    // 預配置固定長度的 sampler 陣列 uniforms（Three.js 需先給佔位 texture）。
    const placeholders = Array.from({ length: MAX_LAYERS }, () => null);
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: {
        uColor: { value: placeholders.slice() },
        uDepth: { value: placeholders.slice() },
        uAlpha: { value: placeholders.slice() },
        uNumLayers: { value: 0 },
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

    const colorTex: (THREE.Texture | null)[] = Array(MAX_LAYERS).fill(null);
    const depthTex: (THREE.Texture | null)[] = Array(MAX_LAYERS).fill(null);
    const alphaTex: (THREE.Texture | null)[] = Array(MAX_LAYERS).fill(null);

    for (let i = 0; i < n; i++) {
      const [c, d, a] = await Promise.all([
        loader.loadAsync(layers[i].color),
        loader.loadAsync(layers[i].depth),
        loader.loadAsync(layers[i].alpha),
      ]);
      c.colorSpace = THREE.SRGBColorSpace;
      for (const t of [c, d, a]) {
        t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
      }
      colorTex[i] = c;
      depthTex[i] = d;
      alphaTex[i] = a;
    }
    // 未用的層位以第一層佔位（避免 sampler 為 null 在某些驅動報錯）。
    for (let i = n; i < MAX_LAYERS; i++) {
      colorTex[i] = colorTex[0];
      depthTex[i] = depthTex[0];
      alphaTex[i] = alphaTex[0];
    }

    this.material.uniforms.uColor.value = colorTex;
    this.material.uniforms.uDepth.value = depthTex;
    this.material.uniforms.uAlpha.value = alphaTex;
    this.material.uniforms.uNumLayers.value = n;

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
