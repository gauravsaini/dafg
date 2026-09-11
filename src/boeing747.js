import * as THREE from 'three';

/**
 * Boeing 747-400 Procedural 3D Model Constructor for Three.js.
 * Built with full structural fidelity:
 * - Single seamless lofted fuselage with rounded dome radome and C1 continuous upper-deck hump
 * - Flush-fitted cockpit windshield integrated directly into fuselage texture & brow geometry
 * - 37.5° swept wings with upward dihedral, aerodynamic camber, aluminum slats, and 8 flap canoes
 * - Aerodynamic curved winglets with port (red) and starboard (green) navigation lights
 * - 4x High-bypass turbofan engines at exact wing sweep positions with animated fan blades
 * - Empennage: Swept vertical fin with Boeing Blue livery (uniform UV grid) and swept horizontal stabilizers
 * - Full 18-wheel landing gear system (2-wheel nose gear + four 4-wheel main bogies)
 */
export function createBoeing747(materials) {
    const aircraft = new THREE.Group();
    aircraft.name = 'Boeing747';

    const fanRotors = [];
    const beaconLights = [];
    const strobeLights = [];

    // =========================================================================
    // 1. UNIFIED SEAMLESS LOFTED FUSELAGE & UPPER DECK HUMP
    // =========================================================================
    const fuselageGroup = new THREE.Group();
    fuselageGroup.name = 'FuselageGroup';

    const numStations = 76;
    const numRadial = 48;

    const vertices = [];
    const uvs = [];
    const indices = [];

    for (let s = 0; s < numStations; s++) {
        const vNorm = s / (numStations - 1);
        const z = 35.0 - vNorm * 81.5; // +35m to -46.5m

        let radius = 3.25;
        let centerY = 5.4;
        let humpHeight = 0;

        if (z > 29.0) {
            // Blunt rounded elliptical dome radome
            const tNose = (35.0 - z) / 6.0;
            radius = 3.25 * Math.sqrt(Math.max(0, 1.0 - Math.pow(1.0 - tNose, 2.0)));
            centerY = 4.4 + tNose * 1.0;
        } else if (z >= 26.5 && z <= 29.0) {
            // Cockpit brow slope
            const tBrow = (29.0 - z) / 2.5;
            centerY = 5.4;
            humpHeight = 1.9 * Math.sin(tBrow * Math.PI / 2);
        } else if (z >= 9.0 && z < 26.5) {
            // Full Upper Deck Hump ("The Queen's Crown")
            centerY = 5.4;
            humpHeight = 1.9;
        } else if (z >= 3.0 && z < 9.0) {
            // Smooth C1 transition from hump to cylindrical main cabin
            const tFair = (z - 3.0) / 6.0;
            centerY = 5.4;
            const smoothT = tFair * tFair * (3.0 - 2.0 * tFair);
            humpHeight = 1.9 * smoothT;
        } else if (z >= -20.0 && z < 3.0) {
            // Constant cylindrical main deck
            centerY = 5.4;
            humpHeight = 0;
            radius = 3.25;
        } else {
            // Smooth tailcone tapering up to APU
            const tTail = (-20.0 - z) / 26.5;
            radius = 3.25 * (1.0 - tTail * 0.85);
            centerY = 5.4 + tTail * 1.5;
            humpHeight = 0;
        }

        for (let r = 0; r < numRadial; r++) {
            const uNorm = r / numRadial;
            const theta = uNorm * Math.PI * 2;

            const sinT = Math.sin(theta);
            const cosT = Math.cos(theta);

            const x = -radius * sinT;
            const humpCurve = cosT > 0 ? (cosT * cosT) : 0;
            const y = centerY + radius * cosT + humpHeight * humpCurve;

            vertices.push(x, y, z);
            uvs.push(vNorm, uNorm);
        }
    }

    for (let s = 0; s < numStations - 1; s++) {
        for (let r = 0; r < numRadial; r++) {
            const nextR = (r + 1) % numRadial;

            const i0 = s * numRadial + r;
            const i1 = s * numRadial + nextR;
            const i2 = (s + 1) * numRadial + r;
            const i3 = (s + 1) * numRadial + nextR;

            indices.push(i0, i2, i1);
            indices.push(i1, i2, i3);
        }
    }

    // Nose cap
    const noseCenterIdx = vertices.length / 3;
    vertices.push(0, 4.4, 35.0);
    uvs.push(0, 0.5);
    for (let r = 0; r < numRadial; r++) {
        const nextR = (r + 1) % numRadial;
        indices.push(noseCenterIdx, nextR, r);
    }

    // Tail APU cap
    const tailCenterIdx = vertices.length / 3;
    vertices.push(0, 6.9, -46.5);
    uvs.push(1, 0.5);
    const lastStationOffset = (numStations - 1) * numRadial;
    for (let r = 0; r < numRadial; r++) {
        const nextR = (r + 1) % numRadial;
        indices.push(tailCenterIdx, lastStationOffset + r, lastStationOffset + nextR);
    }

    const fuselageGeom = new THREE.BufferGeometry();
    fuselageGeom.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    fuselageGeom.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
    fuselageGeom.setIndex(indices);
    fuselageGeom.computeVertexNormals();

    const fuselageMesh = new THREE.Mesh(fuselageGeom, materials.fuselage);
    fuselageMesh.castShadow = true;
    fuselageMesh.receiveShadow = true;
    fuselageGroup.add(fuselageMesh);

    // APU Exhaust Nozzle at extreme tail tip
    const apuGeom = new THREE.CylinderGeometry(0.38, 0.46, 1.4, 24);
    apuGeom.rotateX(Math.PI / 2);
    const apuMesh = new THREE.Mesh(apuGeom, materials.exhaustTitanium);
    apuMesh.position.set(0, 6.9, -46.7);
    fuselageGroup.add(apuMesh);

    aircraft.add(fuselageGroup);

    // =========================================================================
    // 2. WINGS & WINGLETS (37.5° Sweep, Upward Dihedral, Slats, Flap Canoes)
    // =========================================================================
    const wingsGroup = new THREE.Group();
    wingsGroup.name = 'WingsGroup';

    function createWing(side) {
        const wing = new THREE.Group();
        wing.name = side === 1 ? 'StarboardWing' : 'PortWing';

        const numWingSections = 20;
        const wingVerts = [];
        const wingUvs = [];
        const wingIndices = [];

        for (let i = 0; i <= numWingSections; i++) {
            const spanT = i / numWingSections;
            const x = 3.25 + spanT * (32.2 - 3.25);
            const y = 4.8 + spanT * 3.2 + Math.pow(spanT, 2) * 0.4;

            const zLE = 5.5 - Math.tan(37.5 * Math.PI / 180) * (x - 3.25);
            const chord = 15.5 - spanT * (15.5 - 3.6);
            const zTE = zLE - chord;

            const thickness = 1.35 - spanT * (1.35 - 0.32);

            const upperProfile = [
                { z: zLE, y: y },
                { z: zLE - chord * 0.15, y: y + thickness * 0.55 },
                { z: zLE - chord * 0.40, y: y + thickness * 0.50 },
                { z: zLE - chord * 0.70, y: y + thickness * 0.28 },
                { z: zTE, y: y + 0.02 },
            ];

            const lowerProfile = [
                { z: zTE, y: y - 0.02 },
                { z: zLE - chord * 0.70, y: y - thickness * 0.22 },
                { z: zLE - chord * 0.40, y: y - thickness * 0.38 },
                { z: zLE - chord * 0.15, y: y - thickness * 0.42 },
            ];

            const fullAirfoil = [...upperProfile, ...lowerProfile];

            for (let p = 0; p < fullAirfoil.length; p++) {
                wingVerts.push(x * side, fullAirfoil[p].y, fullAirfoil[p].z);
                wingUvs.push(spanT, p / (fullAirfoil.length - 1));
            }
        }

        const ptsPerSection = 9;
        for (let s = 0; s < numWingSections; s++) {
            for (let p = 0; p < ptsPerSection; p++) {
                const nextP = (p + 1) % ptsPerSection;
                const i0 = s * ptsPerSection + p;
                const i1 = s * ptsPerSection + nextP;
                const i2 = (s + 1) * ptsPerSection + p;
                const i3 = (s + 1) * ptsPerSection + nextP;

                if (side === 1) {
                    wingIndices.push(i0, i1, i2);
                    wingIndices.push(i1, i3, i2);
                } else {
                    wingIndices.push(i0, i2, i1);
                    wingIndices.push(i1, i2, i3);
                }
            }
        }

        const wingGeom = new THREE.BufferGeometry();
        wingGeom.setAttribute('position', new THREE.Float32BufferAttribute(wingVerts, 3));
        wingGeom.setAttribute('uv', new THREE.Float32BufferAttribute(wingUvs, 2));
        wingGeom.setIndex(wingIndices);
        wingGeom.computeVertexNormals();

        const wingMesh = new THREE.Mesh(wingGeom, materials.wings);
        wingMesh.castShadow = true;
        wingMesh.receiveShadow = true;
        wing.add(wingMesh);

        // Polished Bare Aluminum Leading-Edge Slat Tube
        const slatCurve = new THREE.CatmullRomCurve3([
            new THREE.Vector3(3.25 * side, 4.82, 5.5),
            new THREE.Vector3(12.0 * side, 5.85, -1.2),
            new THREE.Vector3(22.0 * side, 7.15, -8.9),
            new THREE.Vector3(32.2 * side, 8.42, -16.8),
        ]);
        const slatTubeGeom = new THREE.TubeGeometry(slatCurve, 24, 0.22, 12, false);
        const slatMesh = new THREE.Mesh(slatTubeGeom, materials.polishedAluminum);
        wing.add(slatMesh);

        // 4 Flap Track Fairings ("Canoes") under wing
        const canoeStations = [
            { x: 8.5, len: 6.8, scale: 1.15 },
            { x: 14.5, len: 6.0, scale: 1.0 },
            { x: 21.0, len: 5.2, scale: 0.85 },
            { x: 27.5, len: 4.4, scale: 0.7 },
        ];

        canoeStations.forEach((cs) => {
            const spanT = (cs.x - 3.25) / (32.2 - 3.25);
            const canoeY = 4.8 + spanT * 3.2 - 0.55;
            const zLE = 5.5 - Math.tan(37.5 * Math.PI / 180) * (cs.x - 3.25);
            const chord = 15.5 - spanT * (15.5 - 3.6);
            const canoeZ = zLE - chord * 0.82;

            const canoeGeom = new THREE.ConeGeometry(0.42 * cs.scale, cs.len, 16);
            canoeGeom.rotateX(Math.PI / 2);
            const canoeMesh = new THREE.Mesh(canoeGeom, materials.fairingWhite);
            canoeMesh.position.set(cs.x * side, canoeY, canoeZ);
            canoeMesh.castShadow = true;
            wing.add(canoeMesh);
        });

        // Aerodynamic 747-400 Winglet
        const wingletGroup = new THREE.Group();
        wingletGroup.name = 'Winglet';
        wingletGroup.position.set(32.2 * side, 8.4, -17.5);

        const wingletShape = new THREE.Shape();
        wingletShape.moveTo(0.6, 0);
        wingletShape.lineTo(-2.2, 0);
        wingletShape.lineTo(-1.6, 2.2);
        wingletShape.bezierCurveTo(-1.3, 2.35, -0.8, 2.35, -0.6, 2.15);
        wingletShape.lineTo(0.2, 1.1);
        wingletShape.closePath();

        const wingletGeom = new THREE.ExtrudeGeometry(wingletShape, {
            depth: 0.16,
            bevelEnabled: true,
            bevelThickness: 0.05,
            bevelSize: 0.04,
        });
        const wingletMesh = new THREE.Mesh(wingletGeom, materials.fuselage);
        wingletMesh.rotation.z = side * 0.32;
        wingletMesh.rotation.y = side * 0.08;
        wingletMesh.castShadow = true;
        wingletGroup.add(wingletMesh);

        // Leading edge chrome trim on winglet
        const wingletTrim = new THREE.Mesh(
            new THREE.CylinderGeometry(0.05, 0.05, 2.4, 12),
            materials.polishedAluminum
        );
        wingletTrim.position.set(0.12 * side, 1.15, 0.08);
        wingletTrim.rotation.z = side * -0.15;
        wingletGroup.add(wingletTrim);

        // Navigation Light (Red on Port, Green on Starboard)
        const navLightMaterial = side === -1 ? materials.navLightRed : materials.navLightGreen;
        const navLightMesh = new THREE.Mesh(
            new THREE.SphereGeometry(0.18, 16, 16),
            navLightMaterial
        );
        navLightMesh.position.set(0.25 * side, 0.2, 0.2);
        wingletGroup.add(navLightMesh);

        const navLightPoint = new THREE.PointLight(
            side === -1 ? 0xff0033 : 0x00ff66,
            2.0,
            20
        );
        navLightPoint.position.copy(navLightMesh.position);
        wingletGroup.add(navLightPoint);

        // Wingtip Strobe Beacon
        const strobeMesh = new THREE.Mesh(
            new THREE.SphereGeometry(0.15, 12, 12),
            materials.strobeWhite
        );
        strobeMesh.position.set(-0.2 * side, 0.1, -0.1);
        wingletGroup.add(strobeMesh);

        const strobeLight = new THREE.PointLight(0xffffff, 3.5, 30);
        strobeLight.position.copy(strobeMesh.position);
        wingletGroup.add(strobeLight);
        strobeLights.push({ mesh: strobeMesh, light: strobeLight });

        wing.add(wingletGroup);

        return wing;
    }

    const starboardWing = createWing(1);
    const portWing = createWing(-1);
    wingsGroup.add(starboardWing);
    wingsGroup.add(portWing);
    aircraft.add(wingsGroup);

    // =========================================================================
    // 3. FOUR HIGH-BYPASS TURBOFAN ENGINES (Exact Wing Leading-Edge Stagger)
    // =========================================================================
    const enginesGroup = new THREE.Group();
    enginesGroup.name = 'EnginesGroup';

    const engineSpecs = [
        { name: 'Engine1_PortOutboard', x: -21.2, y: 4.0, z: -7.7, wingLowerY: 6.67 },
        { name: 'Engine2_PortInboard', x: -11.8, y: 3.1, z: -0.5, wingLowerY: 5.35 },
        { name: 'Engine3_StbdInboard', x: 11.8, y: 3.1, z: -0.5, wingLowerY: 5.35 },
        { name: 'Engine4_StbdOutboard', x: 21.2, y: 4.0, z: -7.7, wingLowerY: 6.67 },
    ];

    engineSpecs.forEach((spec) => {
        const engine = new THREE.Group();
        engine.name = spec.name;
        engine.position.set(spec.x, spec.y, spec.z);

        // Aerodynamic Pylon connecting flush to nacelle top and under wing skin
        const pylonTopY = spec.wingLowerY - spec.y;
        const pylonShape = new THREE.Shape();
        pylonShape.moveTo(-1.2, 1.35);
        pylonShape.lineTo(0.6, 1.35);
        pylonShape.lineTo(1.2, pylonTopY);
        pylonShape.lineTo(2.6, pylonTopY);
        pylonShape.lineTo(2.4, 1.35);
        pylonShape.closePath();

        const pylonGeom = new THREE.ExtrudeGeometry(pylonShape, {
            depth: 0.32,
            bevelEnabled: true,
            bevelThickness: 0.05,
            bevelSize: 0.04,
        });
        pylonGeom.translate(0, 0, -0.16);
        pylonGeom.rotateY(Math.PI / 2);
        const pylon = new THREE.Mesh(pylonGeom, materials.engineCowling);
        pylon.castShadow = true;
        engine.add(pylon);

        // Nacelle Outer Cowling with texture
        const nacelleGeom = new THREE.CylinderGeometry(1.35, 1.22, 5.0, 36, 6, true);
        nacelleGeom.rotateX(Math.PI / 2);
        const nacelle = new THREE.Mesh(nacelleGeom, materials.engineCowling);
        nacelle.castShadow = true;
        nacelle.receiveShadow = true;
        engine.add(nacelle);

        // Polished Chrome Intake Lip
        const intakeLipGeom = new THREE.TorusGeometry(1.35, 0.16, 16, 48);
        const intakeLip = new THREE.Mesh(intakeLipGeom, materials.polishedAluminum);
        intakeLip.position.set(0, 0, 2.5);
        engine.add(intakeLip);

        // Duct Liner
        const ductGeom = new THREE.CylinderGeometry(1.22, 1.14, 3.6, 32, 1, true);
        ductGeom.rotateX(Math.PI / 2);
        const duct = new THREE.Mesh(ductGeom, materials.turbineInterior);
        duct.position.set(0, 0, 0.6);
        engine.add(duct);

        // Core Primary Exhaust Nozzle & Center Plug
        const exhaustGeom = new THREE.CylinderGeometry(0.82, 0.94, 2.2, 32);
        exhaustGeom.rotateX(Math.PI / 2);
        const exhaust = new THREE.Mesh(exhaustGeom, materials.exhaustTitanium);
        exhaust.position.set(0, 0, -2.7);
        engine.add(exhaust);

        const exhaustPlugGeom = new THREE.ConeGeometry(0.52, 1.8, 24);
        exhaustPlugGeom.rotateX(-Math.PI / 2);
        const exhaustPlug = new THREE.Mesh(exhaustPlugGeom, materials.exhaustTitanium);
        exhaustPlug.position.set(0, 0, -3.7);
        engine.add(exhaustPlug);

        // Rotating Fan Rotor Assembly (24 Blades)
        const rotorGroup = new THREE.Group();
        rotorGroup.name = 'FanRotor';
        rotorGroup.position.set(0, 0, 1.8);

        const spinnerGeom = new THREE.ConeGeometry(0.46, 1.25, 24);
        spinnerGeom.rotateX(Math.PI / 2);
        const spinner = new THREE.Mesh(spinnerGeom, materials.spinner);
        rotorGroup.add(spinner);

        const bladeCount = 24;
        const bladeGeom = new THREE.BoxGeometry(0.08, 0.72, 0.15);
        for (let b = 0; b < bladeCount; b++) {
            const angle = (b / bladeCount) * Math.PI * 2;
            const blade = new THREE.Mesh(bladeGeom, materials.fanBlades);
            blade.position.set(
                Math.cos(angle) * 0.76,
                Math.sin(angle) * 0.76,
                -0.08
            );
            blade.rotation.z = angle + Math.PI / 2;
            blade.rotation.y = 0.42;
            rotorGroup.add(blade);
        }

        engine.add(rotorGroup);
        fanRotors.push(rotorGroup);

        enginesGroup.add(engine);
    });

    aircraft.add(enginesGroup);

    // =========================================================================
    // 4. EMPENNAGE (Swept Fin with Boeing Blue Livery & Swept Stabilizers)
    // =========================================================================
    const tailGroup = new THREE.Group();
    tailGroup.name = 'TailGroup';
    tailGroup.position.set(0, 6.6, -34.0);

    const finVerts = [];
    const finUvs = [];
    const finIndices = [];

    const finLevels = 14;
    const finChordSegments = 5; // 6 vertices across chord for smooth undistorted texture mapping

    for (let l = 0; l <= finLevels; l++) {
        const t = l / finLevels;
        const y = 1.3 + t * 10.4;

        const zLE = -t * 5.4;
        const zTE = -11.5 + t * 3.3;

        const thick = 0.3 * (1.0 - t * 0.7);

        // Starboard face (X > 0)
        for (let c = 0; c <= finChordSegments; c++) {
            const u = c / finChordSegments;
            const z = zLE + (zTE - zLE) * u;
            // Aerodynamic airfoil thickness curve
            const localThick = thick * Math.sin(u * Math.PI * 0.9 + 0.1);
            finVerts.push(localThick, y, z);
            finUvs.push(u, t);
        }

        // Port face (X < 0) - u inverted so text reads correctly from left to right!
        for (let c = 0; c <= finChordSegments; c++) {
            const u = c / finChordSegments;
            const z = zLE + (zTE - zLE) * u;
            const localThick = thick * Math.sin(u * Math.PI * 0.9 + 0.1);
            finVerts.push(-localThick, y, z);
            finUvs.push(1.0 - u, t);
        }
    }

    const vPerSide = finChordSegments + 1;
    const vPerLevel = vPerSide * 2;

    for (let l = 0; l < finLevels; l++) {
        const b = l * vPerLevel;
        const nb = (l + 1) * vPerLevel;

        // Starboard face grid
        for (let c = 0; c < finChordSegments; c++) {
            const i0 = b + c;
            const i1 = b + c + 1;
            const i2 = nb + c;
            const i3 = nb + c + 1;

            finIndices.push(i0, i2, i1);
            finIndices.push(i1, i2, i3);
        }

        // Port face grid
        for (let c = 0; c < finChordSegments; c++) {
            const i0 = b + vPerSide + c;
            const i1 = b + vPerSide + c + 1;
            const i2 = nb + vPerSide + c;
            const i3 = nb + vPerSide + c + 1;

            finIndices.push(i0, i1, i2);
            finIndices.push(i1, i3, i2);
        }

        // Leading edge close
        finIndices.push(b, nb, b + vPerSide);
        finIndices.push(b + vPerSide, nb, nb + vPerSide);

        // Trailing edge close
        finIndices.push(b + finChordSegments, b + vPerSide + finChordSegments, nb + finChordSegments);
        finIndices.push(b + vPerSide + finChordSegments, nb + vPerSide + finChordSegments, nb + finChordSegments);
    }

    const finGeom = new THREE.BufferGeometry();
    finGeom.setAttribute('position', new THREE.Float32BufferAttribute(finVerts, 3));
    finGeom.setAttribute('uv', new THREE.Float32BufferAttribute(finUvs, 2));
    finGeom.setIndex(finIndices);
    finGeom.computeVertexNormals();

    const finMesh = new THREE.Mesh(finGeom, materials.tailLivery);
    finMesh.castShadow = true;
    finMesh.receiveShadow = true;
    tailGroup.add(finMesh);

    // Polished Aluminum Leading Edge Strip on Fin
    const finLeadCurve = new THREE.CatmullRomCurve3([
        new THREE.Vector3(0, 1.3, 0),
        new THREE.Vector3(0, 6.5, -2.7),
        new THREE.Vector3(0, 11.7, -5.4),
    ]);
    const finLeadTube = new THREE.TubeGeometry(finLeadCurve, 16, 0.16, 10, false);
    const finLeadMesh = new THREE.Mesh(finLeadTube, materials.polishedAluminum);
    tailGroup.add(finLeadMesh);

    // White Tail Navigation Light
    const tailNavMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.18, 16, 16),
        materials.strobeWhite
    );
    tailNavMesh.position.set(0, 0.4, -12.6);
    tailGroup.add(tailNavMesh);

    const tailNavPoint = new THREE.PointLight(0xffffff, 2.0, 20);
    tailNavPoint.position.copy(tailNavMesh.position);
    tailGroup.add(tailNavPoint);
    strobeLights.push({ mesh: tailNavMesh, light: tailNavPoint });

    // Horizontal Stabilizers (Span: 22m, Sweep: 33°, Dihedral: 7°)
    function createHorizontalStab(side) {
        const stab = new THREE.Group();
        stab.name = side === 1 ? 'StbdHorizontalStab' : 'PortHorizontalStab';

        const stabShape = new THREE.Shape();
        stabShape.moveTo(0, -2.5);
        stabShape.lineTo(0, 3.2);
        stabShape.lineTo(11.0, 8.5);
        stabShape.lineTo(11.0, 5.5);
        stabShape.closePath();

        const stabGeom = new THREE.ExtrudeGeometry(stabShape, {
            depth: 0.35,
            bevelEnabled: true,
            bevelThickness: 0.08,
            bevelSize: 0.06,
        });
        stabGeom.rotateX(-Math.PI / 2);
        const stabMesh = new THREE.Mesh(stabGeom, materials.wings);
        stabMesh.castShadow = true;
        stab.add(stabMesh);

        // Leading edge chrome tube following the 33° backward sweep
        const stabLeadCurve = new THREE.CatmullRomCurve3([
            new THREE.Vector3(0, 0.05, 2.5),
            new THREE.Vector3(5.5, 0.05, -1.5),
            new THREE.Vector3(11.0, 0.05, -5.5),
        ]);
        const stabLeadTube = new THREE.TubeGeometry(stabLeadCurve, 16, 0.12, 8, false);
        const stabLead = new THREE.Mesh(stabLeadTube, materials.polishedAluminum);
        stab.add(stabLead);

        stab.rotation.z = side * 0.12;
        if (side === -1) stab.scale.x = -1;
        return stab;
    }

    const stbdStab = createHorizontalStab(1);
    const portStab = createHorizontalStab(-1);
    stbdStab.position.set(1.4, 0.2, -5.5);
    portStab.position.set(-1.4, 0.2, -5.5);
    tailGroup.add(stbdStab);
    tailGroup.add(portStab);

    aircraft.add(tailGroup);

    // =========================================================================
    // 5. FULL 18-WHEEL LANDING GEAR SYSTEM (Runway at Y = 0)
    // =========================================================================
    const gearGroup = new THREE.Group();
    gearGroup.name = 'LandingGearGroup';

    function createWheel(radius = 0.65, width = 0.42) {
        const wheel = new THREE.Group();
        const tireGeom = new THREE.CylinderGeometry(radius, radius, width, 24);
        tireGeom.rotateZ(Math.PI / 2);
        const tire = new THREE.Mesh(tireGeom, materials.tireRubber);
        tire.castShadow = true;
        wheel.add(tire);

        const hubGeom = new THREE.CylinderGeometry(radius * 0.55, radius * 0.55, width * 1.05, 18);
        hubGeom.rotateZ(Math.PI / 2);
        const hub = new THREE.Mesh(hubGeom, materials.wheelHub);
        wheel.add(hub);

        const capGeom = new THREE.CylinderGeometry(radius * 0.18, radius * 0.18, width * 1.15, 12);
        capGeom.rotateZ(Math.PI / 2);
        const cap = new THREE.Mesh(capGeom, materials.hydraulicChrome);
        wheel.add(cap);

        return wheel;
    }

    // --- 5A. Nose Landing Gear (2 Wheels, Oleo Strut, Taxi Spotlight, Bay Doors) ---
    const noseGear = new THREE.Group();
    noseGear.name = 'NoseGear';
    noseGear.position.set(0, 0, 24.5);

    const noseStrutHeight = 2.8;
    const noseStrutGeom = new THREE.CylinderGeometry(0.2, 0.2, noseStrutHeight, 16);
    const noseStrut = new THREE.Mesh(noseStrutGeom, materials.gearStrut);
    noseStrut.position.y = 0.62 + noseStrutHeight / 2;
    noseStrut.castShadow = true;
    noseGear.add(noseStrut);

    const nosePistonGeom = new THREE.CylinderGeometry(0.14, 0.14, 1.4, 16);
    const nosePiston = new THREE.Mesh(nosePistonGeom, materials.hydraulicChrome);
    nosePiston.position.y = 1.2;
    noseGear.add(nosePiston);

    const noseAxleGeom = new THREE.CylinderGeometry(0.09, 0.09, 1.3, 12);
    noseAxleGeom.rotateZ(Math.PI / 2);
    const noseAxle = new THREE.Mesh(noseAxleGeom, materials.gearStrut);
    noseAxle.position.y = 0.62;
    noseGear.add(noseAxle);

    const leftNoseWheel = createWheel(0.62, 0.32);
    leftNoseWheel.position.set(-0.52, 0.62, 0);
    const rightNoseWheel = createWheel(0.62, 0.32);
    rightNoseWheel.position.set(0.52, 0.62, 0);
    noseGear.add(leftNoseWheel);
    noseGear.add(rightNoseWheel);

    // Taxi Spotlight
    const taxiLightMesh = new THREE.Mesh(
        new THREE.CylinderGeometry(0.16, 0.16, 0.15, 16),
        materials.strobeWhite
    );
    taxiLightMesh.rotateX(Math.PI / 2);
    taxiLightMesh.position.set(0, 1.9, 0.25);
    noseGear.add(taxiLightMesh);

    const taxiSpotlight = new THREE.SpotLight(0xfffaed, 3.5, 70, Math.PI / 6, 0.3);
    taxiSpotlight.position.set(0, 1.9, 0.35);
    taxiSpotlight.target.position.set(0, 0, 50);
    noseGear.add(taxiSpotlight);
    noseGear.add(taxiSpotlight.target);

    // Open Nose Bay Doors
    const noseDoorGeom = new THREE.BoxGeometry(0.06, 1.6, 2.8);
    const leftNoseDoor = new THREE.Mesh(noseDoorGeom, materials.fuselage);
    leftNoseDoor.position.set(-0.7, 2.8, 0);
    leftNoseDoor.rotation.z = -0.32;
    const rightNoseDoor = new THREE.Mesh(noseDoorGeom, materials.fuselage);
    rightNoseDoor.position.set(0.7, 2.8, 0);
    rightNoseDoor.rotation.z = 0.32;
    noseGear.add(leftNoseDoor);
    noseGear.add(rightNoseDoor);

    gearGroup.add(noseGear);

    // --- 5B. Main Landing Gear (4 Bogies x 4 Wheels = 16 Wheels) ---
    const mainGearConfigs = [
        { name: 'PortWingGear', x: -5.6, z: -1.5, strutTop: 4.4 },
        { name: 'StbdWingGear', x: 5.6, z: -1.5, strutTop: 4.4 },
        { name: 'PortBodyGear', x: -2.2, z: -5.0, strutTop: 3.6 },
        { name: 'StbdBodyGear', x: 2.2, z: -5.0, strutTop: 3.6 },
    ];

    mainGearConfigs.forEach((cfg) => {
        const bogieGroup = new THREE.Group();
        bogieGroup.name = cfg.name;
        bogieGroup.position.set(cfg.x, 0, cfg.z);

        const strutHeight = cfg.strutTop - 0.65;
        const mainStrutGeom = new THREE.CylinderGeometry(0.24, 0.24, strutHeight, 16);
        const mainStrut = new THREE.Mesh(mainStrutGeom, materials.gearStrut);
        mainStrut.position.y = 0.65 + strutHeight / 2;
        mainStrut.castShadow = true;
        bogieGroup.add(mainStrut);

        const truckBeamGeom = new THREE.BoxGeometry(0.32, 0.32, 2.2);
        const truckBeam = new THREE.Mesh(truckBeamGeom, materials.gearStrut);
        truckBeam.position.y = 0.65;
        bogieGroup.add(truckBeam);

        [-0.78, 0.78].forEach((az) => {
            const axleGeom = new THREE.CylinderGeometry(0.1, 0.1, 1.8, 12);
            axleGeom.rotateZ(Math.PI / 2);
            const axle = new THREE.Mesh(axleGeom, materials.gearStrut);
            axle.position.set(0, 0.65, az);
            bogieGroup.add(axle);

            const wL = createWheel(0.65, 0.42);
            wL.position.set(-0.84, 0.65, az);
            const wR = createWheel(0.65, 0.42);
            wR.position.set(0.84, 0.65, az);
            bogieGroup.add(wL);
            bogieGroup.add(wR);
        });

        const bayDoorGeom = new THREE.BoxGeometry(0.08, 1.6, 3.4);
        const bayDoor = new THREE.Mesh(bayDoorGeom, materials.fuselage);
        const doorSide = cfg.x > 0 ? 1 : -1;
        bayDoor.position.set(doorSide * 1.25, 2.8, 0);
        bayDoor.rotation.z = doorSide * 0.35;
        bogieGroup.add(bayDoor);

        gearGroup.add(bogieGroup);
    });

    aircraft.add(gearGroup);

    // =========================================================================
    // 6. FUSELAGE BEACONS & WING SCAN LIGHTS
    // =========================================================================
    const topBeaconMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.2, 16, 16),
        materials.beaconRed
    );
    topBeaconMesh.position.set(0, 10.5, 16.0);
    aircraft.add(topBeaconMesh);

    const topBeaconLight = new THREE.PointLight(0xff1100, 3.0, 35);
    topBeaconLight.position.copy(topBeaconMesh.position);
    aircraft.add(topBeaconLight);
    beaconLights.push({ mesh: topBeaconMesh, light: topBeaconLight });

    const bellyBeaconMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.2, 16, 16),
        materials.beaconRed
    );
    bellyBeaconMesh.position.set(0, 2.1, 0.0);
    aircraft.add(bellyBeaconMesh);

    const bellyBeaconLight = new THREE.PointLight(0xff1100, 3.0, 30);
    bellyBeaconLight.position.copy(bellyBeaconMesh.position);
    aircraft.add(bellyBeaconLight);
    beaconLights.push({ mesh: bellyBeaconMesh, light: bellyBeaconLight });

    [-3.3, 3.3].forEach((wx) => {
        const wingScan = new THREE.SpotLight(0xfffaee, 2.5, 50, Math.PI / 5, 0.4);
        wingScan.position.set(wx, 5.0, 7.0);
        wingScan.target.position.set(wx * 4, 3.5, -5.0);
        aircraft.add(wingScan);
        aircraft.add(wingScan.target);
    });

    // =========================================================================
    // 7. ANIMATION TICK UPDATE
    // =========================================================================
    aircraft.userData = {
        fanRotors,
        beaconLights,
        strobeLights,
        engineRPM: 1200,
        lightsActive: true,
        update: (delta, time) => {
            const spinDelta = delta * 25.0;
            fanRotors.forEach((rotor) => {
                rotor.rotation.z += spinDelta;
            });

            const beaconCycle = (Math.sin(time * 5.0) + 1.0) / 2.0;
            const beaconIntensity = Math.pow(beaconCycle, 4) * 5.0;
            beaconLights.forEach((b) => {
                b.light.intensity = beaconIntensity;
                b.mesh.material.emissiveIntensity = 0.5 + beaconIntensity;
            });

            const strobePhase = (time % 1.5);
            const isFlashing = (strobePhase > 0 && strobePhase < 0.08) || (strobePhase > 0.16 && strobePhase < 0.24);
            const strobeIntensity = isFlashing ? 12.0 : 0.05;
            strobeLights.forEach((s) => {
                s.light.intensity = strobeIntensity;
                s.mesh.material.emissiveIntensity = isFlashing ? 6.0 : 0.2;
            });
        },
    };

    return aircraft;
}
