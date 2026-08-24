import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { gsap } from 'gsap';

const WebGLBackground: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // --- SETUP ---
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 5;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    containerRef.current.appendChild(renderer.domElement);

    // --- PARTICLES ---
    const particlesCount = 6000;
    const positions = new Float32Array(particlesCount * 3);
    const colors = new Float32Array(particlesCount * 3);
    const sizes = new Float32Array(particlesCount);

    const colorPalette = [
      new THREE.Color('#3b82f6'), // Blue
      new THREE.Color('#8b5cf6'), // Purple
      new THREE.Color('#06b6d4'), // Cyan
      new THREE.Color('#ffffff')  // White
    ];

    for (let i = 0; i < particlesCount; i++) {
      const r = 4 + Math.random() * 4;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);

      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);

      const color = colorPalette[Math.floor(Math.random() * colorPalette.length)];
      colors[i * 3] = color.r;
      colors[i * 3 + 1] = color.g;
      colors[i * 3 + 2] = color.b;

      sizes[i] = Math.random() * 0.05;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    const material = new THREE.PointsMaterial({
      size: 0.02,
      vertexColors: true,
      transparent: true,
      opacity: 0.4,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true
    });

    const particleSystem = new THREE.Points(geometry, material);
    scene.add(particleSystem);

    // --- MOUSE INTERACTION ---
    let mouseX = 0;
    let mouseY = 0;
    let targetX = 0;
    let targetY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      targetX = (e.clientX - window.innerWidth / 2) * 0.0005;
      targetY = (e.clientY - window.innerHeight / 2) * 0.0005;
    };

    window.addEventListener('mousemove', handleMouseMove);

    // --- ANIMATION LOOP ---
    const clock = new THREE.Clock();
    let animationFrameId: number;

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);

      const elapsedTime = clock.getElapsedTime();

      // Smooth mouse follow
      mouseX += (targetX - mouseX) * 0.05;
      mouseY += (targetY - mouseY) * 0.05;

      // Rotate particle system
      particleSystem.rotation.y = elapsedTime * 0.03 + mouseX;
      particleSystem.rotation.x = -mouseY;

      // Subtle wave pulse
      const posArray = geometry.attributes.position.array as Float32Array;
      for (let i = 0; i < particlesCount; i++) {
        const x = posArray[i * 3];
        posArray[i * 3 + 2] += Math.sin(elapsedTime * 0.5 + x * 0.2) * 0.0005;
      }
      geometry.attributes.position.needsUpdate = true;

      renderer.render(scene, camera);
    };

    animate();

    // --- INTRO ---
    gsap.from(camera.position, {
      z: 10,
      duration: 3,
      ease: 'power3.out'
    });

    // --- RESIZE ---
    const handleResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };

    window.addEventListener('resize', handleResize);

    // --- CLEANUP ---
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animationFrameId);
      if (containerRef.current) {
        containerRef.current.removeChild(renderer.domElement);
      }
      geometry.dispose();
      material.dispose();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 pointer-events-none overflow-hidden"
      style={{ zIndex: 5 }}
    />
  );
};

export default WebGLBackground;
