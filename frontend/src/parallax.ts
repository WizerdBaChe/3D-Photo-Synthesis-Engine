// Facebook 3D Photo 式「深度位移視差」檢視器（輕量路徑，預設）。
// ───────────────────────────────────────────────────────────────────────
// 不建 mesh、不載 .glb：在一張覆蓋畫面的平面 quad 上，用 fragment shader 依
// depth map 對 RGB 做 UV 位移——近處像素位移大、遠處小，造成視差錯覺。
// 互動為「拖曳驅動」：按住拖動才產生視差、易推到上限，放開平滑回正。
//
// depth 約定（與後端 /parallax 一致）：[0,1] 灰階、值大=遠（metric）。
// 故「近度」= (1 - depth)，位移量正比於近度，遠景幾乎不動。
import * as THREE from "three";

const VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

// uMouse ∈ [-1,1]^2（拖曳量）；uIntensity 視差強度；depth 值大=遠。
// 以 0.5 為中性面：比中性近(往觀者) 與比中性遠 反向位移，視差更立體。
//
// 殘影（鬼影 / disocclusion）抑制，兩道防線：
//  A) 邊界衰減：用 depth 局部梯度估物件邊界，邊界處(梯度大)把位移壓到近 0，黏住邊界。
//  B) depth-aware 補色：取樣若落在「比原處明顯更近」的像素（前景滲入背景），視為錯誤
//     取樣，沿位移反方向往背景方向退幾步重採，改填鄰近背景色而非前景色
//     （DIBR depth-aided inpainting 的輕量近似：只填背景、排除前景）。
const FRAG = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform sampler2D uImage;
  uniform sampler2D uDepth;
  uniform vec2 uMouse;
  uniform float uIntensity;
  uniform vec2 uTexel;        // 1/depthSize，用來取鄰格算梯度
  uniform float uEdgeFalloff; // 邊界衰減強度（越大邊界越早被壓住）

  void main() {
    float depth = texture2D(uDepth, vUv).r;     // 0=近, 1=遠

    // ---- A：局部深度梯度（中央差分）→ 物件邊界處梯度大 → 衰減位移 ----
    float dx = texture2D(uDepth, vUv + vec2(uTexel.x, 0.0)).r
             - texture2D(uDepth, vUv - vec2(uTexel.x, 0.0)).r;
    float dy = texture2D(uDepth, vUv + vec2(0.0, uTexel.y)).r
             - texture2D(uDepth, vUv - vec2(0.0, uTexel.y)).r;
    float grad = length(vec2(dx, dy));
    float falloff = 1.0 / (1.0 + uEdgeFalloff * grad);

    float signedDepth = 0.5 - depth;            // >0 近於中性面, <0 遠於中性面
    vec2 offset = uMouse * signedDepth * uIntensity * falloff;
    vec2 sampleUv = clamp(vUv + offset, 0.0, 1.0);

    // ---- B：depth-aware 補色，修正前景滲入（disocclusion） ----
    // 取樣處深度比原處明顯更近 → 取到了不該出現的前景 → 沿 offset 反向退步找背景。
    float sampledDepth = texture2D(uDepth, sampleUv).r;
    if (sampledDepth < depth - 0.06) {
      vec2 back = vUv;        // 回退起點：原像素（屬背景一側）
      // 沿反方向小步搜尋，取「不再更近」的第一個樣本（鄰近背景色）。
      for (int i = 1; i <= 4; i++) {
        vec2 probe = clamp(vUv - offset * (float(i) / 4.0), 0.0, 1.0);
        if (texture2D(uDepth, probe).r >= depth - 0.06) { back = probe; break; }
      }
      sampleUv = back;
    }

    gl_FragColor = texture2D(uImage, sampleUv);
  }
`;

export class ParallaxViewer {
  private scene = new THREE.Scene();
  private camera: THREE.OrthographicCamera;
  private renderer: THREE.WebGLRenderer;
  private material: THREE.ShaderMaterial;
  private mesh: THREE.Mesh | null = null;
  private container: HTMLElement;

  // 拖曳狀態：目標位移（拖曳中更新、放開歸零）與其平滑值。
  private dragging = false;
  private dragStart = new THREE.Vector2();
  private target = new THREE.Vector2(0, 0);
  private smoothed = new THREE.Vector2(0, 0);
  private readonly damping = 0.18;        // 越大反應越快（#1：原 0.08 偏慢）
  private readonly dragScale = 2.2;       // 拖曳靈敏度：易推到 [-1,1] 上限

  constructor(container: HTMLElement) {
    this.container = container;
    const w = container.clientWidth;
    const h = container.clientHeight;

    this.scene.background = new THREE.Color(0x12151b);

    // 正交相機：純 2D 平面，無透視、無「相機太遠」問題（#3）。
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 10);
    this.camera.position.z = 1;

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(this.renderer.domElement);

    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: {
        uImage: { value: null },
        uDepth: { value: null },
        uMouse: { value: new THREE.Vector2(0, 0) },
        uIntensity: { value: 0.06 },
        uTexel: { value: new THREE.Vector2(1 / 1024, 1 / 1024) },
        uEdgeFalloff: { value: 6.0 },   // 邊界衰減強度（越大鬼影越少、視差越保守）
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

  /** 設定視差強度（UI 滑桿綁定；對應 Step 4 的「視差強度語意」）。 */
  setIntensity(v: number): void {
    this.material.uniforms.uIntensity.value = v;
  }

  /** 設定邊界穩定強度（UI 滑桿綁定；越大邊緣殘影越少、視差越保守）。 */
  setEdgeFalloff(v: number): void {
    this.material.uniforms.uEdgeFalloff.value = v;
  }

  /** 載入 RGB 與 depth 兩張圖（data URL），鋪到 quad、依長寬比調整。 */
  async loadParallax(rgbUrl: string, depthUrl: string): Promise<void> {
    const loader = new THREE.TextureLoader();
    const [img, depth] = await Promise.all([
      loader.loadAsync(rgbUrl),
      loader.loadAsync(depthUrl),
    ]);
    img.colorSpace = THREE.SRGBColorSpace;
    // ClampToEdge：位移把取樣推到影像外時，取邊緣色而非 wrap（避免破圖）。
    img.wrapS = img.wrapT = THREE.ClampToEdgeWrapping;
    depth.wrapS = depth.wrapT = THREE.ClampToEdgeWrapping;

    this.material.uniforms.uImage.value = img;
    this.material.uniforms.uDepth.value = depth;
    // texel = 1/depth 尺寸，供 shader 取鄰格算深度梯度（邊界偵測）。
    (this.material.uniforms.uTexel.value as THREE.Vector2).set(
      1 / depth.image.width,
      1 / depth.image.height,
    );

    if (this.mesh) this.scene.remove(this.mesh);
    const aspect = img.image.width / img.image.height;
    // quad 高固定 2（相機 [-1,1]），寬依影像長寬比；onResize 再校正視窗比例。
    const geo = new THREE.PlaneGeometry(2 * aspect, 2);
    this.mesh = new THREE.Mesh(geo, this.material);
    this.scene.add(this.mesh);

    this.imageAspect = aspect;
    this.onResize();
  }

  private imageAspect = 1;

  private onResize(): void {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    this.renderer.setSize(w, h);

    // 讓 quad「contain」於視窗內：依視窗與影像長寬比調整正交相機框。
    const viewAspect = w / h;
    if (viewAspect > this.imageAspect) {
      // 視窗較寬：以高為準，左右留邊
      this.camera.top = 1;
      this.camera.bottom = -1;
      this.camera.right = viewAspect;
      this.camera.left = -viewAspect;
    } else {
      // 視窗較高：以寬為準，上下留邊
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
    // 拖曳位移正規化到 [-1,1]（dragScale 放大 → 容易到上限）。
    const dx = ((e.clientX - this.dragStart.x) / rect.width) * this.dragScale;
    const dy = ((e.clientY - this.dragStart.y) / rect.height) * this.dragScale;
    this.target.set(
      THREE.MathUtils.clamp(dx, -1, 1),
      THREE.MathUtils.clamp(dy, -1, 1),
    );
  }

  private onUp(): void {
    this.dragging = false;
    this.target.set(0, 0);   // 放開 → 平滑回正
    this.renderer.domElement.style.cursor = "grab";
  }

  private animate = (): void => {
    requestAnimationFrame(this.animate);
    this.smoothed.lerp(this.target, this.damping);
    (this.material.uniforms.uMouse.value as THREE.Vector2).copy(this.smoothed);
    this.renderer.render(this.scene, this.camera);
  };
}
