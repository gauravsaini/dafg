import * as THREE from 'three';

export class CameraSystem {
  constructor(camera, domElement) {
    this.camera = camera;
    this.domElement = domElement;

    // Viewpoint presets
    this.presets = {
      hero: {
        pos: new THREE.Vector3(42, 14, 48),
        target: new THREE.Vector3(0, 1, 4),
        name: 'Hero 3/4 View',
        desc: 'Classic airline promotional perspective highlighting the iconic hump and swept wings'
      },
      side: {
        pos: new THREE.Vector3(68, 4, 0),
        target: new THREE.Vector3(0, 1, 0),
        name: 'Side Profile',
        desc: 'True lateral elevation showcasing the full 70m fuselage length and double-deck curvature'
      },
      front: {
        pos: new THREE.Vector3(0, 3, 56),
        target: new THREE.Vector3(0, 2, 20),
        name: 'Front Head-On',
        desc: 'Direct head-on view emphasizing the 4 GEnx turbofan engines and 7° wing dihedral'
      },
      top: {
        pos: new THREE.Vector3(0, 95, -2),
        target: new THREE.Vector3(0, 0, -2),
        name: 'Top-Down Plan',
        desc: 'Aerodynamic planform displaying the 37.5° wing sweep and empennage geometry'
      },
      engine: {
        pos: new THREE.Vector3(-17, -1, 3),
        target: new THREE.Vector3(-12, -1.6, -4.5),
        name: 'Engine Nacelle',
        desc: 'High-bypass turbofan close-up: titanium fan blades, spinner spiral, and chevron exhaust'
      },
      cockpit: {
        pos: new THREE.Vector3(4.5, 4.2, 29.5),
        target: new THREE.Vector3(0, 3.2, 25.0),
        name: 'Cockpit & Nose',
        desc: '6-piece faceted windshield, wipers, radome curvature, and upper deck flight deck'
      },
      wingtip: {
        pos: new THREE.Vector3(-35, 4.5, -20),
        target: new THREE.Vector3(-31, 2.0, -23),
        name: 'Wingtip & Winglet',
        desc: 'Raked wingtip aerofoil, navigation light fixture, strobe flasher, and canoe fairings'
      },
      gear: {
        pos: new THREE.Vector3(-7.5, -4.8, 3.5),
        target: new THREE.Vector3(-3.5, -4.0, -3.0),
        name: 'Landing Gear System',
        desc: 'Multi-wheel bogie assemblies (18 wheels total), titanium oleo struts, and brake discs'
      },
      tail: {
        pos: new THREE.Vector3(12, 10, -46),
        target: new THREE.Vector3(0, 5, -28),
        name: 'Tail & Empennage',
        desc: 'Swept vertical stabilizer, double-hinged rudder, horizontal elevators, and APU exhaust'
      },
      takeoff: {
        pos: new THREE.Vector3(3.5, -5.2, 75),
        target: new THREE.Vector3(0, 2.0, 10),
        name: 'Takeoff Runway View',
        desc: 'Dramatic low-altitude runway angle showing taxi lights and touchdown markings'
      }
    };

    this.currentPresetKey = 'hero';
    this.targetPos = this.presets.hero.pos.clone();
    this.targetLookAt = this.presets.hero.target.clone();
    this.currentLookAt = this.targetLookAt.clone();

    this.isTransitioning = false;
    this.transitionSpeed = 4.0;
    this.isAutoOrbit = false;
    this.orbitAngle = 0;
    this.orbitRadius = 55;
    this.orbitHeight = 12;

    // Mouse Interaction
    this.isDragging = false;
    this.prevMousePos = { x: 0, y: 0 };
    this.spherical = new THREE.Spherical(55, Math.PI / 2.5, Math.PI / 4);

    this.initControls();
  }

  initControls() {
    const el = this.domElement;

    el.addEventListener('mousedown', (e) => {
      this.isDragging = true;
      this.isAutoOrbit = false;
      this.prevMousePos = { x: e.clientX, y: e.clientY };
    });

    window.addEventListener('mouseup', () => {
      this.isDragging = false;
    });

    window.addEventListener('mousemove', (e) => {
      if (!this.isDragging) return;
      const dx = (e.clientX - this.prevMousePos.x) * 0.005;
      const dy = (e.clientY - this.prevMousePos.y) * 0.005;

      this.spherical.theta -= dx;
      this.spherical.phi = Math.max(0.1, Math.min(Math.PI / 2 - 0.02, this.spherical.phi - dy));
      
      this.updateSphericalPosition();
      this.prevMousePos = { x: e.clientX, y: e.clientY };
    });

    el.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.isAutoOrbit = false;
      this.spherical.radius = Math.max(8, Math.min(180, this.spherical.radius + e.deltaY * 0.05));
      this.updateSphericalPosition();
    }, { passive: false });

    // Touch support for mobile/tablets
    let touchStartDist = 0;
    el.addEventListener('touchstart', (e) => {
      if (e.touches.length === 1) {
        this.isDragging = true;
        this.isAutoOrbit = false;
        this.prevMousePos = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      } else if (e.touches.length === 2) {
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        touchStartDist = Math.hypot(dx, dy);
      }
    });

    el.addEventListener('touchmove', (e) => {
      if (e.touches.length === 1 && this.isDragging) {
        const dx = (e.touches[0].clientX - this.prevMousePos.x) * 0.005;
        const dy = (e.touches[0].clientY - this.prevMousePos.y) * 0.005;
        this.spherical.theta -= dx;
        this.spherical.phi = Math.max(0.1, Math.min(Math.PI / 2 - 0.02, this.spherical.phi - dy));
        this.updateSphericalPosition();
        this.prevMousePos = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      } else if (e.touches.length === 2) {
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        const dist = Math.hypot(dx, dy);
        const factor = touchStartDist / dist;
        this.spherical.radius = Math.max(8, Math.min(180, this.spherical.radius * factor));
        touchStartDist = dist;
        this.updateSphericalPosition();
      }
    });

    el.addEventListener('touchend', () => {
      this.isDragging = false;
    });
  }

  updateSphericalPosition() {
    const offset = new THREE.Vector3().setFromSpherical(this.spherical);
    this.camera.position.copy(this.currentLookAt).add(offset);
    this.camera.lookAt(this.currentLookAt);
    this.targetPos.copy(this.camera.position);
  }

  setPreset(key) {
    const preset = this.presets[key];
    if (!preset) return;

    this.currentPresetKey = key;
    this.isAutoOrbit = false;
    this.targetPos.copy(preset.pos);
    this.targetLookAt.copy(preset.target);
    this.isTransitioning = true;

    // Recalculate spherical for smooth continuation
    const diff = preset.pos.clone().sub(preset.target);
    this.spherical.setFromVector3(diff);
  }

  toggleAutoOrbit() {
    this.isAutoOrbit = !this.isAutoOrbit;
    if (this.isAutoOrbit) {
      this.orbitAngle = this.spherical.theta;
      this.orbitRadius = Math.max(45, this.spherical.radius);
    }
    return this.isAutoOrbit;
  }

  update(delta) {
    if (this.isAutoOrbit) {
      this.orbitAngle += delta * 0.25;
      this.camera.position.x = Math.sin(this.orbitAngle) * this.orbitRadius;
      this.camera.position.z = Math.cos(this.orbitAngle) * this.orbitRadius;
      this.camera.position.y = THREE.MathUtils.lerp(this.camera.position.y, this.orbitHeight, delta * 2.0);
      this.currentLookAt.lerp(new THREE.Vector3(0, 2, 0), delta * 3.0);
      this.camera.lookAt(this.currentLookAt);
      return;
    }

    if (this.isTransitioning) {
      const step = delta * this.transitionSpeed;
      this.camera.position.lerp(this.targetPos, step);
      this.currentLookAt.lerp(this.targetLookAt, step);
      this.camera.lookAt(this.currentLookAt);

      if (this.camera.position.distanceTo(this.targetPos) < 0.1 && this.currentLookAt.distanceTo(this.targetLookAt) < 0.1) {
        this.camera.position.copy(this.targetPos);
        this.currentLookAt.copy(this.targetLookAt);
        this.isTransitioning = false;
      }
    }
  }

  getCurrentTelemetry() {
    return {
      x: this.camera.position.x.toFixed(1),
      y: this.camera.position.y.toFixed(1),
      z: this.camera.position.z.toFixed(1),
      distance: this.camera.position.distanceTo(this.currentLookAt).toFixed(1),
      preset: this.presets[this.currentPresetKey]?.name || 'Manual Orbit'
    };
  }
}
