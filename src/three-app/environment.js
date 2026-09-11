import * as THREE from 'three';
import { createRunwayTexture } from './textures.js';

export class AirportEnvironment {
  constructor(scene) {
    this.scene = scene;
    this.timeOfDay = 'day'; // 'day' | 'sunset' | 'night'
    this.initEnvironment();
  }

  initEnvironment() {
    this.envGroup = new THREE.Group();
    this.envGroup.name = 'Airport_Environment';

    // 1. Runway Tarmac Mesh
    const runwayTex = createRunwayTexture();
    const runwayGeo = new THREE.PlaneGeometry(120, 480);
    runwayGeo.rotateX(-Math.PI / 2);
    
    this.runwayMaterial = new THREE.MeshStandardMaterial({
      map: runwayTex,
      roughness: 0.85,
      metalness: 0.1
    });

    const runwayMesh = new THREE.Mesh(runwayGeo, this.runwayMaterial);
    runwayMesh.position.set(0, -6.9, 0); // Position under the landing gear wheels
    runwayMesh.receiveShadow = true;
    this.envGroup.add(runwayMesh);

    // 2. Surrounding Airport Terrain / Grass / Apron
    const terrainGeo = new THREE.PlaneGeometry(1200, 1200);
    terrainGeo.rotateX(-Math.PI / 2);
    const terrainMaterial = new THREE.MeshStandardMaterial({
      color: 0x1e293b,
      roughness: 0.95,
      metalness: 0.05
    });
    const terrainMesh = new THREE.Mesh(terrainGeo, terrainMaterial);
    terrainMesh.position.set(0, -6.92, 0);
    terrainMesh.receiveShadow = true;
    this.envGroup.add(terrainMesh);

    // 3. Runway Edge & Threshold Lights
    this.buildRunwayLighting();

    // 4. Sky & Atmosphere Dome
    this.buildSkyDome();

    // 5. Sun & Ambient Lighting
    this.buildLighting();

    this.scene.add(this.envGroup);
  }

  buildRunwayLighting() {
    this.runwayLightsGroup = new THREE.Group();
    this.runwayLightsGroup.name = 'Runway_Lights';

    const lightGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.35, 8);
    const whiteGlowMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
    const greenGlowMat = new THREE.MeshBasicMaterial({ color: 0x22c55e });
    const amberGlowMat = new THREE.MeshBasicMaterial({ color: 0xf59e0b });

    // Edge lights along left & right sides of runway (spacing every 20m)
    for (let z = -220; z <= 220; z += 20) {
      const isAftSection = z < -100;
      const mat = isAftSection ? amberGlowMat : whiteGlowMat;

      // Left edge
      const lightL = new THREE.Mesh(lightGeo, mat);
      lightL.position.set(-54, -6.7, z);
      this.runwayLightsGroup.add(lightL);

      // Right edge
      const lightR = new THREE.Mesh(lightGeo, mat);
      lightR.position.set(54, -6.7, z);
      this.runwayLightsGroup.add(lightR);
    }

    // Threshold Green Lights across runway threshold (Z = 200)
    for (let x = -50; x <= 50; x += 5) {
      const greenLight = new THREE.Mesh(lightGeo, greenGlowMat);
      greenLight.position.set(x, -6.7, 210);
      this.runwayLightsGroup.add(greenLight);
    }

    this.envGroup.add(this.runwayLightsGroup);
  }

  buildSkyDome() {
    const skyGeo = new THREE.SphereGeometry(600, 32, 24);
    // Custom gradient sky material
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 512;
    this.skyCtx = canvas.getContext('2d');
    this.skyCanvas = canvas;
    this.updateSkyGradient('day');

    this.skyTexture = new THREE.CanvasTexture(canvas);
    const skyMat = new THREE.MeshBasicMaterial({
      map: this.skyTexture,
      side: THREE.BackSide
    });

    this.skyMesh = new THREE.Mesh(skyGeo, skyMat);
    this.envGroup.add(this.skyMesh);
  }

  updateSkyGradient(mode) {
    const ctx = this.skyCtx;
    const h = this.skyCanvas.height;
    const w = this.skyCanvas.width;
    const grad = ctx.createLinearGradient(0, 0, 0, h);

    if (mode === 'day') {
      grad.addColorStop(0.0, '#1e40af'); // Deep Zenith Blue
      grad.addColorStop(0.3, '#3b82f6'); // Sky Blue
      grad.addColorStop(0.65, '#93c5fd'); // Horizon Azure
      grad.addColorStop(0.85, '#e0f2fe'); // Atmospheric haze
      grad.addColorStop(1.0, '#cbd5e1'); // Ground horizon
    } else if (mode === 'sunset') {
      grad.addColorStop(0.0, '#1e1b4b'); // Deep Twilight
      grad.addColorStop(0.25, '#431407'); // Purple/Burgundy
      grad.addColorStop(0.5, '#c2410c'); // Radiant Orange
      grad.addColorStop(0.7, '#ea580c'); // Golden Amber
      grad.addColorStop(0.85, '#fbbf24'); // Sun horizon glare
      grad.addColorStop(1.0, '#78350f'); // Horizon ground
    } else { // Night
      grad.addColorStop(0.0, '#030712'); // Pitch Black Zenith
      grad.addColorStop(0.4, '#0b1329'); // Deep Midnight Blue
      grad.addColorStop(0.75, '#111c44'); // Horizon Glow
      grad.addColorStop(1.0, '#050a18'); // Ground
    }

    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);

    if (mode === 'night') {
      // Draw Stars
      ctx.fillStyle = '#ffffff';
      for (let i = 0; i < 200; i++) {
        const sx = Math.random() * w;
        const sy = Math.random() * (h * 0.7);
        const sr = Math.random() * 1.5 + 0.5;
        ctx.beginPath();
        ctx.arc(sx, sy, sr, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    if (this.skyTexture) {
      this.skyTexture.needsUpdate = true;
    }
  }

  buildLighting() {
    // 1. Hemisphere Light (Sky & Ground bounce)
    this.hemiLight = new THREE.HemisphereLight(0xe0f2fe, 0x1e293b, 0.85);
    this.envGroup.add(this.hemiLight);

    // 2. Primary Directional Sun / Key Light
    this.sunLight = new THREE.DirectionalLight(0xfffaed, 2.2);
    this.sunLight.position.set(65, 80, 50);
    this.sunLight.castShadow = true;
    this.sunLight.shadow.mapSize.width = 2048;
    this.sunLight.shadow.mapSize.height = 2048;
    this.sunLight.shadow.camera.near = 10;
    this.sunLight.shadow.camera.far = 280;
    this.sunLight.shadow.camera.left = -60;
    this.sunLight.shadow.camera.right = 60;
    this.sunLight.shadow.camera.top = 60;
    this.sunLight.shadow.camera.bottom = -60;
    this.sunLight.shadow.bias = -0.0001;
    this.sunLight.shadow.radius = 2.5; // Soft shadows
    this.envGroup.add(this.sunLight);

    // 3. Secondary Rim / Fill Light
    this.fillLight = new THREE.DirectionalLight(0x93c5fd, 0.65);
    this.fillLight.position.set(-60, 30, -50);
    this.envGroup.add(this.fillLight);
  }

  setTimeOfDay(mode) {
    this.timeOfDay = mode;
    this.updateSkyGradient(mode);

    if (mode === 'day') {
      this.hemiLight.color.setHex(0xe0f2fe);
      this.hemiLight.groundColor.setHex(0x334155);
      this.hemiLight.intensity = 0.95;

      this.sunLight.color.setHex(0xfffaed);
      this.sunLight.intensity = 2.2;
      this.sunLight.position.set(65, 80, 50);

      this.fillLight.color.setHex(0x93c5fd);
      this.fillLight.intensity = 0.65;
    } else if (mode === 'sunset') {
      this.hemiLight.color.setHex(0xfdba74);
      this.hemiLight.groundColor.setHex(0x451a03);
      this.hemiLight.intensity = 0.75;

      this.sunLight.color.setHex(0xf97316);
      this.sunLight.intensity = 2.6;
      this.sunLight.position.set(110, 22, -40); // Low grazing sunset sun

      this.fillLight.color.setHex(0x7c3aed);
      this.fillLight.intensity = 0.45;
    } else if (mode === 'night') {
      this.hemiLight.color.setHex(0x1e1b4b);
      this.hemiLight.groundColor.setHex(0x020617);
      this.hemiLight.intensity = 0.25;

      this.sunLight.color.setHex(0x60a5fa); // Cool moonlight
      this.sunLight.intensity = 0.4;
      this.sunLight.position.set(-45, 90, 45);

      this.fillLight.color.setHex(0x1e293b);
      this.fillLight.intensity = 0.15;
    }
  }
}
