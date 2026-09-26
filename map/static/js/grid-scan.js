// GridScan -- corredor de grade em perspectiva com um pulso de "sonar"
// varrendo por ele. Adaptado do componente React do próprio painel de DNS
// da Natverk (D:\dns-bind9\frontend\src\components\GridScan.jsx, que por
// sua vez credita reactbits.dev/backgrounds/grid-scan), portado pra JS
// puro/ES module porque este projeto não tem build step nem React -- só a
// parte de fato usada na tela de login (sem postprocessing, sem giroscópio,
// sem scan por clique, já que a tela de login de origem não liga nenhum
// desses). Shader (vert/frag) mantido igual ao original.
import * as THREE from 'https://unpkg.com/three@0.180.0/build/three.module.js';

const vert = `
varying vec2 vUv;
void main(){
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

const frag = `
precision highp float;
uniform vec3 iResolution;
uniform float iTime;
uniform vec2 uSkew;
uniform float uTilt;
uniform float uYaw;
uniform float uLineThickness;
uniform vec3 uLinesColor;
uniform vec3 uScanColor;
uniform float uGridScale;
uniform float uLineStyle;
uniform float uLineJitter;
uniform float uScanOpacity;
uniform float uScanDirection;
uniform float uNoise;
uniform float uBloomOpacity;
uniform float uScanGlow;
uniform float uScanSoftness;
uniform float uPhaseTaper;
uniform float uScanDuration;
uniform float uScanDelay;
uniform float uLightMode;
uniform float uFlowSpeed;
uniform float uStaticLight;
uniform float uStaticLightPos;
uniform float uFocalLength;
uniform float uScanTaperOut;
varying vec2 vUv;
uniform float uScanStarts[8];
uniform float uScanCount;
const int MAX_SCANS = 8;

float smoother01(float a,float b,float x){
  float t=clamp((x-a)/max(1e-5,(b-a)),0.0,1.0);
  return t*t*t*(t*(t*6.0-15.0)+10.0);
}

void mainImage(out vec4 fragColor,in vec2 fragCoord){
  vec2 p=(2.0*fragCoord-iResolution.xy)/iResolution.y;
  vec3 ro=vec3(0.0);
  vec3 rd=normalize(vec3(p,max(0.3,uFocalLength)));
  float cR=cos(uTilt),sR=sin(uTilt);
  rd.xy=mat2(cR,-sR,sR,cR)*rd.xy;
  float cY=cos(uYaw),sY=sin(uYaw);
  rd.xz=mat2(cY,-sY,sY,cY)*rd.xz;
  vec2 skew=clamp(uSkew,vec2(-0.7),vec2(0.7));
  rd.xy+=skew*rd.z;
  vec3 color=vec3(0.0);
  float minT=1e20;
  float gridScale=max(1e-5,uGridScale);
  float fadeStrength=2.0;
  vec2 gridUV=vec2(0.0);
  float hitIsY=1.0;
  for(int i=0;i<4;i++){
    float isY=float(i<2);
    float pos=mix(-0.2,0.2,float(i))*isY+mix(-0.5,0.5,float(i-2))*(1.0-isY);
    float num=pos-(isY*ro.y+(1.0-isY)*ro.x);
    float den=isY*rd.y+(1.0-isY)*rd.x;
    float t=num/den;
    vec3 h=ro+rd*t;
    float depthBoost=smoothstep(0.0,3.0,h.z);
    h.xy+=skew*0.15*depthBoost;
    bool use=t>0.0&&t<minT;
    gridUV=use?mix(h.zy,h.xz,isY)/gridScale:gridUV;
    minT=use?t:minT;
    hitIsY=use?isY:hitIsY;
  }
  vec3 hit=ro+rd*minT;
  float dist=length(hit-ro);
  if(hitIsY>0.5){gridUV.y+=iTime*uFlowSpeed;}else{gridUV.x+=iTime*uFlowSpeed;}
  float jitterAmt=clamp(uLineJitter,0.0,1.0);
  if(jitterAmt>0.0){
    vec2 j=vec2(sin(gridUV.y*2.7+iTime*1.8),cos(gridUV.x*2.3-iTime*1.6))*(0.15*jitterAmt);
    gridUV+=j;
  }
  float fx=fract(gridUV.x);float fy=fract(gridUV.y);
  float ax=min(fx,1.0-fx);float ay=min(fy,1.0-fy);
  float wx=fwidth(gridUV.x);float wy=fwidth(gridUV.y);
  float halfPx=max(0.0,uLineThickness)*0.5;
  float tx=halfPx*wx;float ty=halfPx*wy;
  float aax=wx;float aay=wy;
  float lineX=1.0-smoothstep(tx,tx+aax,ax);
  float lineY=1.0-smoothstep(ty,ty+aay,ay);
  if(uLineStyle>0.5){
    float dr=4.0,dd=0.5;
    float vy=fract(gridUV.y*dr),vx=fract(gridUV.x*dr);
    float dmY=step(vy,dd),dmX=step(vx,dd);
    if(uLineStyle<1.5){lineX*=dmY;lineY*=dmX;}
    else{
      float dotr=6.0,dotw=0.18;
      float cy=abs(fract(gridUV.y*dotr)-0.5),cx2=abs(fract(gridUV.x*dotr)-0.5);
      lineX*=1.0-smoothstep(dotw,dotw+fwidth(gridUV.y*dotr),cy);
      lineY*=1.0-smoothstep(dotw,dotw+fwidth(gridUV.x*dotr),cx2);
    }
  }
  float primaryMask=max(lineX,lineY);
  vec2 gridUV2=(hitIsY>0.5?hit.xz:hit.zy)/gridScale;
  if(hitIsY>0.5){gridUV2.y+=iTime*uFlowSpeed;}else{gridUV2.x+=iTime*uFlowSpeed;}
  if(jitterAmt>0.0){
    vec2 j2=vec2(cos(gridUV2.y*2.1-iTime*1.4),sin(gridUV2.x*2.5+iTime*1.7))*(0.15*jitterAmt);
    gridUV2+=j2;
  }
  float fx2=fract(gridUV2.x),fy2=fract(gridUV2.y);
  float ax2=min(fx2,1.0-fx2),ay2=min(fy2,1.0-fy2);
  float wx2=fwidth(gridUV2.x),wy2=fwidth(gridUV2.y);
  float tx2=halfPx*wx2,ty2=halfPx*wy2;
  float lineX2=1.0-smoothstep(tx2,tx2+wx2,ax2);
  float lineY2=1.0-smoothstep(ty2,ty2+wy2,ay2);
  if(uLineStyle>0.5){
    float dr2=4.0,dd2=0.5;
    float vy2=fract(gridUV2.y*dr2),vx2=fract(gridUV2.x*dr2);
    float dmY2=step(vy2,dd2),dmX2=step(vx2,dd2);
    if(uLineStyle<1.5){lineX2*=dmY2;lineY2*=dmX2;}
    else{
      float dotr2=6.0,dotw2=0.18;
      float cy2=abs(fract(gridUV2.y*dotr2)-0.5),cx2b=abs(fract(gridUV2.x*dotr2)-0.5);
      lineX2*=1.0-smoothstep(dotw2,dotw2+fwidth(gridUV2.y*dotr2),cy2);
      lineY2*=1.0-smoothstep(dotw2,dotw2+fwidth(gridUV2.x*dotr2),cx2b);
    }
  }
  float altMask=max(lineX2,lineY2);
  float edgeDistX=min(abs(hit.x-(-0.5)),abs(hit.x-0.5));
  float edgeDistY=min(abs(hit.y-(-0.2)),abs(hit.y-0.2));
  float edgeDist=mix(edgeDistY,edgeDistX,hitIsY);
  altMask*=1.0-smoothstep(gridScale*0.5,gridScale*2.0,edgeDist);
  float lineMask=max(primaryMask,altMask);
  float fade=exp(-dist*fadeStrength);
  float dur=max(0.05,uScanDuration);
  float del=max(0.0,uScanDelay);
  float scanZMax=2.0;
  float widthScale=max(0.1,uScanGlow);
  float sigma=max(0.001,0.18*widthScale*uScanSoftness);
  float sigmaA=sigma*2.0;
  float combinedPulse=0.0,combinedAura=0.0;
  float cycle=dur+del;
  float tCycle=mod(iTime,cycle);
  float scanPhase=clamp((tCycle-del)/dur,0.0,1.0);
  float phase=scanPhase;
  if(uScanDirection>0.5&&uScanDirection<1.5){phase=1.0-phase;}
  else if(uScanDirection>1.5){float t2=mod(max(0.0,iTime-del),2.0*dur);phase=(t2<dur)?(t2/dur):(1.0-(t2-dur)/dur);}
  float scanZ=phase*scanZMax;
  float dz=abs(hit.z-scanZ);
  float lineBand=exp(-0.5*(dz*dz)/(sigma*sigma));
  float taperIn=clamp(uPhaseTaper,0.0,0.49);
  float taperOut=clamp(uScanTaperOut,0.0,0.49);
  float phaseWindow=smoother01(0.0,taperIn,phase)*(1.0-smoother01(1.0-taperOut,1.0,phase));
  combinedPulse+=lineBand*phaseWindow*clamp(uScanOpacity,0.0,1.0);
  combinedAura+=(exp(-0.5*(dz*dz)/(sigmaA*sigmaA))*0.25)*phaseWindow*clamp(uScanOpacity,0.0,1.0);
  for(int i=0;i<MAX_SCANS;i++){
    if(float(i)>=uScanCount)break;
    float tA=iTime-uScanStarts[i];
    float phI=clamp(tA/dur,0.0,1.0);
    if(uScanDirection>0.5&&uScanDirection<1.5){phI=1.0-phI;}
    else if(uScanDirection>1.5){phI=(phI<0.5)?(phI*2.0):(1.0-(phI-0.5)*2.0);}
    float szI=phI*scanZMax;
    float dzI=abs(hit.z-szI);
    float lbI=exp(-0.5*(dzI*dzI)/(sigma*sigma));
    float pwI=smoother01(0.0,taperIn,phI)*(1.0-smoother01(1.0-taperOut,1.0,phI));
    combinedPulse+=lbI*pwI*clamp(uScanOpacity,0.0,1.0);
    combinedAura+=(exp(-0.5*(dzI*dzI)/(sigmaA*sigmaA))*0.25)*pwI*clamp(uScanOpacity,0.0,1.0);
  }
  if(uStaticLight>0.0){
    float szS=uStaticLightPos*scanZMax;
    float dzS=abs(hit.z-szS);
    float lbS=exp(-0.5*(dzS*dzS)/(sigma*sigma));
    combinedPulse+=lbS*uStaticLight;
    combinedAura+=(exp(-0.5*(dzS*dzS)/(sigmaA*sigmaA))*0.25)*uStaticLight;
  }
  float lineVis=lineMask;
  vec3 gridCol=uLinesColor*lineVis*fade;
  vec3 scanCol=uScanColor*combinedPulse;
  vec3 scanAura=uScanColor*combinedAura;
  color=gridCol+scanCol+scanAura;
  float n=fract(sin(dot(gl_FragCoord.xy+vec2(iTime*123.4),vec2(12.9898,78.233)))*43758.5453123);
  color+=(n-0.5)*uNoise;
  color=clamp(color,0.0,1.0);
  float alpha=clamp(max(lineVis,combinedPulse),0.0,1.0);
  float gx2=1.0-smoothstep(tx*2.0,tx*2.0+aax*2.0,ax);
  float gy2=1.0-smoothstep(ty*2.0,ty*2.0+aay*2.0,ay);
  float halo=max(gx2,gy2)*fade;
  alpha=max(alpha,halo*clamp(uBloomOpacity,0.0,1.0));
  if(uLightMode>0.5){
    float energy=max(max(color.r,color.g),color.b);
    float coverage=clamp(max(alpha,smoothstep(0.0,0.55,energy)*0.82),0.0,0.9)*smoothstep(0.015,0.12,energy);
    vec3 chroma=pow(clamp(color/max(energy,0.0001),0.0,1.0),vec3(1.2));
    fragColor=vec4(mix(vec3(1.0),chroma,coverage*0.94),1.0);
  } else {
    fragColor=vec4(color,alpha);
  }
}

void main(){
  vec4 c;
  mainImage(c,vUv*iResolution.xy);
  gl_FragColor=c;
}
`;

function srgbColor(hex) {
  const c = new THREE.Color(hex);
  c.convertSRGBToLinear();
  return c;
}

function smoothDampFloat(current, target, velRef, smoothTime, dt) {
  smoothTime = Math.max(0.0001, smoothTime);
  const omega = 2.0 / smoothTime;
  const x = omega * dt;
  const exp_ = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x);
  let change = current - target;
  const originalTo = target;
  change = Math.max(-Infinity, Math.min(Infinity, change));
  target = current - change;
  const temp = (velRef.v + omega * change) * dt;
  velRef.v = (velRef.v - omega * temp) * exp_;
  let value = target + (change + temp) * exp_;
  if ((originalTo - current > 0) === (value > originalTo)) {
    value = originalTo;
    velRef.v = 0;
  }
  return value;
}

// Cria e liga um GridScan dentro de `container` (precisa ter tamanho real --
// position:relative/absolute definido no CSS de quem chama). Devolve uma
// função `dispose()` pra parar o loop e liberar o contexto WebGL.
export function createGridScan(container, opts = {}) {
  const {
    linesColor = '#2F293A', scanColor = '#FF9FFC', scanOpacity = 0.4,
    gridScale = 0.1, lineJitter = 0.1, scanDirection = 'forward',
    noiseIntensity = 0.01, scanGlow = 0.5, scanSoftness = 2,
    scanPhaseTaper = 0.9, scanDuration = 2.0, scanDelay = 2.0,
    flowSpeed = 0, staticLight = 0, staticLightPos = 0.5,
    focalLength = 2.0, scanTaperOut = 0, lineThickness = 1,
    sensitivity = 0.55, snapBackDelay = 250,
  } = opts;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.autoClear = false;
  renderer.setClearColor(0x000000, 0);
  container.appendChild(renderer.domElement);

  const uniforms = {
    iResolution: { value: new THREE.Vector3(container.clientWidth, container.clientHeight, renderer.getPixelRatio()) },
    iTime: { value: 0 },
    uSkew: { value: new THREE.Vector2(0, 0) },
    uTilt: { value: 0 },
    uYaw: { value: 0 },
    uLineThickness: { value: lineThickness },
    uLinesColor: { value: srgbColor(linesColor) },
    uScanColor: { value: srgbColor(scanColor) },
    uGridScale: { value: gridScale },
    uLineStyle: { value: 0 },
    uLineJitter: { value: Math.max(0, Math.min(1, lineJitter || 0)) },
    uScanOpacity: { value: scanOpacity },
    uNoise: { value: noiseIntensity },
    uBloomOpacity: { value: 0 },
    uScanGlow: { value: scanGlow },
    uScanSoftness: { value: scanSoftness },
    uPhaseTaper: { value: scanPhaseTaper },
    uScanDuration: { value: scanDuration },
    uScanDelay: { value: scanDelay },
    uScanDirection: { value: scanDirection === 'backward' ? 1 : scanDirection === 'pingpong' ? 2 : 0 },
    uScanStarts: { value: new Array(8).fill(0) },
    uScanCount: { value: 0 },
    uLightMode: { value: 0 },
    uFlowSpeed: { value: flowSpeed },
    uStaticLight: { value: staticLight },
    uStaticLightPos: { value: staticLightPos },
    uFocalLength: { value: focalLength },
    uScanTaperOut: { value: scanTaperOut },
  };

  const material = new THREE.ShaderMaterial({
    uniforms, vertexShader: vert, fragmentShader: frag,
    transparent: true, depthWrite: false, depthTest: false,
  });

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
  scene.add(quad);

  // Look-around suave com o mouse -- mesmo smooth-damp do original, só sem
  // o giroscópio/clique (a tela de login não usa nenhum dos dois).
  const s = Math.max(0, Math.min(1, sensitivity));
  const lerp = (a, b, t) => a + (b - a) * t;
  const skewScale = lerp(0.06, 0.2, s);
  const smoothTime = lerp(0.45, 0.12, s);
  const lookTarget = { x: 0, y: 0 };
  const lookCurrent = { x: 0, y: 0 };
  const lookVel = { x: { v: 0 }, y: { v: 0 } };

  let leaveTimer = null;
  const onMove = (e) => {
    if (leaveTimer) { clearTimeout(leaveTimer); leaveTimer = null; }
    const rect = container.getBoundingClientRect();
    lookTarget.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    lookTarget.y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
  };
  const onLeave = () => {
    if (leaveTimer) clearTimeout(leaveTimer);
    leaveTimer = window.setTimeout(() => { lookTarget.x = 0; lookTarget.y = 0; }, Math.max(0, snapBackDelay || 0));
  };
  container.addEventListener('mousemove', onMove);
  container.addEventListener('mouseleave', onLeave);

  const onResize = () => {
    renderer.setSize(container.clientWidth, container.clientHeight);
    uniforms.iResolution.value.set(container.clientWidth, container.clientHeight, renderer.getPixelRatio());
  };
  window.addEventListener('resize', onResize);

  let rafId = null;
  let last = performance.now();
  const tick = () => {
    const now = performance.now();
    const dt = Math.max(0, Math.min(0.1, (now - last) / 1000));
    last = now;

    lookCurrent.x = smoothDampFloat(lookCurrent.x, lookTarget.x, lookVel.x, smoothTime, dt);
    lookCurrent.y = smoothDampFloat(lookCurrent.y, lookTarget.y, lookVel.y, smoothTime, dt);
    uniforms.uSkew.value.set(lookCurrent.x * skewScale, -lookCurrent.y * lerp(1.2, 1.6, s) * skewScale);
    uniforms.iTime.value = now / 1000;

    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);

  return function dispose() {
    if (rafId) cancelAnimationFrame(rafId);
    window.removeEventListener('resize', onResize);
    container.removeEventListener('mousemove', onMove);
    container.removeEventListener('mouseleave', onLeave);
    if (leaveTimer) clearTimeout(leaveTimer);
    material.dispose();
    quad.geometry.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement);
  };
}
