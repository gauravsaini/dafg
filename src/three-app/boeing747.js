import * as THREE from 'three';
import {
  createFuselageTexture,
  createFuselageBumpMap,
  createWingTexture,
  createTurbineSpiralTexture,
  createTireTexture
} from './textures.js';

export class Boeing747 {
  constructor() {
    this.group = new THREE.Group();
    this.group.name = 'Boeing747-8';

    // Subsystem references for animation & controls
    this.turbines = [];
    this.beacons = [];
    this.strobes = [];
    this.navLights = [];
    this.landingLights = [];
    this.cabinLights = [];
    this.landingGears = [];
    this.movingSurfaces = {};

    // Animation state
    this.throttle = 0.35; // 0.0 to 1.0
    this.turbineAngle = 0;
    this.beaconTimer = 0;
    this.strobeTimer = 0;
    this.gearDeployed = 1.0; // 1.0 deployed, 0.0 retracted
    this.targetGear = 1.0;

    // Build PBR materials & 3D Geometry
    this.initMaterials();
    this.buildAircraft();
  }

  initMaterials() {
    // Textures
    this.fuselageTex = createFuselageTexture();
    this.fuselageBump = createFuselageBumpMap();
    this.wingTex = createWingTexture();
    this.turbineTex = createTurbineSpiralTexture();
    this.tireTex = createTireTexture();

    // Fuselage White Pearl PBR Material
    this.fuselageMaterial = new THREE.MeshStandardMaterial({
      map: this.fuselageTex,
      bumpMap: this.fuselageBump,
      bumpScale: 0.04,
      roughness: 0.22,
      metalness: 0.15,
      envMapIntensity: 1.2
    });

    // Polished Aluminum / Chrome (Leading edges, engine lips, pylon trim)
    this.chromeMaterial = new THREE.MeshStandardMaterial({
      color: 0xe2e8f0,
      roughness: 0.08,
      metalness: 0.92,
      envMapIntensity: 2.0
    });

    // Dark Titanium / Inconel Engine Exhausts & Nozzles
    this.titaniumMaterial = new THREE.MeshStandardMaterial({
      color: 0x334155,
      roughness: 0.45,
      metalness: 0.85,
      envMapIntensity: 1.0
    });

    // Wings & Stabilizers Boeing Gray Material
    this.wingMaterial = new THREE.MeshStandardMaterial({
      map: this.wingTex,
      roughness: 0.38,
      metalness: 0.25,
      envMapIntensity: 1.0
    });

    // Dark Cockpit Tinted Glass
    this.glassMaterial = new THREE.MeshPhysicalMaterial({
      color: 0x0a1118,
      roughness: 0.05,
      metalness: 0.2,
      transmission: 0.85,
      ior: 1.52,
      transparent: true,
      opacity: 0.92,
      reflectivity: 0.9
    });

    // Passenger Window Night Emissive Material
    this.windowEmissiveMaterial = new THREE.MeshStandardMaterial({
      color: 0xfffbeb,
      emissive: 0xfef08a,
      emissiveIntensity: 0.0,
      roughness: 0.3
    });

    // Rubber Tires
    this.tireMaterial = new THREE.MeshStandardMaterial({
      map: this.tireTex,
      roughness: 0.85,
      metalness: 0.05
    });

    // Aircraft Wheel Rims / Alloy
    this.rimMaterial = new THREE.MeshStandardMaterial({
      color: 0x94a3b8,
      roughness: 0.25,
      metalness: 0.85
    });

    // Turbine Fan Blades (Graphite/Titanium)
    this.fanBladeMaterial = new THREE.MeshStandardMaterial({
      color: 0x1e293b,
      roughness: 0.2,
      metalness: 0.95
    });

    // Spinner Cone Material
    this.spinnerMaterial = new THREE.MeshStandardMaterial({
      map: this.turbineTex,
      roughness: 0.25,
      metalness: 0.7
    });
  }

  buildAircraft() {
    this.buildFuselage();
    this.buildCockpit();
    this.buildWings();
    this.buildEngines();
    this.buildEmpennage();
    this.buildLandingGears();
    this.buildLighting();
  }

  buildFuselage() {
    this.fuselageGroup = new THREE.Group();
    this.fuselageGroup.name = 'Fuselage_Assembly';

    // 1. Main Tube Body (scaled to ~70m aircraft length, radius 3.25m)
    // We build the authentic 747 fuselage profile using lofted Lathe / Loft points
    const points = [];
    // Nose Radome curve
    points.push(new THREE.Vector2(0.0, 32.0));
    points.push(new THREE.Vector2(0.8, 31.2));
    points.push(new THREE.Vector2(1.8, 29.8));
    points.push(new THREE.Vector2(2.6, 27.5));
    points.push(new THREE.Vector2(3.1, 24.5));
    points.push(new THREE.Vector2(3.25, 20.0));
    
    // Constant section
    points.push(new THREE.Vector2(3.25, -15.0));

    // Aft fuselage tapering up
    points.push(new THREE.Vector2(3.1, -22.0));
    points.push(new THREE.Vector2(2.6, -28.0));
    points.push(new THREE.Vector2(1.9, -32.5));
    points.push(new THREE.Vector2(1.0, -35.0));
    points.push(new THREE.Vector2(0.35, -36.5)); // APU exhaust orifice

    const latheGeo = new THREE.LatheGeometry(points, 48);
    // Rotate to align along Z axis (nose pointing +Z, tail pointing -Z)
    latheGeo.rotateX(Math.PI / 2);

    const mainBody = new THREE.Mesh(latheGeo, this.fuselageMaterial);
    mainBody.castShadow = true;
    mainBody.receiveShadow = true;
    this.fuselageGroup.add(mainBody);

    // 2. Iconic 747 Upper Deck "Hump"
    // The upper deck bubble sits on top of forward fuselage (Z: 5 to 26, Y: 1.5 to 5.2)
    const humpShape = new THREE.Shape();
    humpShape.moveTo(0, 0);
    humpShape.quadraticCurveTo(2.4, 0, 2.4, 2.2);
    humpShape.quadraticCurveTo(1.6, 3.2, 0, 3.2);
    humpShape.quadraticCurveTo(-1.6, 3.2, -2.4, 2.2);
    humpShape.quadraticCurveTo(-2.4, 0, 0, 0);

    // Lofted geometry for hump with smooth aerodynamic taper
    const humpCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, 2.3, 27.0), // Cockpit brow start
      new THREE.Vector3(0, 2.8, 24.0), // Above cockpit
      new THREE.Vector3(0, 3.1, 18.0), // Upper deck max height
      new THREE.Vector3(0, 2.8, 10.0), // Mid lounge
      new THREE.Vector3(0, 2.3, 2.0),  // Fairing blend start
      new THREE.Vector3(0, 1.8, -4.0)  // Tail blend
    ]);

    const humpGeo = new THREE.TubeGeometry(humpCurve, 32, 2.2, 24, false);
    // Scale X to flatten sides
    humpGeo.scale(1.25, 0.95, 1.0);
    const humpMesh = new THREE.Mesh(humpGeo, this.fuselageMaterial);
    humpMesh.castShadow = true;
    humpMesh.receiveShadow = true;
    this.fuselageGroup.add(humpMesh);

    // 3. Wing Root Fairing / Belly Fairing (protects main gear wells & aerodynamic transition)
    const fairingGeo = new THREE.BoxGeometry(7.2, 2.2, 22.0);
    fairingGeo.translate(0, -1.8, 2.0);
    const fairingMesh = new THREE.Mesh(fairingGeo, this.fuselageMaterial);
    fairingMesh.castShadow = true;
    this.fuselageGroup.add(fairingMesh);

    // 4. APU Tail Cone & Exhaust Pipe
    const apuGeo = new THREE.CylinderGeometry(0.35, 0.45, 1.8, 24, 1, true);
    apuGeo.rotateX(Math.PI / 2);
    apuGeo.translate(0, 0.3, -36.6);
    const apuMesh = new THREE.Mesh(apuGeo, this.titaniumMaterial);
    this.fuselageGroup.add(apuMesh);

    this.group.add(this.fuselageGroup);
  }

  buildCockpit() {
    const cockpitGroup = new THREE.Group();
    cockpitGroup.name = 'Cockpit_Assembly';

    // 6-Piece Faceted 747 Windshield Glass
    // 2 Center panels, 2 Side panels, 2 Aft quarter windows
    const windshieldFrames = new THREE.Group();

    // Front Center Left & Right
    const centerWinGeo = new THREE.PlaneGeometry(1.2, 0.75);
    
    // Left Front
    const winFL = new THREE.Mesh(centerWinGeo, this.glassMaterial);
    winFL.position.set(0.65, 3.35, 25.8);
    winFL.rotation.set(-0.55, 0.35, -0.18);
    windshieldFrames.add(winFL);

    // Right Front
    const winFR = new THREE.Mesh(centerWinGeo, this.glassMaterial);
    winFR.position.set(-0.65, 3.35, 25.8);
    winFR.rotation.set(-0.55, -0.35, 0.18);
    windshieldFrames.add(winFR);

    // Left Side Windshield
    const sideWinGeo = new THREE.PlaneGeometry(1.4, 0.68);
    const winSL = new THREE.Mesh(sideWinGeo, this.glassMaterial);
    winSL.position.set(1.55, 3.25, 24.8);
    winSL.rotation.set(-0.45, 0.95, -0.35);
    windshieldFrames.add(winSL);

    // Right Side Windshield
    const winSR = new THREE.Mesh(sideWinGeo, this.glassMaterial);
    winSR.position.set(-1.55, 3.25, 24.8);
    winSR.rotation.set(-0.45, -0.95, 0.35);
    windshieldFrames.add(winSR);

    // Left Aft Sliding Window
    const aftWinGeo = new THREE.PlaneGeometry(1.1, 0.62);
    const winAL = new THREE.Mesh(aftWinGeo, this.glassMaterial);
    winAL.position.set(2.05, 3.15, 23.6);
    winAL.rotation.set(-0.3, 1.45, -0.2);
    windshieldFrames.add(winAL);

    // Right Aft Sliding Window
    const winAR = new THREE.Mesh(aftWinGeo, this.glassMaterial);
    winAR.position.set(-2.05, 3.15, 23.6);
    winAR.rotation.set(-0.3, -1.45, 0.2);
    windshieldFrames.add(winAR);

    // Windshield frame post trim (Chrome / Dark Metal)
    const postGeo = new THREE.BoxGeometry(0.08, 0.85, 0.08);
    const postCenter = new THREE.Mesh(postGeo, this.chromeMaterial);
    postCenter.position.set(0, 3.35, 26.0);
    postCenter.rotation.x = -0.55;
    windshieldFrames.add(postCenter);

    // Wiper Blades
    const wiperGeo = new THREE.BoxGeometry(0.03, 0.5, 0.03);
    const wiperL = new THREE.Mesh(wiperGeo, this.chromeMaterial);
    wiperL.position.set(0.65, 3.25, 25.85);
    wiperL.rotation.set(-0.55, 0.35, 0.3);
    windshieldFrames.add(wiperL);

    const wiperR = new THREE.Mesh(wiperGeo, this.chromeMaterial);
    wiperR.position.set(-0.65, 3.25, 25.85);
    wiperR.rotation.set(-0.55, -0.35, -0.3);
    windshieldFrames.add(wiperR);

    // Instrument Glare Shield & Pilot Silhouette hints
    const glareGeo = new THREE.BoxGeometry(2.4, 0.2, 1.5);
    const glareMesh = new THREE.Mesh(glareGeo, this.fanBladeMaterial);
    glareMesh.position.set(0, 2.9, 24.8);
    glareMesh.rotation.x = 0.2;
    windshieldFrames.add(glareMesh);

    cockpitGroup.add(windshieldFrames);
    this.group.add(cockpitGroup);
  }

  buildWings() {
    this.wingsGroup = new THREE.Group();
    this.wingsGroup.name = 'Wings_Assembly';

    // Authentic Boeing 747 Wing Specifications:
    // Wingspan: ~68.4m, Sweep: 37.5°, Dihedral: ~7°, Root chord: ~16m, Tip chord: ~3.5m
    const makeWing = (isRight = false) => {
      const side = isRight ? -1 : 1;
      const wing = new THREE.Group();
      wing.name = isRight ? 'Wing_Starboard' : 'Wing_Port';

      // 1. Wing Main Airfoil Geometry
      // We build a swept, tapered, lofted wing panel using ExtrudeGeometry / Custom geometry
      const wingShape = new THREE.Shape();
      // Supercritical Airfoil profile
      wingShape.moveTo(0, 0);
      wingShape.bezierCurveTo(3.5, 0.8, 10.0, 0.7, 14.0, 0.0); // Upper camber
      wingShape.lineTo(14.0, -0.25); // Trailing edge
      wingShape.bezierCurveTo(9.0, -0.4, 3.0, -0.5, 0.0, 0.0); // Lower surface

      // Create Wing Mesh via lofted segments
      const wingGeo = new THREE.BufferGeometry();
      const spanSegments = 16;
      const chordSegments = 16;
      const vertices = [];
      const normals = [];
      const uvs = [];
      const indices = [];

      const wingSpan = 31.5; // Half span
      const sweepAngle = (37.5 * Math.PI) / 180;
      const dihedralAngle = (6.5 * Math.PI) / 180;

      for (let i = 0; i <= spanSegments; i++) {
        const t = i / spanSegments;
        const xPos = t * wingSpan * side;
        const zSweep = -Math.tan(sweepAngle) * (t * wingSpan);
        const yDihedral = Math.sin(dihedralAngle) * (t * wingSpan) - 1.2;
        const chord = 14.0 * (1 - t * 0.72); // Taper ratio ~0.28
        const thickness = (1 - t * 0.65) * 1.35;

        for (let j = 0; j <= chordSegments; j++) {
          const u = j / chordSegments;
          const zChord = (u - 0.25) * chord;
          
          // Airfoil profile curve equation
          let yProfile = 0;
          if (u < 0.25) {
            yProfile = Math.sqrt(u / 0.25) * 0.8 * thickness;
          } else {
            yProfile = (1 - ((u - 0.25) / 0.75)) * 0.8 * thickness;
          }
          // Lower or upper surface
          const isLower = j > chordSegments / 2;
          const y = isLower ? -yProfile * 0.45 : yProfile;

          vertices.push(xPos, yDihedral + y, zSweep + zChord);
          normals.push(0, isLower ? -1 : 1, 0);
          uvs.push(t, u);
        }
      }

      for (let i = 0; i < spanSegments; i++) {
        for (let j = 0; j < chordSegments; j++) {
          const a = i * (chordSegments + 1) + j;
          const b = (i + 1) * (chordSegments + 1) + j;
          const c = (i + 1) * (chordSegments + 1) + (j + 1);
          const d = i * (chordSegments + 1) + (j + 1);

          if (!isRight) {
            indices.push(a, b, d);
            indices.push(b, c, d);
          } else {
            indices.push(a, d, b);
            indices.push(b, d, c);
          }
        }
      }

      wingGeo.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
      wingGeo.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
      wingGeo.setIndex(indices);
      wingGeo.computeVertexNormals();

      const wingMesh = new THREE.Mesh(wingGeo, this.wingMaterial);
      wingMesh.castShadow = true;
      wingMesh.receiveShadow = true;
      wing.add(wingMesh);

      // 2. Polished Chrome Leading Edge Anti-Ice Slat Trim
      const slatGeo = new THREE.CylinderGeometry(0.2, 0.35, wingSpan * 0.98, 12, 1);
      slatGeo.rotateZ(Math.PI / 2);
      slatGeo.rotateY(isRight ? sweepAngle : -sweepAngle);
      const slatMesh = new THREE.Mesh(slatGeo, this.chromeMaterial);
      slatMesh.position.set(
        (wingSpan * 0.5) * side,
        (Math.sin(dihedralAngle) * (wingSpan * 0.5)) - 1.0,
        -(Math.tan(sweepAngle) * (wingSpan * 0.5)) + 3.2
      );
      wing.add(slatMesh);

      // 3. Flap Track Fairings (Canoe Fairings) - 4 per wing
      const fairingX = [7.5, 13.5, 19.5, 25.5];
      fairingX.forEach((spanX, idx) => {
        const t = spanX / wingSpan;
        const posX = spanX * side;
        const posY = Math.sin(dihedralAngle) * spanX - 1.7;
        const posZ = -Math.tan(sweepAngle) * spanX - (idx === 0 ? 5.5 : 4.0);

        const canoeGeo = new THREE.ConeGeometry(0.4, 4.5, 16);
        canoeGeo.rotateX(-Math.PI / 2);
        canoeGeo.scale(0.85, 1.2, 1.0);
        const canoeMesh = new THREE.Mesh(canoeGeo, this.wingMaterial);
        canoeMesh.position.set(posX, posY, posZ);
        canoeMesh.castShadow = true;
        wing.add(canoeMesh);
      });

      // 4. Wingtips: 747-8 Raked Wingtip / Blended Winglet
      const wingletGroup = new THREE.Group();
      const tipX = wingSpan * side;
      const tipY = Math.sin(dihedralAngle) * wingSpan - 1.2;
      const tipZ = -Math.tan(sweepAngle) * wingSpan;

      const wingletGeo = new THREE.BoxGeometry(0.35, 3.8, 2.2);
      wingletGeo.translate(0, 1.8, -0.5);
      const wingletMesh = new THREE.Mesh(wingletGeo, this.wingMaterial);
      wingletMesh.rotation.z = side * 0.45; // Canted upward & outward
      wingletMesh.rotation.y = side * -0.2;
      wingletMesh.castShadow = true;
      wingletGroup.add(wingletMesh);

      // Chrome Winglet leading edge
      const tipChromeGeo = new THREE.CylinderGeometry(0.12, 0.12, 3.8, 8);
      const tipChrome = new THREE.Mesh(tipChromeGeo, this.chromeMaterial);
      tipChrome.position.set(side * 0.8, 1.8, 0.6);
      tipChrome.rotation.z = side * 0.45;
      wingletGroup.add(tipChrome);

      wingletGroup.position.set(tipX, tipY, tipZ);
      wing.add(wingletGroup);

      return wing;
    };

    this.wingPort = makeWing(false);
    this.wingStarboard = makeWing(true);

    this.wingsGroup.add(this.wingPort);
    this.wingsGroup.add(this.wingStarboard);
    this.group.add(this.wingsGroup);
  }

  buildEngines() {
    this.enginesGroup = new THREE.Group();
    this.enginesGroup.name = 'Engines_Assembly';

    // 4x High-Bypass Turbofans (Engines 1 & 2 on Port, Engines 3 & 4 on Starboard)
    // Engine 1: Outboard Port (-21.5)
    // Engine 2: Inboard Port (-11.5)
    // Engine 3: Inboard Starboard (11.5)
    // Engine 4: Outboard Starboard (21.5)
    const engineSpecs = [
      { id: 'ENG1', x: -21.5, z: -11.0, y: -0.2, isRight: false },
      { id: 'ENG2', x: -11.8, z: -4.5, y: -1.6, isRight: false },
      { id: 'ENG3', x: 11.8, z: -4.5, y: -1.6, isRight: true },
      { id: 'ENG4', x: 21.5, z: -11.0, y: -0.2, isRight: true }
    ];

    engineSpecs.forEach((spec, idx) => {
      const nacelle = new THREE.Group();
      nacelle.name = ;

      // 1. Aerodynamic Pylon Strut (attaches engine forward and below wing)
      const pylonGeo = new THREE.BoxGeometry(0.65, 2.2, 5.5);
      pylonGeo.translate(0, 0.8, -0.4);
      const pylonMesh = new THREE.Mesh(pylonGeo, this.wingMaterial);
      pylonMesh.castShadow = true;
      nacelle.add(pylonMesh);

      // 2. Outer Engine Cowling (Nacelle Body)
      // High-bypass ratio turbofan diameter ~3.2m, length ~5.8m
      const cowlGeo = new THREE.CylinderGeometry(1.62, 1.55, 4.8, 36, 1, true);
      cowlGeo.rotateX(Math.PI / 2);
      const cowlMesh = new THREE.Mesh(cowlGeo, this.fuselageMaterial);
      cowlMesh.castShadow = true;
      nacelle.add(cowlMesh);

      // Inner Acoustic Liner Barrel
      const innerGeo = new THREE.CylinderGeometry(1.54, 1.48, 4.6, 36, 1, true);
      innerGeo.rotateX(Math.PI / 2);
      const innerMesh = new THREE.Mesh(innerGeo, this.titaniumMaterial);
      nacelle.add(innerMesh);

      // 3. Polished Chrome Cowl Lip (Intake highlight)
      const lipGeo = new THREE.TorusGeometry(1.58, 0.12, 16, 48);
      const lipMesh = new THREE.Mesh(lipGeo, this.chromeMaterial);
      lipMesh.position.z = 2.4;
      nacelle.add(lipMesh);

      // 4. Chevron Noise-Reduction Serrated Trailing Edges (747-8 GEnx feature!)
      const chevronGroup = new THREE.Group();
      const chevronCount = 18;
      for (let c = 0; c < chevronCount; c++) {
        const ang = (c / chevronCount) * Math.PI * 2;
        const triShape = new THREE.Shape();
        triShape.moveTo(-0.15, 0);
        triShape.lineTo(0.15, 0);
        triShape.lineTo(0, -0.45);
        triShape.closePath();

        const triGeo = new THREE.ShapeGeometry(triShape);
        const triMesh = new THREE.Mesh(triGeo, this.fuselageMaterial);
        triMesh.position.set(Math.cos(ang) * 1.55, Math.sin(ang) * 1.55, -2.4);
        triMesh.rotation.z = ang - Math.PI / 2;
        triMesh.rotation.x = 0.15;
        chevronGroup.add(triMesh);
      }
      nacelle.add(chevronGroup);

      // 5. Core Exhaust Nozzle & Centerbody Turbine Plug
      const exhaustGeo = new THREE.CylinderGeometry(0.85, 0.95, 1.8, 24);
      exhaustGeo.rotateX(Math.PI / 2);
      exhaustGeo.translate(0, 0, -2.9);
      const exhaustMesh = new THREE.Mesh(exhaustGeo, this.titaniumMaterial);
      nacelle.add(exhaustMesh);

      const plugGeo = new THREE.ConeGeometry(0.45, 1.6, 24);
      plugGeo.rotateX(-Math.PI / 2);
      plugGeo.translate(0, 0, -3.8);
      const plugMesh = new THREE.Mesh(plugGeo, this.titaniumMaterial);
      nacelle.add(plugMesh);

      // 6. Rotating Fan Rotor & 22 3D Titanium Fan Blades
      const rotorGroup = new THREE.Group();
      rotorGroup.name = ;
      rotorGroup.position.z = 1.4;

      // Central Spinner Cone with Spiral Swirl
      const spinnerGeo = new THREE.ConeGeometry(0.45, 1.4, 24);
      spinnerGeo.rotateX(Math.PI / 2);
      spinnerGeo.translate(0, 0, 0.7);
      const spinnerMesh = new THREE.Mesh(spinnerGeo, this.spinnerMaterial);
      rotorGroup.add(spinnerMesh);

      // 22 Wide-chord swept titanium fan blades
      const bladeCount = 22;
      for (let b = 0; b < bladeCount; b++) {
        const bAng = (b / bladeCount) * Math.PI * 2;
        const bladeGeo = new THREE.BoxGeometry(0.12, 1.15, 0.35);
        bladeGeo.translate(0, 0.65, 0);
        const bladeMesh = new THREE.Mesh(bladeGeo, this.fanBladeMaterial);
        bladeMesh.rotation.z = bAng;
        bladeMesh.rotation.y = 0.45; // Aerodynamic pitch angle
        rotorGroup.add(bladeMesh);
      }

      nacelle.add(rotorGroup);
      this.turbines.push(rotorGroup);

      // Position engine assembly in world
      nacelle.position.set(spec.x, spec.y, spec.z);
      this.enginesGroup.add(nacelle);
    });

    this.group.add(this.enginesGroup);
  }

  buildEmpennage() {
    this.empennageGroup = new THREE.Group();
    this.empennageGroup.name = 'Empennage_Assembly';

    // 1. Swept Vertical Stabilizer (Fin) & Double-Hinged Rudder
    // Height ~10.5m, 45° sweep angle
    const finGroup = new THREE.Group();
    finGroup.position.set(0, 3.2, -26.5);

    const finShape = new THREE.Shape();
    finShape.moveTo(0, 0);
    finShape.lineTo(0, 10.5); // Fin tip
    finShape.lineTo(-3.8, 9.8); // Trailing tip
    finShape.lineTo(-8.5, 0); // Root trailing edge
    finShape.closePath();

    const extrudeSettings = {
      depth: 0.6,
      bevelEnabled: true,
      bevelSegments: 3,
      steps: 1,
      bevelSize: 0.15,
      bevelThickness: 0.15
    };

    const finGeo = new THREE.ExtrudeGeometry(finShape, extrudeSettings);
    finGeo.translate(0, 0, -0.3);
    finGeo.rotateY(Math.PI / 2);
    const finMesh = new THREE.Mesh(finGeo, this.fuselageMaterial);
    finMesh.castShadow = true;
    finGroup.add(finMesh);

    // Polished Chrome Leading Edge of Fin
    const finLeadingGeo = new THREE.CylinderGeometry(0.12, 0.22, 11.2, 12);
    finLeadingGeo.rotateZ(0.42);
    finLeadingGeo.translate(-0.1, 5.2, 2.3);
    const finLeading = new THREE.Mesh(finLeadingGeo, this.chromeMaterial);
    finGroup.add(finLeading);

    this.empennageGroup.add(finGroup);

    // 2. Horizontal Stabilizers (Port & Starboard)
    // Span ~22m, 37.5° sweep, ~7° dihedral
    const makeHStab = (isRight = false) => {
      const side = isRight ? -1 : 1;
      const hStab = new THREE.Group();
      const hSpan = 11.2;
      const hSweep = (37.5 * Math.PI) / 180;
      const hDihedral = (7.0 * Math.PI) / 180;

      const hStabShape = new THREE.Shape();
      hStabShape.moveTo(0, 0);
      hStabShape.lineTo(0, 4.2);
      hStabShape.lineTo(hSpan * side, 4.2 - Math.tan(hSweep) * hSpan);
      hStabShape.lineTo(hSpan * side, 2.8 - Math.tan(hSweep) * hSpan);
      hStabShape.closePath();

      const hGeo = new THREE.BoxGeometry(hSpan, 0.35, 4.2);
      hGeo.translate((hSpan / 2) * side, 0, 0);
      hGeo.rotateY(side * -0.55);
      hGeo.rotateZ(side * 0.12);

      const hMesh = new THREE.Mesh(hGeo, this.wingMaterial);
      hMesh.castShadow = true;
      hStab.add(hMesh);

      // Chrome Leading edge
      const hLeadGeo = new THREE.CylinderGeometry(0.1, 0.18, hSpan * 0.95, 8);
      hLeadGeo.rotateZ(Math.PI / 2);
      hLeadGeo.rotateY(side * -0.55);
      const hLead = new THREE.Mesh(hLeadGeo, this.chromeMaterial);
      hLead.position.set((hSpan * 0.5) * side, 0.15, 1.8);
      hStab.add(hLead);

      return hStab;
    };

    const hStabPort = makeHStab(false);
    hStabPort.position.set(0, 1.2, -31.5);
    const hStabStarboard = makeHStab(true);
    hStabStarboard.position.set(0, 1.2, -31.5);

    this.empennageGroup.add(hStabPort);
    this.empennageGroup.add(hStabStarboard);

    this.group.add(this.empennageGroup);
  }

  buildLandingGears() {
    this.landingGearGroup = new THREE.Group();
    this.landingGearGroup.name = 'LandingGear_Assembly';

    // 1. Nose Landing Gear (Dual Wheels + Oleo Strut + Taxi Lights)
    const noseGear = new THREE.Group();
    noseGear.name = 'NoseLandingGear';
    noseGear.position.set(0, -3.2, 23.5);

    // Main Oleo Strut
    const noseStrutGeo = new THREE.CylinderGeometry(0.18, 0.22, 3.8, 16);
    const noseStrut = new THREE.Mesh(noseStrutGeo, this.chromeMaterial);
    noseStrut.position.y = -1.9;
    noseGear.add(noseStrut);

    // Torque Links / Scissor Hinge
    const torqueGeo = new THREE.BoxGeometry(0.1, 0.8, 0.15);
    const torqueMesh = new THREE.Mesh(torqueGeo, this.chromeMaterial);
    torqueMesh.position.set(0, -1.8, 0.3);
    torqueMesh.rotation.x = 0.5;
    noseGear.add(torqueMesh);

    // Axle
    const noseAxleGeo = new THREE.CylinderGeometry(0.1, 0.1, 1.2, 12);
    noseAxleGeo.rotateZ(Math.PI / 2);
    noseAxleGeo.translate(0, -3.7, 0);
    const noseAxle = new THREE.Mesh(noseAxleGeo, this.chromeMaterial);
    noseGear.add(noseAxle);

    // 2 Nose Wheels
    [-0.45, 0.45].forEach(xOff => {
      const tireGeo = new THREE.CylinderGeometry(0.72, 0.72, 0.35, 24);
      tireGeo.rotateZ(Math.PI / 2);
      const tire = new THREE.Mesh(tireGeo, this.tireMaterial);
      tire.position.set(xOff, -3.7, 0);
      tire.castShadow = true;
      noseGear.add(tire);

      const rimGeo = new THREE.CylinderGeometry(0.42, 0.42, 0.36, 16);
      rimGeo.rotateZ(Math.PI / 2);
      const rim = new THREE.Mesh(rimGeo, this.rimMaterial);
      rim.position.set(xOff, -3.7, 0);
      noseGear.add(rim);
    });

    this.landingGearGroup.add(noseGear);
    this.landingGears.push(noseGear);

    // 2. 4 Main Landing Gear Bogies (2 Wing Gear + 2 Body Gear = 16 Wheels!)
    const mainGearConfigs = [
      { name: 'WingGear_Port', x: -5.4, z: -1.8, y: -3.2 },
      { name: 'WingGear_Starboard', x: 5.4, z: -1.8, y: -3.2 },
      { name: 'BodyGear_Port', x: -2.3, z: -4.8, y: -3.2 },
      { name: 'BodyGear_Starboard', x: 2.3, z: -4.8, y: -3.2 }
    ];

    mainGearConfigs.forEach(cfg => {
      const bogieAssembly = new THREE.Group();
      bogieAssembly.name = cfg.name;
      bogieAssembly.position.set(cfg.x, cfg.y, cfg.z);

      // Heavy Duty Main Oleo Shock Strut
      const mainStrutGeo = new THREE.CylinderGeometry(0.28, 0.32, 4.2, 16);
      const mainStrut = new THREE.Mesh(mainStrutGeo, this.chromeMaterial);
      mainStrut.position.y = -2.1;
      bogieAssembly.add(mainStrut);

      // Bogie Beam (Horizontal pivot arm holding 4 wheels)
      const bogieBeamGeo = new THREE.BoxGeometry(0.4, 0.35, 2.8);
      const bogieBeam = new THREE.Mesh(bogieBeamGeo, this.titaniumMaterial);
      bogieBeam.position.set(0, -4.1, 0);
      bogieBeam.rotation.x = -0.08; // Typical 747 bogie slight tilt
      bogieAssembly.add(bogieBeam);

      // 4 Wheels per Bogie (Front Pair + Rear Pair)
      const wheelOffsets = [
        { x: -0.65, z: 0.95 },
        { x: 0.65, z: 0.95 },
        { x: -0.65, z: -0.95 },
        { x: 0.65, z: -0.95 }
      ];

      wheelOffsets.forEach(wOff => {
        // Main Wheel Tire (Diameter ~1.3m)
        const tireGeo = new THREE.CylinderGeometry(0.85, 0.85, 0.42, 28);
        tireGeo.rotateZ(Math.PI / 2);
        const tire = new THREE.Mesh(tireGeo, this.tireMaterial);
        tire.position.set(wOff.x, -4.1, wOff.z);
        tire.castShadow = true;
        bogieAssembly.add(tire);

        // Alloy Rim with Brake Caliper Hub
        const rimGeo = new THREE.CylinderGeometry(0.5, 0.5, 0.44, 20);
        rimGeo.rotateZ(Math.PI / 2);
        const rim = new THREE.Mesh(rimGeo, this.rimMaterial);
        rim.position.set(wOff.x, -4.1, wOff.z);
        bogieAssembly.add(rim);

        // Brake rotor disc
        const brakeGeo = new THREE.CylinderGeometry(0.38, 0.38, 0.46, 16);
        brakeGeo.rotateZ(Math.PI / 2);
        const brake = new THREE.Mesh(brakeGeo, this.titaniumMaterial);
        brake.position.set(wOff.x * 0.6, -4.1, wOff.z);
        bogieAssembly.add(brake);
      });

      this.landingGearGroup.add(bogieAssembly);
      this.landingGears.push(bogieAssembly);
    });

    this.group.add(this.landingGearGroup);
  }

  buildLighting() {
    this.lightingGroup = new THREE.Group();
    this.lightingGroup.name = 'Aviation_Lighting';

    // Helper: Glowing Corona Sprite
    const createGlowSprite = (colorHex, size = 3.5) => {
      const canvas = document.createElement('canvas');
      canvas.width = 128;
      canvas.height = 128;
      const ctx = canvas.getContext('2d');
      const grad = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
      grad.addColorStop(0, '#ffffff');
      grad.addColorStop(0.25, colorHex);
      grad.addColorStop(0.7, colorHex.replace(')', ', 0.35)').replace('rgb', 'rgba'));
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, 128, 128);

      const tex = new THREE.CanvasTexture(canvas);
      const mat = new THREE.SpriteMaterial({
        map: tex,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false
      });
      const sprite = new THREE.Sprite(mat);
      sprite.scale.set(size, size, 1);
      return sprite;
    };

    // 1. Wing Navigation Lights
    // Port (Left) = Solid Red
    const portNav = new THREE.PointLight(0xff1e1e, 2.5, 15);
    portNav.position.set(-32.0, 2.2, -23.8);
    const portSprite = createGlowSprite('rgb(255, 30, 30)', 2.8);
    portNav.add(portSprite);
    this.lightingGroup.add(portNav);
    this.navLights.push(portNav);

    // Starboard (Right) = Solid Green
    const stbdNav = new THREE.PointLight(0x00ff66, 2.5, 15);
    stbdNav.position.set(32.0, 2.2, -23.8);
    const stbdSprite = createGlowSprite('rgb(0, 255, 102)', 2.8);
    stbdNav.add(stbdSprite);
    this.lightingGroup.add(stbdNav);
    this.navLights.push(stbdNav);

    // Tail Navigation Light = Solid White
    const tailNav = new THREE.PointLight(0xffffff, 2.0, 12);
    tailNav.position.set(0, 0.4, -36.7);
    const tailSprite = createGlowSprite('rgb(255, 255, 255)', 2.2);
    tailNav.add(tailSprite);
    this.lightingGroup.add(tailNav);
    this.navLights.push(tailNav);

    // 2. Anti-Collision Red Rotating Beacons (Upper & Lower Fuselage)
    const upperBeacon = new THREE.PointLight(0xff0000, 0, 25);
    upperBeacon.position.set(0, 5.3, 14.0);
    const upperBeaconSprite = createGlowSprite('rgb(255, 0, 0)', 4.2);
    upperBeacon.add(upperBeaconSprite);
    this.lightingGroup.add(upperBeacon);
    this.beacons.push({ light: upperBeacon, sprite: upperBeaconSprite });

    const lowerBeacon = new THREE.PointLight(0xff0000, 0, 25);
    lowerBeacon.position.set(0, -3.4, 3.0);
    const lowerBeaconSprite = createGlowSprite('rgb(255, 0, 0)', 4.2);
    lowerBeacon.add(lowerBeaconSprite);
    this.lightingGroup.add(lowerBeacon);
    this.beacons.push({ light: lowerBeacon, sprite: lowerBeaconSprite });

    // 3. High-Intensity White Wingtip Strobes (Flashing double pulse)
    const portStrobe = new THREE.PointLight(0xffffff, 0, 45);
    portStrobe.position.set(-32.2, 2.3, -24.0);
    const portStrobeSprite = createGlowSprite('rgb(255, 255, 255)', 6.0);
    portStrobe.add(portStrobeSprite);
    this.lightingGroup.add(portStrobe);
    this.strobes.push({ light: portStrobe, sprite: portStrobeSprite });

    const stbdStrobe = new THREE.PointLight(0xffffff, 0, 45);
    stbdStrobe.position.set(32.2, 2.3, -24.0);
    const stbdStrobeSprite = createGlowSprite('rgb(255, 255, 255)', 6.0);
    stbdStrobe.add(stbdStrobeSprite);
    this.lightingGroup.add(stbdStrobe);
    this.strobes.push({ light: stbdStrobe, sprite: stbdStrobeSprite });

    // 4. High-Power Landing Lights & Taxi Lights
    const landingLightL = new THREE.SpotLight(0xfff5ea, 12.0, 160, Math.PI / 7, 0.45, 1.2);
    landingLightL.position.set(-4.2, -1.2, 7.5);
    landingLightL.target.position.set(-4.0, -10.0, 95.0);
    this.lightingGroup.add(landingLightL);
    this.lightingGroup.add(landingLightL.target);
    this.landingLights.push(landingLightL);

    const landingLightR = new THREE.SpotLight(0xfff5ea, 12.0, 160, Math.PI / 7, 0.45, 1.2);
    landingLightR.position.set(4.2, -1.2, 7.5);
    landingLightR.target.position.set(4.0, -10.0, 95.0);
    this.lightingGroup.add(landingLightR);
    this.lightingGroup.add(landingLightR.target);
    this.landingLights.push(landingLightR);

    // Nose Gear Taxi Light
    const taxiLight = new THREE.SpotLight(0xfff7ed, 8.0, 100, Math.PI / 5, 0.35, 1.2);
    taxiLight.position.set(0, -4.5, 23.5);
    taxiLight.target.position.set(0, -8.0, 65.0);
    this.lightingGroup.add(taxiLight);
    this.lightingGroup.add(taxiLight.target);
    this.landingLights.push(taxiLight);

    this.group.add(this.lightingGroup);
  }

  update(delta) {
    // 1. Turbines Rotation
    const rpmSpeed = (15 + this.throttle * 45) * delta;
    this.turbines.forEach(rotor => {
      rotor.rotation.z += rpmSpeed;
    });

    // 2. Beacon Flashing (1.2 Hz smooth pulse)
    this.beaconTimer += delta * 4.5;
    const beaconIntensity = Math.pow(Math.max(0, Math.sin(this.beaconTimer)), 6) * 6.0;
    this.beacons.forEach(b => {
      b.light.intensity = beaconIntensity;
      b.sprite.material.opacity = Math.min(1.0, beaconIntensity / 2.0);
    });

    // 3. Wingtip Strobe Flashing (Double pulse every 1.4 seconds)
    this.strobeTimer = (this.strobeTimer + delta) % 1.4;
    let strobeIntensity = 0;
    if ((this.strobeTimer > 0.05 && this.strobeTimer < 0.12) || (this.strobeTimer > 0.22 && this.strobeTimer < 0.29)) {
      strobeIntensity = 15.0;
    }
    this.strobes.forEach(s => {
      s.light.intensity = strobeIntensity;
      s.sprite.material.opacity = strobeIntensity > 0 ? 1.0 : 0.0;
    });

    // 4. Landing Gear Retraction / Deployment Animation
    if (this.gearDeployed !== this.targetGear) {
      const speed = delta * 0.8;
      if (this.gearDeployed < this.targetGear) {
        this.gearDeployed = Math.min(this.targetGear, this.gearDeployed + speed);
      } else {
        this.gearDeployed = Math.max(this.targetGear, this.gearDeployed - speed);
      }
      this.landingGears.forEach(gear => {
        gear.position.y = -3.2 * this.gearDeployed;
        gear.scale.set(this.gearDeployed, this.gearDeployed, this.gearDeployed);
      });
    }
  }

  setThrottle(val) {
    this.throttle = THREE.MathUtils.clamp(val, 0, 1);
  }

  toggleLandingGear() {
    this.targetGear = this.targetGear > 0.5 ? 0.0 : 1.0;
    return this.targetGear === 1.0;
  }

  setLightingState(type, enabled) {
    if (type === 'nav') {
      this.navLights.forEach(l => (l.visible = enabled));
    } else if (type === 'beacon') {
      this.beacons.forEach(b => (b.light.visible = enabled));
    } else if (type === 'strobe') {
      this.strobes.forEach(s => (s.light.visible = enabled));
    } else if (type === 'landing') {
      this.landingLights.forEach(l => (l.visible = enabled));
    }
  }
}
