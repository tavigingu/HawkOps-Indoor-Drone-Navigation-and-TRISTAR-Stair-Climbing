import React, { useRef, useEffect, useMemo } from 'react';
import { useFrame, useLoader } from '@react-three/fiber';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader';
import * as THREE from 'three';

// Real anatomy of the Tello GLB, recovered from its node graph:
//   • nodes named "pervane" (TR: propeller) hold each rotor — the blade sits
//     directly under the pervane node, the long arm/leg sits under a Cube node.
//   • "govde" (body), "kapak" (cover), "Text.001" (the TELLO logo).
// Parts share materials (all black parts use one material), so we classify by
// ancestry + material and clone each mesh's material to highlight it alone.
const COMPONENT_DEFS = [
  { id: 'propellers', label: 'Propellers' },
  { id: 'motors', label: 'Motors' },
  { id: 'body', label: 'Body & arms' },
  { id: 'camera', label: 'Camera' },
  { id: 'casing', label: 'Body casing' },
  { id: 'branding', label: 'TELLO branding' },
];

const EMISSIVE_BASE = new THREE.Color(0x05140d);
const EMISSIVE_BASE_INTENSITY = 0.4;
const HIGHLIGHT_COLOR = new THREE.Color('#2fe38b');

// Classify a mesh into one of the components above using its node ancestry
// (robust against the GLB's generic mesh names) and material name.
function classifyMesh(mesh) {
  const ancestry = [];
  let p = mesh.parent;
  while (p) { ancestry.push((p.name || '').toLowerCase()); p = p.parent; }
  const matName = mesh.material?.name || '';

  if (ancestry.some((n) => n.startsWith('pervane'))) return 'propellers'; // whole rotor: hub + blade
  if (matName === 'metalimsi') return 'motors'; // the metallic cylinder barrels under the arms
  if (matName === 'yaz_rengi') return 'branding'; // TELLO text
  if (matName === 'beyaz_ke') return 'casing'; // white shell
  if (matName === 'Material.001') return 'camera'; // front lens
  return 'body'; // govde body + kapak cover (incl. the arms/legs)
}

// ── Drone model ───────────────────────────────────────────────────────────
// Loads the GLB, applies a refined metallic material pass, plays the embedded
// propeller animation on connect, and exposes its material groups so an
// external panel can highlight individual components on hover.
export function DroneModel({ scrollY, isConnected = false, highlightId = null, onComponentsReady }) {
  const groupRef = useRef();
  const mixerRef = useRef(null);
  const clockRef = useRef(new THREE.Clock());
  const componentsRef = useRef(null);
  const highlightRef = useRef(null);
  const gltf = useLoader(GLTFLoader, '/assets/dji_tello.glb');

  useEffect(() => {
    if (!gltf.scene) return;

    const comps = new Map(COMPONENT_DEFS.map((d) => [d.id, []]));
    gltf.scene.traverse((child) => {
      if (child.isMesh && child.material) {
        // clone so each mesh can be highlighted independently of parts that
        // happen to share the same source material (e.g. blades vs arms).
        child.material = child.material.clone();
        child.material.metalness = 0.75;
        child.material.roughness = 0.28;
        child.castShadow = true;
        child.receiveShadow = true;
        child.material.emissive = EMISSIVE_BASE.clone();
        child.material.emissiveIntensity = EMISSIVE_BASE_INTENSITY;
        child.material.needsUpdate = true;

        const compId = classifyMesh(child);
        if (comps.has(compId)) comps.get(compId).push(child);
      }
    });
    componentsRef.current = comps;

    // Publish only the components that actually have geometry, in order.
    if (typeof onComponentsReady === 'function') {
      onComponentsReady(
        COMPONENT_DEFS
          .filter((d) => (comps.get(d.id) || []).length > 0)
          .map((d) => ({ id: d.id, label: d.label, count: comps.get(d.id).length }))
      );
    }

    if (gltf.animations && gltf.animations.length > 0) {
      const animationMixer = new THREE.AnimationMixer(gltf.scene);
      mixerRef.current = animationMixer;
      gltf.animations.forEach((clip) => {
        const action = animationMixer.clipAction(clip);
        action.setLoop(THREE.LoopRepeat);
        action.timeScale = 1.0;
        if (isConnected) action.play();
      });
    }
  }, [gltf]);

  // Start/stop the propellers on connection changes, matched to the HUD focus.
  useEffect(() => {
    if (!mixerRef.current || !gltf.animations) return;

    if (isConnected) {
      const delayTimer = setTimeout(() => {
        gltf.animations.forEach((clip) => {
          const action = mixerRef.current.clipAction(clip);
          action.timeScale = 1.0;
          action.play();
        });
      }, 1200);
      return () => clearTimeout(delayTimer);
    }

    const stopTimer = setTimeout(() => {
      gltf.animations.forEach((clip) => {
        mixerRef.current.clipAction(clip).stop();
      });
    }, 1200);
    return () => clearTimeout(stopTimer);
  }, [isConnected, gltf.animations]);

  // Highlight every mesh in the hovered component; restore the rest to base.
  useEffect(() => {
    highlightRef.current = highlightId;
    const comps = componentsRef.current;
    if (!comps) return;
    comps.forEach((meshes, id) => {
      const on = id === highlightId;
      meshes.forEach((m) => {
        if (on) {
          m.material.emissive.copy(HIGHLIGHT_COLOR);
          m.material.emissiveIntensity = 0.9;
        } else {
          m.material.emissive.copy(EMISSIVE_BASE);
          m.material.emissiveIntensity = EMISSIVE_BASE_INTENSITY;
        }
      });
    });
  }, [highlightId]);

  useFrame(() => {
    if (mixerRef.current) {
      mixerRef.current.update(clockRef.current.getDelta());
    }
    // Gentle pulse on the highlighted component for a living "selected" feel.
    const comps = componentsRef.current;
    if (comps && highlightRef.current) {
      const meshes = comps.get(highlightRef.current);
      if (meshes && meshes.length) {
        const v = 0.7 + Math.sin(performance.now() * 0.006) * 0.3;
        meshes.forEach((m) => { m.material.emissiveIntensity = v; });
      }
    }
    if (groupRef.current) {
      groupRef.current.rotation.y += 0.003;
      const time = performance.now() * 0.001;
      const hoverOffset = Math.sin(time * 1.5) * 0.1;
      const scrollOffset = scrollY * 0.0003;
      groupRef.current.position.y = hoverOffset + scrollOffset;
      groupRef.current.rotation.x = Math.sin(time * 0.5) * 0.03;
      groupRef.current.rotation.z = Math.cos(time * 0.3) * 0.02;
    }
  });

  return (
    <group ref={groupRef} scale={[1, 1, 1]} position={[0, 0, 0]}>
      <primitive object={gltf.scene} />
    </group>
  );
}

// ── Particle field ────────────────────────────────────────────────────────
// Four layered point clouds in the emerald/teal palette for depth.
export function ParticleField() {
  const ref1 = useRef();
  const ref2 = useRef();
  const ref3 = useRef();
  const ref4 = useRef();

  const c1 = 1800;
  const c2 = 450;
  const c3 = 900;
  const c4 = 90;

  const particleTexture = useMemo(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    const ctx = canvas.getContext('2d');
    const g = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.5, 'rgba(255,255,255,0.45)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 32, 32);
    return new THREE.CanvasTexture(canvas);
  }, []);

  // emerald / mint / teal / white mix
  const palette = (t) => {
    if (t < 0.34) return [0.18, 0.89, 0.55]; // emerald
    if (t < 0.62) return [0.12, 0.85, 0.78]; // teal
    if (t < 0.84) return [0.55, 0.96, 0.78]; // mint
    return [0.85, 0.95, 0.9]; // near-white
  };

  const stars = useMemo(() => {
    const positions = new Float32Array(c1 * 3);
    const colors = new Float32Array(c1 * 3);
    for (let i = 0; i < c1; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 150;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 150;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 150;
      const [r, g, b] = palette(Math.random());
      colors[i * 3] = r;
      colors[i * 3 + 1] = g;
      colors[i * 3 + 2] = b;
    }
    return { positions, colors };
  }, []);

  const nebula = useMemo(() => {
    const positions = new Float32Array(c2 * 3);
    const colors = new Float32Array(c2 * 3);
    for (let i = 0; i < c2; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 100;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 100;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 100;
      const [r, g, b] = palette(Math.random() * 0.6);
      colors[i * 3] = r * 0.8;
      colors[i * 3 + 1] = g * 0.8;
      colors[i * 3 + 2] = b * 0.8;
    }
    return { positions, colors };
  }, []);

  const fast = useMemo(() => {
    const positions = new Float32Array(c3 * 3);
    const colors = new Float32Array(c3 * 3);
    const velocities = new Float32Array(c3 * 3);
    for (let i = 0; i < c3; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 120;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 120;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 120;
      colors[i * 3] = 0.16;
      colors[i * 3 + 1] = Math.random() * 0.4 + 0.6;
      colors[i * 3 + 2] = Math.random() * 0.3 + 0.6;
      velocities[i * 3] = (Math.random() - 0.5) * 0.02;
      velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.02;
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.02;
    }
    return { positions, colors, velocities };
  }, []);

  const orbs = useMemo(() => {
    const positions = new Float32Array(c4 * 3);
    const colors = new Float32Array(c4 * 3);
    for (let i = 0; i < c4; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 80;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 80;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 80;
      const [r, g, b] = palette(Math.random() * 0.6);
      colors[i * 3] = r;
      colors[i * 3 + 1] = g;
      colors[i * 3 + 2] = b;
    }
    return { positions, colors };
  }, []);

  useFrame((state) => {
    const time = state.clock.elapsedTime;

    if (ref1.current) {
      ref1.current.rotation.y += 0.0002;
      ref1.current.rotation.x += 0.0001;
      const p = ref1.current.geometry.attributes.position.array;
      for (let i = 0; i < c1; i++) p[i * 3 + 1] += Math.sin(time * 2 + i) * 0.01;
      ref1.current.geometry.attributes.position.needsUpdate = true;
    }
    if (ref2.current) {
      ref2.current.rotation.y -= 0.0001;
      ref2.current.scale.setScalar(1 + Math.sin(time * 0.3) * 0.15);
    }
    if (ref3.current) {
      const p = ref3.current.geometry.attributes.position.array;
      for (let i = 0; i < c3; i++) {
        p[i * 3] += fast.velocities[i * 3];
        p[i * 3 + 1] += fast.velocities[i * 3 + 1];
        p[i * 3 + 2] += fast.velocities[i * 3 + 2];
        if (Math.abs(p[i * 3]) > 60) p[i * 3] *= -0.5;
        if (Math.abs(p[i * 3 + 1]) > 60) p[i * 3 + 1] *= -0.5;
        if (Math.abs(p[i * 3 + 2]) > 60) p[i * 3 + 2] *= -0.5;
      }
      ref3.current.geometry.attributes.position.needsUpdate = true;
      ref3.current.rotation.y += 0.001;
    }
    if (ref4.current) {
      const p = ref4.current.geometry.attributes.position.array;
      for (let i = 0; i < c4; i++) p[i * 3 + 1] += Math.sin(time + i) * 0.02;
      ref4.current.geometry.attributes.position.needsUpdate = true;
      ref4.current.scale.setScalar(1 + Math.sin(time * 2) * 0.2);
    }
  });

  const layer = (ref, count, data, size, opacity) => (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={count} array={data.positions} itemSize={3} />
        <bufferAttribute attach="attributes-color" count={count} array={data.colors} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial
        size={size}
        vertexColors
        transparent
        opacity={opacity}
        sizeAttenuation
        blending={THREE.AdditiveBlending}
        depthWrite={false}
        map={particleTexture}
      />
    </points>
  );

  return (
    <group>
      {layer(ref1, c1, stars, 0.05, 0.85)}
      {layer(ref2, c2, nebula, 0.3, 0.65)}
      {layer(ref3, c3, fast, 0.04, 0.8)}
      {layer(ref4, c4, orbs, 0.4, 1.0)}
    </group>
  );
}

// ── Lighting ──────────────────────────────────────────────────────────────
export function LightingSetup() {
  const directionalRef = useRef();

  useFrame((state) => {
    if (directionalRef.current) {
      directionalRef.current.position.x = Math.sin(state.clock.elapsedTime * 0.5) * 5;
      directionalRef.current.position.z = Math.cos(state.clock.elapsedTime * 0.5) * 5;
    }
  });

  return (
    <>
      <ambientLight intensity={0.25} />
      <directionalLight
        ref={directionalRef}
        position={[10, 10, 5]}
        intensity={1.25}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
      />
      <pointLight position={[-10, -8, -5]} color="#2fe38b" intensity={0.9} distance={32} />
      <pointLight position={[10, -4, 10]} color="#1fd9c6" intensity={0.6} distance={24} />
      <pointLight position={[0, 6, -8]} color="#46f5a3" intensity={0.4} distance={26} />
    </>
  );
}
