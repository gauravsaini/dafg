import * as THREE from 'three';

/**
 * Scene, Environment, Runway, and Physical Lighting Setup for Boeing 747.
 */

export function setupScene(container, materials) {
    // 1. Three.js Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xd9e5f0);
    scene.fog = new THREE.FogExp2(0xd9e5f0, 0.0018);

    const w = (container && container.clientWidth > 0) ? container.clientWidth : (window.innerWidth || 1440);
    const h = (container && container.clientHeight > 0) ? container.clientHeight : (window.innerHeight || 900);

    // 2. Camera
    const camera = new THREE.PerspectiveCamera(
        48,
        w / h,
        0.5,
        1500
    );
    camera.position.set(42, 14, 45);

    // 3. Renderer with ACESFilmic Tone Mapping and Soft Shadows
    const renderer = new THREE.WebGLRenderer({
        antialias: true,
        powerPreference: 'high-performance',
        preserveDrawingBuffer: true, // Required for screenshots
    });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1.0, 2.0));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    if (container) {
        container.appendChild(renderer.domElement);
    } else {
        document.body.appendChild(renderer.domElement);
    }

    // 4. Runway / Airport Tarmac Ground Plane (Length: 1200m, Width: 120m)
    const runwayGeom = new THREE.PlaneGeometry(160, 1200, 32, 128);
    runwayGeom.rotateX(-Math.PI / 2);
    const runwayMesh = new THREE.Mesh(runwayGeom, materials.runway);
    runwayMesh.position.set(0, 0, 0);
    runwayMesh.receiveShadow = true;
    scene.add(runwayMesh);

    // Airport Grass Infield Surroundings
    const infieldGeom = new THREE.PlaneGeometry(1600, 1600);
    infieldGeom.rotateX(-Math.PI / 2);
    const infieldMat = new THREE.MeshStandardMaterial({
        color: 0x2b3d2b,
        roughness: 0.95,
        metalness: 0.05,
    });
    const infieldMesh = new THREE.Mesh(infieldGeom, infieldMat);
    infieldMesh.position.set(0, -0.05, 0);
    infieldMesh.receiveShadow = true;
    scene.add(infieldMesh);

    // Runway Edge Lights (Dual rows of glowing yellow/white marker lights)
    const edgeLightsGroup = new THREE.Group();
    const lightMarkerGeom = new THREE.CylinderGeometry(0.12, 0.16, 0.4, 8);
    const lightMarkerMat = new THREE.MeshStandardMaterial({
        color: 0xffea9f,
        emissive: 0xffcc33,
        emissiveIntensity: 3.0,
    });
    for (let z = -400; z <= 400; z += 25) {
        [-38, 38].forEach((lx) => {
            const marker = new THREE.Mesh(lightMarkerGeom, lightMarkerMat);
            marker.position.set(lx, 0.2, z);
            edgeLightsGroup.add(marker);
        });
    }
    scene.add(edgeLightsGroup);

    // 5. Environmental Physical Lighting
    // Ambient / Hemisphere Sky Light
    const hemiLight = new THREE.HemisphereLight(0xffffff, 0x556677, 0.75);
    hemiLight.position.set(0, 200, 0);
    scene.add(hemiLight);

    // Main Sun Directional Light with Shadow Frustum
    const sunLight = new THREE.DirectionalLight(0xfffaed, 2.2);
    sunLight.position.set(70, 90, 80);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.width = 2048;
    sunLight.shadow.mapSize.height = 2048;
    sunLight.shadow.camera.near = 10;
    sunLight.shadow.camera.far = 350;
    sunLight.shadow.camera.left = -60;
    sunLight.shadow.camera.right = 60;
    sunLight.shadow.camera.top = 60;
    sunLight.shadow.camera.bottom = -60;
    sunLight.shadow.bias = -0.0003;
    scene.add(sunLight);

    // Fill Light for Underbelly & Engine Details
    const fillLight = new THREE.DirectionalLight(0xd0e0f0, 0.65);
    fillLight.position.set(-60, 25, -40);
    scene.add(fillLight);

    // Airport Ramp Tower Floodlight
    const towerLight = new THREE.SpotLight(0xfffae0, 2.0, 200, Math.PI / 4, 0.5);
    towerLight.position.set(65, 38, -30);
    towerLight.target.position.set(0, 4, 0);
    towerLight.castShadow = true;
    scene.add(towerLight);
    scene.add(towerLight.target);

    // Lighting Presets Management (Day, Sunset, Night)
    const lightingModes = {
        day: () => {
            scene.background.set(0xd9e5f0);
            scene.fog.color.set(0xd9e5f0);
            scene.fog.density = 0.0018;
            sunLight.color.set(0xfffaed);
            sunLight.intensity = 2.2;
            sunLight.position.set(70, 90, 80);
            hemiLight.color.set(0xffffff);
            hemiLight.groundColor.set(0x556677);
            hemiLight.intensity = 0.75;
            renderer.toneMappingExposure = 1.15;
            lightMarkerMat.emissiveIntensity = 1.5;
        },
        sunset: () => {
            scene.background.set(0x3a2038);
            scene.fog.color.set(0x3a2038);
            scene.fog.density = 0.0022;
            sunLight.color.set(0xff7733);
            sunLight.intensity = 2.8;
            sunLight.position.set(110, 18, 40);
            hemiLight.color.set(0xff9966);
            hemiLight.groundColor.set(0x221133);
            hemiLight.intensity = 0.5;
            renderer.toneMappingExposure = 1.25;
            lightMarkerMat.emissiveIntensity = 4.0;
        },
        night: () => {
            scene.background.set(0x06080e);
            scene.fog.color.set(0x06080e);
            scene.fog.density = 0.003;
            sunLight.color.set(0x223355);
            sunLight.intensity = 0.25;
            sunLight.position.set(40, 50, -40);
            hemiLight.color.set(0x1a2433);
            hemiLight.groundColor.set(0x080c14);
            hemiLight.intensity = 0.25;
            renderer.toneMappingExposure = 1.45;
            lightMarkerMat.emissiveIntensity = 8.0;
        },
    };

    let currentLighting = 'day';
    const setLightingMode = (mode) => {
        if (lightingModes[mode]) {
            lightingModes[mode]();
            currentLighting = mode;
            // Update HUD lighting buttons
            document.querySelectorAll('.lighting-btn').forEach((b) => {
                if (b.dataset.mode === mode) b.classList.add('active');
                else b.classList.remove('active');
            });
        }
    };

    return {
        scene,
        camera,
        renderer,
        sunLight,
        hemiLight,
        setLightingMode,
        getLightingMode: () => currentLighting,
    };
}
