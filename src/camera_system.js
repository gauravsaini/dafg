import * as THREE from 'three';

/**
 * Multi-Angle Camera Inspection System for Boeing 747.
 * Provides 10 curated inspection angles with smooth animated transitions,
 * keyboard shortcuts, HUD feedback, and screenshot capture.
 */

export const CAMERA_PRESETS = {
    hero: {
        id: 'hero',
        name: 'Hero 3/4 Perspective',
        description: 'Classic ramp beauty shot showing full aircraft, swept wings, and all 4 engines.',
        position: new THREE.Vector3(32, 16, 50),
        target: new THREE.Vector3(0, 5.2, 2.0),
        fov: 45,
    },
    cockpit: {
        id: 'cockpit',
        name: 'Cockpit & Hump Close-up',
        description: 'Detailed inspection of cockpit windshield, mullions, radome, and upper-deck hump.',
        position: new THREE.Vector3(8.0, 9.8, 35.0),
        target: new THREE.Vector3(0, 8.2, 28.8),
        fov: 36,
    },
    side: {
        id: 'side',
        name: 'Side Profile',
        description: 'Orthogonal side view highlighting fuselage length, hump contour, doors, and window belts.',
        position: new THREE.Vector3(72, 7.5, -5),
        target: new THREE.Vector3(0, 6.0, -5),
        fov: 44,
    },
    top: {
        id: 'top',
        name: 'Top-Down Planform',
        description: 'Aerial planform perspective exhibiting exact 37.5° wing sweep and aerodynamic layout.',
        position: new THREE.Vector3(0, 95, -6),
        target: new THREE.Vector3(0, 0, -6),
        fov: 44,
    },
    front: {
        id: 'front',
        name: 'Front Head-On',
        description: 'Head-on view revealing wing dihedral, 4 engine nacelles, and cockpit brow.',
        position: new THREE.Vector3(0, 6.8, 55),
        target: new THREE.Vector3(0, 6.0, 10),
        fov: 40,
    },
    gear: {
        id: 'gear',
        name: 'Landing Gear & Belly',
        description: 'Low-angle underbelly inspection of all 18 wheels, 5 bogies, and open gear doors.',
        position: new THREE.Vector3(16.0, 1.4, -3.2),
        target: new THREE.Vector3(0, 1.8, -3.2),
        fov: 50,
    },
    engines: {
        id: 'engines',
        name: 'Engines & Pylons',
        description: 'Close-up of port turbofan engines, spinner spiral, titanium blades, and chrome cowlings.',
        position: new THREE.Vector3(-6.0, 2.8, 12.0),
        target: new THREE.Vector3(-16.5, 3.5, -4.0),
        fov: 42,
    },
    winglet: {
        id: 'winglet',
        name: 'Wingtip & Winglet',
        description: 'High-detail inspection of starboard winglet, navigation lights, and slats.',
        position: new THREE.Vector3(36.0, 12.0, -18.0),
        target: new THREE.Vector3(32.2, 8.8, -18.0),
        fov: 38,
    },
    tail: {
        id: 'tail',
        name: 'Tail Empennage & APU',
        description: 'Inspection of the vertical fin with Boeing Blue livery, split rudder, and stabilizers.',
        position: new THREE.Vector3(-18.0, 20.0, -48.0),
        target: new THREE.Vector3(0, 12.0, -38.0),
        fov: 44,
    },
    cinematic_runway: {
        id: 'cinematic_runway',
        name: 'Cinematic Runway Low-Angle',
        description: 'Dramatic ground-level perspective from runway centerline gazing up at the Queen of the Skies.',
        position: new THREE.Vector3(-26.0, 1.6, 42.0),
        target: new THREE.Vector3(0, 7.0, 5.0),
        fov: 50,
    },
};

export class CameraSystem {
    constructor(camera, controls, renderer) {
        this.camera = camera;
        this.controls = controls;
        this.renderer = renderer;

        this.currentPresetId = 'hero';
        this.presets = CAMERA_PRESETS;

        this.isTransitioning = false;
        this.transitionStart = 0;
        this.transitionDuration = 1.2;
        this.startPos = new THREE.Vector3();
        this.targetPos = new THREE.Vector3();
        this.startLookAt = new THREE.Vector3();
        this.targetLookAt = new THREE.Vector3();
        this.startFov = 45;
        this.targetFov = 45;

        this.setupKeyboard();
    }

    setAngle(presetId, immediate = false) {
        const preset = this.presets[presetId];
        if (!preset) {
            console.warn(`Camera preset "${presetId}" not found`);
            return;
        }

        this.currentPresetId = presetId;

        if (immediate) {
            this.camera.position.copy(preset.position);
            this.camera.fov = preset.fov;
            this.camera.updateProjectionMatrix();
            if (this.controls) {
                this.controls.target.copy(preset.target);
                this.controls.update();
            }
            this.isTransitioning = false;
            this.updateHUD();
            return;
        }

        this.isTransitioning = true;
        this.transitionStart = performance.now();
        this.startPos.copy(this.camera.position);
        this.targetPos.copy(preset.position);

        if (this.controls) {
            this.startLookAt.copy(this.controls.target);
        } else {
            this.startLookAt.set(0, 5.2, 2.0);
        }
        this.targetLookAt.copy(preset.target);

        this.startFov = this.camera.fov;
        this.targetFov = preset.fov;

        this.updateHUD();
    }

    update() {
        if (!this.isTransitioning) return;

        const now = performance.now();
        const elapsed = (now - this.transitionStart) / 1000;
        const progress = Math.min(1.0, elapsed / this.transitionDuration);

        const t = progress < 0.5
            ? 4 * progress * progress * progress
            : 1 - Math.pow(-2 * progress + 2, 3) / 2;

        this.camera.position.lerpVectors(this.startPos, this.targetPos, t);
        if (this.controls) {
            this.controls.target.lerpVectors(this.startLookAt, this.targetLookAt, t);
            this.controls.update();
        }

        this.camera.fov = THREE.MathUtils.lerp(this.startFov, this.targetFov, t);
        this.camera.updateProjectionMatrix();

        if (progress >= 1.0) {
            this.isTransitioning = false;
            this.camera.position.copy(this.targetPos);
            if (this.controls) {
                this.controls.target.copy(this.targetLookAt);
                this.controls.update();
            }
        }
    }

    setupKeyboard() {
        window.addEventListener('keydown', (e) => {
            const keyMap = {
                '1': 'hero',
                '2': 'cockpit',
                '3': 'side',
                '4': 'top',
                '5': 'front',
                '6': 'gear',
                '7': 'engines',
                '8': 'winglet',
                '9': 'tail',
                '0': 'cinematic_runway',
            };

            if (keyMap[e.key]) {
                this.setAngle(keyMap[e.key]);
            }
        });
    }

    updateHUD() {
        const preset = this.presets[this.currentPresetId];
        const titleEl = document.getElementById('camera-angle-title');
        const descEl = document.getElementById('camera-angle-desc');
        const coordsEl = document.getElementById('camera-coords');

        if (titleEl && preset) titleEl.textContent = preset.name;
        if (descEl && preset) descEl.textContent = preset.description;
        if (coordsEl && preset) {
            coordsEl.textContent = `Pos: [${preset.position.x.toFixed(1)}, ${preset.position.y.toFixed(1)}, ${preset.position.z.toFixed(1)}] | LookAt: [${preset.target.x.toFixed(1)}, ${preset.target.y.toFixed(1)}, ${preset.target.z.toFixed(1)}]`;
        }

        document.querySelectorAll('.preset-btn').forEach((btn) => {
            if (btn.dataset.preset === this.currentPresetId) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    captureScreenshot(filename = 'boeing_747_screenshot.png') {
        if (!this.renderer) return null;
        this.renderer.render(this.camera.parent || this.camera, this.camera);
        const dataUrl = this.renderer.domElement.toDataURL('image/png');
        window.__lastScreenshot = dataUrl;
        return dataUrl;
    }
}
