/* The reactor, mounted.
 *
 * The component's only job is owning the canvas element and its lifetime. The
 * drawing lives in reactor.ts and runs outside React entirely — sixty frames a
 * second is no place for a render cycle.
 *
 * State and mic level are passed through a mutable ref rather than as props to
 * the loop: changing them must not tear down and restart the animation, or the
 * rings would snap back to zero every time Jarvis started thinking.
 */
import { useEffect, useRef } from "react";

import { mountReactor, type ReactorInput, type ReactorState } from "./reactorEngine";

export function Reactor({ state, level = 0 }: { state: ReactorState; level?: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const input = useRef<ReactorInput>({ state, level });

  input.current.state = state;
  input.current.level = level;

  useEffect(() => {
    if (!canvas.current) return;
    return mountReactor(canvas.current, input.current);
  }, []);

  return (
    <canvas
      ref={canvas}
      className="reactor"
      role="img"
      aria-label={`Jarvis is ${state}`}
    />
  );
}
