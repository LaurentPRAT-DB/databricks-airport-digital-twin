import { useCallback, type MutableRefObject } from 'react';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import * as THREE from 'three';

interface NavigationControls3DProps {
  controlsRef: MutableRefObject<OrbitControlsImpl | null>;
}

/** Duration (ms) for smooth camera transitions */
const ANIM_DURATION = 400;

/** Animate from current value to target over duration using easeInOutCubic */
function animateCamera(
  controls: OrbitControlsImpl,
  targetPos: THREE.Vector3,
  targetTarget: THREE.Vector3,
  duration = ANIM_DURATION
) {
  const camera = controls.object as THREE.PerspectiveCamera;
  const startPos = camera.position.clone();
  const startTarget = controls.target.clone();
  const startTime = performance.now();

  function ease(t: number) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  function tick() {
    const elapsed = performance.now() - startTime;
    const t = Math.min(elapsed / duration, 1);
    const e = ease(t);

    camera.position.lerpVectors(startPos, targetPos, e);
    controls.target.lerpVectors(startTarget, targetTarget, e);
    controls.update();

    if (t < 1) requestAnimationFrame(tick);
  }

  requestAnimationFrame(tick);
}

export function NavigationControls3D({ controlsRef }: NavigationControls3DProps) {
  const handleHome = useCallback(() => {
    const c = controlsRef.current;
    if (!c) return;
    // Reset to default overview: camera above and south of origin
    const distance = c.object.position.distanceTo(c.target);
    const d = Math.max(distance, 200);
    animateCamera(
      c,
      new THREE.Vector3(0, d * 0.8, d * 0.5),
      new THREE.Vector3(0, 0, 0)
    );
  }, [controlsRef]);

  const handleNorthUp = useCallback(() => {
    const c = controlsRef.current;
    if (!c) return;
    const camera = c.object as THREE.PerspectiveCamera;
    // Keep same distance and elevation, rotate so camera is due south (north is up)
    const offset = camera.position.clone().sub(c.target);
    const distance = offset.length();
    const polar = Math.acos(Math.max(-1, Math.min(1, offset.y / distance)));
    // North-up means camera is along +Z from target
    const horizontalDist = distance * Math.sin(polar);
    const height = distance * Math.cos(polar);
    animateCamera(
      c,
      new THREE.Vector3(c.target.x, c.target.y + height, c.target.z + horizontalDist),
      c.target.clone()
    );
  }, [controlsRef]);

  const handleTopDown = useCallback(() => {
    const c = controlsRef.current;
    if (!c) return;
    const camera = c.object as THREE.PerspectiveCamera;
    const distance = camera.position.distanceTo(c.target);
    const d = Math.max(distance, 100);
    // Straight above the current target
    animateCamera(
      c,
      new THREE.Vector3(c.target.x, d, c.target.z + 0.01), // tiny Z offset to avoid gimbal lock
      c.target.clone()
    );
  }, [controlsRef]);

  const handleZoom = useCallback((factor: number) => {
    const c = controlsRef.current;
    if (!c) return;
    const camera = c.object as THREE.PerspectiveCamera;
    const offset = camera.position.clone().sub(c.target);
    const newDistance = Math.max(c.minDistance, Math.min(c.maxDistance, offset.length() * factor));
    offset.normalize().multiplyScalar(newDistance);
    animateCamera(
      c,
      c.target.clone().add(offset),
      c.target.clone()
    );
  }, [controlsRef]);

  const btnClass =
    'w-9 h-9 flex items-center justify-center bg-white hover:bg-gray-100 active:bg-gray-200 text-gray-700 transition-colors cursor-pointer border-0 outline-none';

  return (
    <div
      className="absolute bottom-28 right-3 z-10 flex flex-col rounded-lg shadow-lg overflow-hidden border border-gray-200"
      style={{ pointerEvents: 'auto' }}
    >
      {/* Home */}
      <button className={btnClass} onClick={handleHome} title="Reset view">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          <polyline points="9 22 9 12 15 12 15 22" />
        </svg>
      </button>

      {/* North Up */}
      <button className={`${btnClass} border-t border-gray-200`} onClick={handleNorthUp} title="North up">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <text x="12" y="16" textAnchor="middle" fill="currentColor" stroke="none" fontSize="12" fontWeight="bold">N</text>
          <path d="M12 2v4" strokeWidth="2.5" />
        </svg>
      </button>

      {/* Top Down */}
      <button className={`${btnClass} border-t border-gray-200`} onClick={handleTopDown} title="Top-down view">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="5" r="3" />
          <line x1="12" y1="8" x2="12" y2="18" />
          <polyline points="8 14 12 18 16 14" />
        </svg>
      </button>

      {/* Zoom In */}
      <button className={`${btnClass} border-t border-gray-200`} onClick={() => handleZoom(0.7)} title="Zoom in">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </button>

      {/* Zoom Out */}
      <button className={`${btnClass} border-t border-gray-200`} onClick={() => handleZoom(1.4)} title="Zoom out">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </button>
    </div>
  );
}
