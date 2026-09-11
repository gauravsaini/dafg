import * as THREE from 'three';

/**
 * Procedural PBR Texture Generator for Boeing 747
 * Produces crisp high-res 2048x2048 canvas textures without external image dependencies.
 */

export function createFuselageTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 2048;
  canvas.height = 1024;
  const ctx = canvas.getContext('2d');

  // Base aviation white with subtle pearl gradient
  const grad = ctx.createLinearGradient(0, 0, 0, canvas.height);
  grad.addColorStop(0, '#f8fafc');
  grad.addColorStop(0.5, '#ffffff');
  grad.addColorStop(1, '#f1f5f9');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Modern Boeing / Airline Livery: Navy blue lower belly swoosh
  ctx.fillStyle = '#0f2744';
  ctx.beginPath();
  ctx.moveTo(0, canvas.height * 0.72);
  ctx.bezierCurveTo(
    canvas.width * 0.25, canvas.height * 0.68,
    canvas.width * 0.55, canvas.height * 0.62,
    canvas.width, canvas.height * 0.58
  );
  ctx.lineTo(canvas.width, canvas.height);
  ctx.lineTo(0, canvas.height);
  ctx.closePath();
  ctx.fill();

  // Cyan / Sky Blue accent stripe
  ctx.strokeStyle = '#0284c7';
  ctx.lineWidth = 14;
  ctx.beginPath();
  ctx.moveTo(0, canvas.height * 0.71);
  ctx.bezierCurveTo(
    canvas.width * 0.25, canvas.height * 0.67,
    canvas.width * 0.55, canvas.height * 0.61,
    canvas.width, canvas.height * 0.57
  );
  ctx.stroke();

  // Golden accent pinstripe
  ctx.strokeStyle = '#eab308';
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.moveTo(0, canvas.height * 0.70);
  ctx.bezierCurveTo(
    canvas.width * 0.25, canvas.height * 0.66,
    canvas.width * 0.55, canvas.height * 0.60,
    canvas.width, canvas.height * 0.56
  );
  ctx.stroke();

  // Metal panel seams & expansion joints (subtle light gray)
  ctx.strokeStyle = 'rgba(150, 160, 175, 0.35)';
  ctx.lineWidth = 2;
  for (let x = 60; x < canvas.width; x += 65) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvas.height * 0.75);
    ctx.stroke();
  }

  // Longitudinal stringer lines
  for (let y = 120; y < canvas.height * 0.7; y += 75) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(canvas.width, y);
    ctx.stroke();
  }

  // Rivet rows (subtle dots along panel lines)
  ctx.fillStyle = 'rgba(120, 130, 145, 0.4)';
  for (let x = 60; x < canvas.width; x += 65) {
    for (let y = 100; y < canvas.height * 0.75; y += 18) {
      ctx.beginPath();
      ctx.arc(x, y, 1.2, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // Main Deck Passenger Window Frames (Port & Starboard strips)
  ctx.fillStyle = '#1e293b';
  const winY = canvas.height * 0.46;
  for (let x = 280; x < canvas.width * 0.85; x += 22) {
    // Skip door sections
    if ((x > 380 && x < 430) || (x > 750 && x < 800) || (x > 1150 && x < 1200) || (x > 1520 && x < 1570)) continue;
    
    // Window frame
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.8)';
    ctx.lineWidth = 2;
    ctx.strokeRect(x - 5, winY - 9, 10, 18);
    
    // Window glass
    ctx.fillRect(x - 4, winY - 8, 8, 16);
    
    // Glass reflection highlight
    ctx.fillStyle = 'rgba(255, 255, 255, 0.35)';
    ctx.fillRect(x - 3, winY - 7, 3, 5);
    ctx.fillStyle = '#1e293b';
  }

  // Upper Deck (Hump) Passenger Windows
  const upperWinY = canvas.height * 0.28;
  for (let x = 240; x < 520; x += 20) {
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.8)';
    ctx.lineWidth = 2;
    ctx.strokeRect(x - 4, upperWinY - 7, 8, 14);
    ctx.fillRect(x - 3, upperWinY - 6, 6, 12);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.35)';
    ctx.fillRect(x - 2, upperWinY - 5, 2, 4);
    ctx.fillStyle = '#1e293b';
  }

  // Passenger Entry & Emergency Exit Doors with red indicator outline & handles
  const doorLocations = [
    { x: 210, y: canvas.height * 0.43, w: 22, h: 46, label: 'L1' },
    { x: 410, y: canvas.height * 0.43, w: 22, h: 46, label: 'L2' },
    { x: 775, y: canvas.height * 0.43, w: 22, h: 46, label: 'L3' },
    { x: 1175, y: canvas.height * 0.43, w: 22, h: 46, label: 'L4' },
    { x: 1545, y: canvas.height * 0.43, w: 22, h: 46, label: 'L5' }
  ];

  doorLocations.forEach(d => {
    // Door outline
    ctx.strokeStyle = '#ef4444';
    ctx.lineWidth = 2.5;
    ctx.strokeRect(d.x, d.y, d.w, d.h);

    ctx.strokeStyle = 'rgba(100, 116, 139, 0.9)';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(d.x + 2, d.y + 2, d.w - 4, d.h - 4);

    // Door small observation window
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(d.x + d.w / 2 - 2, d.y + 8, 4, 10);

    // Door handle
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(d.x + d.w - 6, d.y + 24, 4, 3);
  });

  // Aircraft Livery Text & Typography: "BOEING 747-8"
  ctx.save();
  ctx.fillStyle = '#0f2744';
  ctx.font = 'bold 36px Arial, Helvetica, sans-serif';
  ctx.fillText('BOEING 747-8', 560, canvas.height * 0.38);

  ctx.fillStyle = '#0284c7';
  ctx.font = 'italic 20px Arial, Helvetica, sans-serif';
  ctx.fillText('INTERCONTINENTAL', 565, canvas.height * 0.42);

  // Registration Number & Flag near aft fuselage
  ctx.fillStyle = '#334155';
  ctx.font = 'bold 22px monospace';
  ctx.fillText('N747AG', 1650, canvas.height * 0.50);

  // Pitot Tube & Angle of Attack Sensors warning marks near nose
  ctx.strokeStyle = '#dc2626';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(110, canvas.height * 0.45, 14, 14);
  ctx.strokeRect(140, canvas.height * 0.48, 14, 14);
  ctx.restore();

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.anisotropy = 8;
  return texture;
}

export function createFuselageBumpMap() {
  const canvas = document.createElement('canvas');
  canvas.width = 2048;
  canvas.height = 1024;
  const ctx = canvas.getContext('2d');

  // Neutral gray 128
  ctx.fillStyle = '#808080';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Indented panel seams (dark lines)
  ctx.strokeStyle = '#404040';
  ctx.lineWidth = 2;
  for (let x = 60; x < canvas.width; x += 65) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvas.height);
    ctx.stroke();
  }

  for (let y = 120; y < canvas.height; y += 75) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(canvas.width, y);
    ctx.stroke();
  }

  // Rivet bumps (raised dots = bright center, dark ring)
  ctx.fillStyle = '#b0b0b0';
  for (let x = 60; x < canvas.width; x += 65) {
    for (let y = 100; y < canvas.height * 0.8; y += 18) {
      ctx.beginPath();
      ctx.arc(x, y, 1.2, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  return texture;
}

export function createWingTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 1024;
  const ctx = canvas.getContext('2d');

  // Boeing gray aerodynamic wing finish
  ctx.fillStyle = '#cbd5e1';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Polished leading edge anti-ice chrome strip
  const chromeGrad = ctx.createLinearGradient(0, 0, 180, 0);
  chromeGrad.addColorStop(0, '#f1f5f9');
  chromeGrad.addColorStop(0.3, '#e2e8f0');
  chromeGrad.addColorStop(1, '#94a3b8');
  ctx.fillStyle = chromeGrad;
  ctx.fillRect(0, 0, 160, canvas.height);

  // Fuel tank panel access covers (rectangular inspection doors)
  ctx.strokeStyle = '#64748b';
  ctx.lineWidth = 2;
  for (let y = 120; y < canvas.height - 120; y += 90) {
    for (let x = 220; x < 700; x += 110) {
      ctx.fillStyle = '#e2e8f0';
      ctx.fillRect(x, y, 45, 25);
      ctx.strokeRect(x, y, 45, 25);

      // Fasteners around panel
      ctx.fillStyle = '#475569';
      ctx.fillRect(x + 2, y + 2, 2, 2);
      ctx.fillRect(x + 41, y + 2, 2, 2);
      ctx.fillRect(x + 2, y + 21, 2, 2);
      ctx.fillRect(x + 41, y + 21, 2, 2);
    }
  }

  // Black dashed wing walkway / escape route corridor
  ctx.strokeStyle = '#0f172a';
  ctx.lineWidth = 4;
  ctx.setLineDash([12, 8]);
  ctx.strokeRect(200, 150, 480, 720);
  ctx.setLineDash([]);

  // "NO STEP" caution stencils in red/black
  ctx.fillStyle = '#dc2626';
  ctx.font = 'bold 16px monospace';
  ctx.fillText('NO STEP', 720, 300);
  ctx.fillText('NO STEP', 720, 500);
  ctx.fillText('NO STEP', 720, 700);

  // Flap / Slat break lines
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(800, 0);
  ctx.lineTo(800, canvas.height);
  ctx.stroke();

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  return texture;
}

export function createTurbineSpiralTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');

  // Dark gunmetal / titanium base
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Concentric machined titanium rings
  ctx.strokeStyle = '#334155';
  for (let r = 20; r < 240; r += 15) {
    ctx.beginPath();
    ctx.arc(canvas.width / 2, canvas.height / 2, r, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Iconic GE/Boeing white spiral swirl on spinner cone
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 14;
  ctx.lineCap = 'round';
  ctx.beginPath();
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  for (let a = 0; a < Math.PI * 4; a += 0.05) {
    const r = a * 18;
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a) * r;
    if (a === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  const texture = new THREE.CanvasTexture(canvas);
  return texture;
}

export function createTireTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');

  // Dark charcoal rubber
  ctx.fillStyle = '#1c1917';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Tire circumferential water displacement tread grooves
  ctx.fillStyle = '#09090b';
  for (let y = 30; y < canvas.height - 30; y += 45) {
    ctx.fillRect(0, y, canvas.width, 18);
  }

  // Subtle rubber texture speckles
  ctx.fillStyle = '#292524';
  for (let i = 0; i < 1500; i++) {
    const rx = Math.random() * canvas.width;
    const ry = Math.random() * canvas.height;
    ctx.fillRect(rx, ry, 2, 2);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  return texture;
}

export function createRunwayTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 2048;
  canvas.height = 2048;
  const ctx = canvas.getContext('2d');

  // Heavy dark airport asphalt tarmac
  ctx.fillStyle = '#1e2022';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Asphalt noise & texture grain
  for (let i = 0; i < 20000; i++) {
    const rx = Math.random() * canvas.width;
    const ry = Math.random() * canvas.height;
    const val = Math.random() > 0.5 ? 45 : 25;
    ctx.fillStyle = ;
    ctx.fillRect(rx, ry, Math.random() * 3 + 1, Math.random() * 3 + 1);
  }

  // Runway Threshold Piano Keys (16 large white bars at threshold)
  ctx.fillStyle = '#f8fafc';
  const barW = 32;
  const barH = 260;
  const startX = 240;
  for (let i = 0; i < 16; i++) {
    ctx.fillRect(startX + i * 96, 60, barW, barH);
  }

  // Runway Designation "27L"
  ctx.fillStyle = '#f8fafc';
  ctx.font = 'bold 120px Arial, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('27L', canvas.width / 2, 450);

  // Dashed Centerline Stripes
  ctx.fillStyle = '#ffffff';
  for (let y = 580; y < canvas.height; y += 180) {
    ctx.fillRect(canvas.width / 2 - 12, y, 24, 110);
  }

  // Touchdown Zone Markings (pairs of solid white bars)
  for (let y = 700; y < canvas.height; y += 350) {
    ctx.fillRect(canvas.width / 2 - 320, y, 90, 160);
    ctx.fillRect(canvas.width / 2 - 200, y, 90, 160);
    ctx.fillRect(canvas.width / 2 + 110, y, 90, 160);
    ctx.fillRect(canvas.width / 2 + 230, y, 90, 160);
  }

  // Rubber skid marks along touchdown zone
  ctx.fillStyle = 'rgba(10, 10, 10, 0.45)';
  for (let i = 0; i < 60; i++) {
    const rx = canvas.width / 2 + (Math.random() - 0.5) * 450;
    const ry = 650 + Math.random() * 1200;
    ctx.fillRect(rx, ry, Math.random() * 14 + 6, Math.random() * 80 + 30);
  }

  // Runway side edge boundary solid white lines
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(80, 0, 16, canvas.height);
  ctx.fillRect(canvas.width - 96, 0, 16, canvas.height);

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(1, 4);
  return texture;
}
