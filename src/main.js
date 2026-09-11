import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createMaterials } from './materials.js';
import { createBoeing747 } from './boeing747.js';
import { CameraSystem, CAMERA_PRESETS } from './camera_system.js';
import { setupScene } from './scene_setup.js';

/**
 * Boeing 747 Realistic 3D Simulation Coordinator
 */

const container = document.getElementById('canvas-container');
const materials = createMaterials();
const sceneContext = setupScene(container, materials);
const { scene, camera, renderer, setLightingMode, getLightingMode } = sceneContext;

// Controls
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.maxPolarAngle = Math.PI / 2 - 0.02; // Don't clip through ground
controls.minDistance = 5;
controls.maxDistance = 250;
controls.target.set(0, 5, 0);

// Initialize Camera Inspection System
const cameraSystem = new CameraSystem(camera, controls, renderer);

// Build Boeing 747 3D Model
const aircraft = createBoeing747(materials);
scene.add(aircraft);

// Real-time animation clock
const clock = new THREE.Clock();
let autoRotate = false;

// Handle window resizing
window.addEventListener('resize', () => {
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
});

// UI Event Bindings
function setupUI() {
    // Preset camera angle buttons
    document.querySelectorAll('.preset-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const presetId = btn.dataset.preset;
            cameraSystem.setAngle(presetId);
        });
    });

    // Lighting mode buttons
    document.querySelectorAll('.lighting-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            setLightingMode(btn.dataset.mode);
        });
    });

    // Auto rotate toggle
    const autoRotateBtn = document.getElementById('toggle-orbit-btn');
    if (autoRotateBtn) {
        autoRotateBtn.addEventListener('click', () => {
            autoRotate = !autoRotate;
            autoRotateBtn.classList.toggle('active', autoRotate);
        });
    }

    // Screenshot capture button
    const screenshotBtn = document.getElementById('capture-btn');
    if (screenshotBtn) {
        screenshotBtn.addEventListener('click', () => {
            const dataUrl = cameraSystem.captureScreenshot(`boeing_747_${cameraSystem.currentPresetId}.png`);
            if (dataUrl) {
                const link = document.createElement('a');
                link.download = `boeing_747_${cameraSystem.currentPresetId}_${Date.now()}.png`;
                link.href = dataUrl;
                link.click();
            }
        });
    }

    cameraSystem.updateHUD();
}

setupUI();

// Render Loop
function animate() {
    requestAnimationFrame(animate);

    const delta = clock.getDelta();
    const elapsedTime = clock.getElapsedTime();

    // Update aircraft systems (fan spinning, strobe lights, beacons)
    if (aircraft.userData && aircraft.userData.update) {
        aircraft.userData.update(delta, elapsedTime);
    }

    // Update camera smooth transition
    cameraSystem.update();

    // Auto-orbit if active and not transitioning
    if (autoRotate && !cameraSystem.isTransitioning) {
        controls.autoRotate = true;
        controls.autoRotateSpeed = 1.0;
    } else {
        controls.autoRotate = false;
    }

    controls.update();
    renderer.render(scene, camera);
}

animate();

// Global verification and inspection hooks for automated testing
window.__boeing747 = {
    aircraft,
    materials,
    scene,
    camera,
    renderer,
    controls,
    cameraSystem,
    CAMERA_PRESETS,
    setAngle: (name, immediate = true) => cameraSystem.setAngle(name, immediate),
    setLightingMode: (mode) => setLightingMode(mode),
    getLightingMode: () => getLightingMode(),
    captureScreenshot: (name) => cameraSystem.captureScreenshot(name),
    captureAllAngles: async () => {
        const results = {};
        for (const [id, preset] of Object.entries(CAMERA_PRESETS)) {
            cameraSystem.setAngle(id, true);
            // Render 2 frames to ensure matrix updates
            renderer.render(scene, camera);
            renderer.render(scene, camera);
            results[id] = renderer.domElement.toDataURL('image/png');
        }
        return results;
    },
    isLoaded: true,
    metrics: {
        triangles: renderer.info.render.triangles,
        calls: renderer.info.render.calls,
        materialsCount: Object.keys(materials).length,
        engineFansCount: aircraft.userData.fanRotors.length,
        beaconsCount: aircraft.userData.beaconLights.length,
    },
};

console.log('Boeing 747 3D simulation initialized successfully.');
