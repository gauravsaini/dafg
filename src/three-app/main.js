import * as THREE from 'three';
import { Boeing747 } from './boeing747.js';
import { AirportEnvironment } from './environment.js';
import { CameraSystem } from './cameraSystem.js';

class BoeingViewerApp {
  constructor() {
    this.canvas = document.getElementById('webgl-canvas');
    this.initThree();
    this.initScene();
    this.initUI();
    this.animate();
  }

  initThree() {
    // 1. Scene
    this.scene = new THREE.Scene();

    // 2. Camera (Realistic 45mm equivalent aviation lens FOV: ~45 deg)
    this.camera = new THREE.PerspectiveCamera(
      45,
      window.innerWidth / window.innerHeight,
      0.5,
      1200
    );

    // 3. WebGL Renderer with High Dynamic Range Tone Mapping
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      powerPreference: 'high-performance',
      alpha: false
    });
    this.renderer.setSize(window.innerWidth, window.innerHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;

    // Window Resize handling
    window.addEventListener('resize', () => {
      this.camera.aspect = window.innerWidth / window.innerHeight;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(window.innerWidth, window.innerHeight);
    });

    this.lastTime = performance.now();
    this.frameCount = 0;
    this.lastFpsUpdate = performance.now();
  }

  initScene() {
    // 1. Airport Environment (Runway, Sky dome, Sun, Ambient)
    this.environment = new AirportEnvironment(this.scene);

    // 2. High-Fidelity Boeing 747-8 Model
    this.aircraft = new Boeing747();
    this.scene.add(this.aircraft.group);

    // 3. Multi-Angle Inspection Camera System
    this.cameraSystem = new CameraSystem(this.camera, this.canvas);
    this.cameraSystem.setPreset('hero');
  }

  initUI() {
    // 1. Camera Viewpoint Buttons
    const navButtons = document.querySelectorAll('.nav-btn');
    const descTitle = document.getElementById('desc-title');
    const descBody = document.getElementById('desc-body');
    const teleView = document.getElementById('tele-view');

    navButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        navButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const key = btn.dataset.preset;
        this.cameraSystem.setPreset(key);

        const presetInfo = this.cameraSystem.presets[key];
        if (presetInfo) {
          descTitle.textContent = presetInfo.name;
          descBody.textContent = presetInfo.desc;
          teleView.textContent = presetInfo.name;
        }
      });
    });

    // 2. 360 Auto-Orbit Tour Button
    const btnTour = document.getElementById('btn-tour');
    btnTour.addEventListener('click', () => {
      const active = this.cameraSystem.toggleAutoOrbit();
      btnTour.classList.toggle('active', active);
      if (active) {
        navButtons.forEach(b => b.classList.remove('active'));
        teleView.textContent = '360° Cinematic Tour';
        descTitle.textContent = '360° Inspection Tour';
        descBody.textContent = 'Automated continuous fly-around inspection of the Boeing 747-8 airframe.';
      }
    });

    // 3. Time of Day (Atmosphere)
    const todButtons = document.querySelectorAll('[data-tod]');
    todButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        todButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const tod = btn.dataset.tod;
        this.environment.setTimeOfDay(tod);
      });
    });

    // 4. Engine Throttle Slider
    const throttleSlider = document.getElementById('slider-throttle');
    const throttleVal = document.getElementById('throttle-val');
    const teleThrust = document.getElementById('tele-thrust');

    throttleSlider.addEventListener('input', (e) => {
      const val = parseInt(e.target.value, 10);
      throttleVal.textContent = val + '%';
      teleThrust.textContent = val + '% N1';
      this.aircraft.setThrottle(val / 100);
    });

    // 5. Landing Gear Button
    const btnGear = document.getElementById('btn-gear');
    const teleGear = document.getElementById('tele-gear');
    btnGear.addEventListener('click', () => {
      const isDown = this.aircraft.toggleLandingGear();
      teleGear.textContent = isDown ? 'DOWN / LOCKED' : 'UP / RETRACTED';
      teleGear.style.color = isDown ? '#4ade80' : '#f87171';
    });

    // 6. Lighting Toggles
    const lightButtons = document.querySelectorAll('[data-light]');
    lightButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        btn.classList.toggle('active');
        const type = btn.dataset.light;
        const enabled = btn.classList.contains('active');
        this.aircraft.setLightingState(type, enabled);
      });
    });

    // 7. Render Modes (PBR, Clay, Wireframe)
    const modeButtons = document.querySelectorAll('[data-mode]');
    modeButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        modeButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const mode = btn.dataset.mode;
        this.setRenderMode(mode);
      });
    });
  }

  setRenderMode(mode) {
    this.aircraft.group.traverse((child) => {
      if (child.isMesh && child.material) {
        if (!child.userData.origMaterial) {
          child.userData.origMaterial = child.material;
        }

        if (mode === 'pbr') {
          child.material = child.userData.origMaterial;
          child.material.wireframe = false;
        } else if (mode === 'clay') {
          if (!child.userData.clayMaterial) {
            child.userData.clayMaterial = new THREE.MeshStandardMaterial({
              color: 0xe2e8f0,
              roughness: 0.6,
              metalness: 0.1
            });
          }
          child.material = child.userData.clayMaterial;
          child.material.wireframe = false;
        } else if (mode === 'wire') {
          child.material = child.userData.origMaterial;
          child.material.wireframe = true;
        }
      }
    });
  }

  animate() {
    requestAnimationFrame(() => this.animate());

    const now = performance.now();
    const delta = Math.min((now - this.lastTime) / 1000, 0.1);
    this.lastTime = now;

    // 1. Update Aircraft Subsystems (turbines, beacons, strobes, gears)
    this.aircraft.update(delta);

    // 2. Update Inspection Camera System
    this.cameraSystem.update(delta);

    // 3. Update Telemetry HUD
    this.frameCount++;
    if (now - this.lastFpsUpdate > 500) {
      const fps = Math.round((this.frameCount * 1000) / (now - this.lastFpsUpdate));
      const teleFps = document.getElementById('tele-fps');
      if (teleFps) teleFps.textContent = fps;
      this.frameCount = 0;
      this.lastFpsUpdate = now;
    }

    const teleDist = document.getElementById('tele-dist');
    if (teleDist) {
      teleDist.textContent = this.cameraSystem.getCurrentTelemetry().distance + ' m';
    }

    // 4. Render Frame
    this.renderer.render(this.scene, this.camera);
  }
}

// Global hook for test automation / headless screenshots
window.addEventListener('DOMContentLoaded', () => {
  window.boeingApp = new BoeingViewerApp();
});
