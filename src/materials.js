import * as THREE from 'three';

/**
 * Ultra-Realistic PBR Materials & Procedural Textures for Boeing 747-400.
 */

export function createFuselageTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 2048;
    canvas.height = 1024;
    const ctx = canvas.getContext('2d');

    // Base Aircraft Pearlescent Gloss White
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Subtle Structural Section Seams
    ctx.strokeStyle = 'rgba(215, 225, 235, 0.45)';
    ctx.lineWidth = 1.5;
    [260, 440, 720, 1020, 1340, 1640].forEach((sx) => {
        ctx.beginPath();
        ctx.moveTo(sx, 0);
        ctx.lineTo(sx, canvas.height);
        ctx.stroke();
    });

    // Aerodynamic Belly Keel (Titanium/Gray belly fairing)
    ctx.fillStyle = 'rgba(218, 226, 236, 0.4)';
    ctx.fillRect(0, 460, canvas.width, 104);

    // Classic Boeing Blue & Gold Cheatline
    // Port side: Y = 230-270
    const portGrad = ctx.createLinearGradient(0, 230, 0, 270);
    portGrad.addColorStop(0, '#002244');
    portGrad.addColorStop(0.5, '#004488');
    portGrad.addColorStop(1, '#001a33');
    ctx.fillStyle = portGrad;
    ctx.fillRect(110, 230, canvas.width - 180, 40);

    // Gold pinstripes Port
    ctx.fillStyle = '#c5a059';
    ctx.fillRect(110, 270, canvas.width - 180, 5);
    ctx.fillRect(110, 225, canvas.width - 180, 3);

    // Port Livery Typography (Reading Nose to Tail)
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 24px -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
    ctx.fillText('BOEING 747-400', 460, 258);
    ctx.fillStyle = '#93c5fd';
    ctx.font = 'italic 12px "Helvetica Neue", Arial, sans-serif';
    ctx.fillText('QUEEN OF THE SKIES', 462, 278);

    // Starboard side: Y = 755-795
    const stbdGrad = ctx.createLinearGradient(0, 755, 0, 795);
    stbdGrad.addColorStop(0, '#002244');
    stbdGrad.addColorStop(0.5, '#004488');
    stbdGrad.addColorStop(1, '#001a33');
    ctx.fillStyle = stbdGrad;
    ctx.fillRect(110, 755, canvas.width - 180, 40);

    // Gold pinstripes Starboard
    ctx.fillStyle = '#c5a059';
    ctx.fillRect(110, 795, canvas.width - 180, 5);
    ctx.fillRect(110, 750, canvas.width - 180, 3);

    // Starboard Livery Typography
    ctx.save();
    ctx.translate(canvas.width, 0);
    ctx.scale(-1, 1);
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 24px -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
    ctx.fillText('BOEING 747-400', canvas.width - 700, 783);
    ctx.fillStyle = '#93c5fd';
    ctx.font = 'italic 12px "Helvetica Neue", Arial, sans-serif';
    ctx.fillText('QUEEN OF THE SKIES', canvas.width - 700, 803);
    ctx.restore();

    // Main Deck Passenger Window Belts
    function drawWindowBelt(yPos) {
        for (let x = 300; x < canvas.width - 240; x += 18) {
            if ((x > 370 && x < 430) || (x > 730 && x < 790) || (x > 1130 && x < 1190) || (x > 1530 && x < 1590)) {
                continue;
            }
            ctx.fillStyle = '#080c14';
            ctx.beginPath();
            ctx.roundRect(x, yPos, 8, 14, 3);
            ctx.fill();
            ctx.strokeStyle = '#cbd5e1';
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.fillStyle = 'rgba(255, 235, 175, 0.5)';
            ctx.fillRect(x + 2, yPos + 3, 4, 7);
        }
    }

    drawWindowBelt(175); // Port main deck
    drawWindowBelt(700); // Starboard main deck

    // Upper Deck Hump Window Belts
    function drawUpperDeckWindows(yPos) {
        for (let x = 320; x < 610; x += 20) {
            ctx.fillStyle = '#080c14';
            ctx.beginPath();
            ctx.roundRect(x, yPos, 8, 13, 3);
            ctx.fill();
            ctx.strokeStyle = '#cbd5e1';
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.fillStyle = 'rgba(255, 235, 175, 0.55)';
            ctx.fillRect(x + 2, yPos + 3, 4, 6);
        }
    }

    drawUpperDeckWindows(105); // Port upper deck
    drawUpperDeckWindows(630); // Starboard upper deck

    // Passenger Entry Doors
    function drawDoors(yDoor) {
        const doorXs = [390, 750, 1150, 1550];
        doorXs.forEach((dx) => {
            ctx.strokeStyle = '#94a3b8';
            ctx.lineWidth = 2.5;
            ctx.strokeRect(dx, yDoor, 22, 58);

            ctx.fillStyle = '#080c14';
            ctx.fillRect(dx + 6, yDoor + 10, 10, 13);

            ctx.fillStyle = '#e11d48';
            ctx.fillRect(dx + 16, yDoor + 28, 3, 8);
        });
    }

    drawDoors(165);
    drawDoors(690);

    // Cockpit Windshield Panes on Texture
    function drawCockpitWindows() {
        const xStart = 148;
        const paneW = 14;
        const paneH = 22;

        const portPanes = [
            { x: xStart, y: 15, w: paneW, h: paneH },
            { x: xStart + 8, y: 42, w: paneW, h: paneH },
            { x: xStart + 16, y: 70, w: paneW + 4, h: paneH - 2 },
        ];

        const stbdPanes = [
            { x: xStart, y: 1024 - 15 - paneH, w: paneW, h: paneH },
            { x: xStart + 8, y: 1024 - 42 - paneH, w: paneW, h: paneH },
            { x: xStart + 16, y: 1024 - 70 - (paneH - 2), w: paneW + 4, h: paneH - 2 },
        ];

        const allPanes = [...portPanes, ...stbdPanes];

        allPanes.forEach((p) => {
            ctx.fillStyle = '#050910';
            ctx.beginPath();
            ctx.roundRect(p.x, p.y, p.w, p.h, 3);
            ctx.fill();

            ctx.strokeStyle = '#e2e8f0';
            ctx.lineWidth = 2.0;
            ctx.stroke();

            ctx.fillStyle = 'rgba(255, 255, 255, 0.35)';
            ctx.beginPath();
            ctx.moveTo(p.x + 2, p.y + 2);
            ctx.lineTo(p.x + p.w - 4, p.y + 2);
            ctx.lineTo(p.x + 2, p.y + p.h - 4);
            ctx.closePath();
            ctx.fill();

            ctx.fillStyle = 'rgba(56, 189, 248, 0.25)';
            ctx.fillRect(p.x + 3, p.y + p.h - 8, p.w - 6, 6);
        });
    }

    drawCockpitWindows();

    // Nose Radome Seam Line
    ctx.strokeStyle = 'rgba(180, 190, 205, 0.6)';
    ctx.lineWidth = 2.0;
    ctx.beginPath();
    ctx.moveTo(135, 0);
    ctx.lineTo(135, canvas.height);
    ctx.stroke();

    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.ClampToEdgeWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    return texture;
}

export function createEngineTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 1024;
    canvas.height = 512;
    const ctx = canvas.getContext('2d');

    // Base Nacelle White Composite
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Front Intake Lip Shadow Gradient
    const lipGrad = ctx.createLinearGradient(0, 0, 80, 0);
    lipGrad.addColorStop(0, '#64748b');
    lipGrad.addColorStop(0.3, '#cbd5e1');
    lipGrad.addColorStop(1, '#f8fafc');
    ctx.fillStyle = lipGrad;
    ctx.fillRect(0, 0, 80, canvas.height);

    // Boeing Blue Accent Ring around Cowling (Station X = 120-145)
    ctx.fillStyle = '#002855';
    ctx.fillRect(120, 0, 25, canvas.height);
    ctx.fillStyle = '#c5a059';
    ctx.fillRect(145, 0, 5, canvas.height);

    // Engine Cowling Panel Seams
    ctx.strokeStyle = 'rgba(180, 195, 210, 0.5)';
    ctx.lineWidth = 2.0;
    ctx.beginPath();
    ctx.moveTo(320, 0);
    ctx.lineTo(320, canvas.height);
    ctx.moveTo(680, 0);
    ctx.lineTo(680, canvas.height);
    ctx.stroke();

    // Warning Stencil
    ctx.fillStyle = '#e11d48';
    ctx.font = 'bold 14px monospace';
    ctx.fillText('DANGER: INTAKE', 170, 120);
    ctx.fillText('DANGER: INTAKE', 170, 380);

    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    return texture;
}

export function createWingTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 1024;
    canvas.height = 1024;
    const ctx = canvas.getContext('2d');

    ctx.fillStyle = '#dbe1e8';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = 'rgba(160, 175, 195, 0.35)';
    ctx.lineWidth = 1.5;
    for (let x = 80; x < canvas.width; x += 120) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvas.height);
        ctx.stroke();
    }

    ctx.strokeStyle = 'rgba(120, 135, 155, 0.5)';
    ctx.lineWidth = 2.0;
    ctx.strokeRect(60, 700, canvas.width - 120, 260);

    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    return texture;
}

export function createTailTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 1024;
    canvas.height = 1024;
    const ctx = canvas.getContext('2d');

    const grad = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    grad.addColorStop(0, '#002244');
    grad.addColorStop(0.4, '#004080');
    grad.addColorStop(1, '#001a33');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Dynamic White Boeing Sweep/Wave Logo Markings
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 16;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(150, 800);
    ctx.bezierCurveTo(350, 500, 650, 450, 900, 150);
    ctx.stroke();

    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 6;
    ctx.beginPath();
    ctx.moveTo(200, 840);
    ctx.bezierCurveTo(400, 540, 700, 490, 920, 190);
    ctx.stroke();

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 84px -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
    ctx.fillText('747', 400, 450);

    ctx.font = 'bold 28px -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
    ctx.fillStyle = '#93c5fd';
    ctx.fillText('BOEING', 410, 495);

    ctx.strokeStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(680, 0);
    ctx.lineTo(680, canvas.height);
    ctx.stroke();

    return new THREE.CanvasTexture(canvas);
}

export function createSpinnerTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 512;
    const ctx = canvas.getContext('2d');

    ctx.fillStyle = '#111317';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 16;
    ctx.lineCap = 'round';
    ctx.beginPath();
    const cx = 256, cy = 256;
    for (let a = 0; a < Math.PI * 4; a += 0.05) {
        const r = a * 18;
        const x = cx + Math.cos(a) * r;
        const y = cy + Math.sin(a) * r;
        if (a === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();

    return new THREE.CanvasTexture(canvas);
}

export function createRunwayTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 2048;
    canvas.height = 2048;
    const ctx = canvas.getContext('2d');

    ctx.fillStyle = '#1e2229';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imgData.data;
    for (let i = 0; i < data.length; i += 4) {
        const noise = (Math.random() - 0.5) * 16;
        data[i] = Math.min(255, Math.max(0, data[i] + noise));
        data[i + 1] = Math.min(255, Math.max(0, data[i + 1] + noise));
        data[i + 2] = Math.min(255, Math.max(0, data[i + 2] + noise));
    }
    ctx.putImageData(imgData, 0, 0);

    ctx.fillStyle = '#f8fafc';
    for (let z = 0; z < canvas.height; z += 180) {
        ctx.fillRect(canvas.width / 2 - 14, z, 28, 100);
    }

    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(180, 0, 16, canvas.height);
    ctx.fillRect(canvas.width - 196, 0, 16, canvas.height);

    ctx.fillStyle = 'rgba(10, 12, 16, 0.4)';
    for (let i = 0; i < 45; i++) {
        const x = canvas.width / 2 + (Math.random() - 0.5) * 140;
        const y = Math.random() * canvas.height;
        const w = 12 + Math.random() * 22;
        const h = 70 + Math.random() * 160;
        ctx.fillRect(x, y, w, h);
    }

    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(4, 16);
    return texture;
}

export function createTireTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 256;
    const ctx = canvas.getContext('2d');

    ctx.fillStyle = '#1c1f24';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.fillStyle = '#0b0d10';
    for (let x = 16; x < canvas.width; x += 36) {
        ctx.fillRect(x, 0, 14, canvas.height);
    }

    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(1, 4);
    return texture;
}

export function createMaterials() {
    const fuselageTex = createFuselageTexture();
    const engineTex = createEngineTexture();
    const wingTex = createWingTexture();
    const tailTex = createTailTexture();
    const spinnerTex = createSpinnerTexture();
    const tireTex = createTireTexture();
    const runwayTex = createRunwayTexture();

    return {
        fuselage: new THREE.MeshStandardMaterial({
            map: fuselageTex,
            roughness: 0.25,
            metalness: 0.12,
            side: THREE.DoubleSide,
        }),

        wings: new THREE.MeshStandardMaterial({
            map: wingTex,
            roughness: 0.35,
            metalness: 0.22,
            side: THREE.DoubleSide,
        }),

        tailLivery: new THREE.MeshStandardMaterial({
            map: tailTex,
            roughness: 0.28,
            metalness: 0.2,
            side: THREE.DoubleSide,
        }),

        engineCowling: new THREE.MeshStandardMaterial({
            map: engineTex,
            roughness: 0.22,
            metalness: 0.12,
            side: THREE.DoubleSide,
        }),

        polishedAluminum: new THREE.MeshStandardMaterial({
            color: 0xf1f5f9,
            roughness: 0.08,
            metalness: 0.96,
        }),

        exhaustTitanium: new THREE.MeshStandardMaterial({
            color: 0x3b3a36,
            roughness: 0.52,
            metalness: 0.88,
        }),

        turbineInterior: new THREE.MeshStandardMaterial({
            color: 0x0f1115,
            roughness: 0.8,
            metalness: 0.4,
            side: THREE.DoubleSide,
        }),

        fanBlades: new THREE.MeshStandardMaterial({
            color: 0x64748b,
            roughness: 0.18,
            metalness: 0.94,
        }),

        spinner: new THREE.MeshStandardMaterial({
            map: spinnerTex,
            roughness: 0.25,
            metalness: 0.25,
        }),

        cockpitGlass: new THREE.MeshPhysicalMaterial({
            color: 0x08101a,
            roughness: 0.03,
            metalness: 0.2,
            transmission: 0.6,
            transparent: true,
            opacity: 0.92,
            ior: 1.55,
            reflectivity: 0.98,
        }),

        cockpitFrame: new THREE.MeshStandardMaterial({
            color: 0x1e293b,
            roughness: 0.3,
            metalness: 0.85,
        }),

        fairingWhite: new THREE.MeshStandardMaterial({
            color: 0xf8fafc,
            roughness: 0.28,
            metalness: 0.12,
        }),

        gearStrut: new THREE.MeshStandardMaterial({
            color: 0x64748b,
            roughness: 0.25,
            metalness: 0.82,
        }),

        hydraulicChrome: new THREE.MeshStandardMaterial({
            color: 0xffffff,
            roughness: 0.04,
            metalness: 0.98,
        }),

        wheelHub: new THREE.MeshStandardMaterial({
            color: 0x334155,
            roughness: 0.32,
            metalness: 0.78,
        }),

        tireRubber: new THREE.MeshStandardMaterial({
            map: tireTex,
            roughness: 0.85,
            metalness: 0.05,
        }),

        navLightRed: new THREE.MeshStandardMaterial({
            color: 0xff0033,
            emissive: 0xff0033,
            emissiveIntensity: 4.0,
            roughness: 0.15,
        }),

        navLightGreen: new THREE.MeshStandardMaterial({
            color: 0x00ff66,
            emissive: 0x00ff66,
            emissiveIntensity: 4.0,
            roughness: 0.15,
        }),

        strobeWhite: new THREE.MeshStandardMaterial({
            color: 0xffffff,
            emissive: 0xffffff,
            emissiveIntensity: 5.5,
            roughness: 0.1,
        }),

        beaconRed: new THREE.MeshStandardMaterial({
            color: 0xff1100,
            emissive: 0xff1100,
            emissiveIntensity: 4.5,
            roughness: 0.15,
        }),

        runway: new THREE.MeshStandardMaterial({
            map: runwayTex,
            roughness: 0.88,
            metalness: 0.08,
        }),
    };
}
