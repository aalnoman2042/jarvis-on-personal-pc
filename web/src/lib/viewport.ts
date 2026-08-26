/* How tall the screen really is, once the keyboard is on it.
 *
 * `height: 100%` and `100vh` both measure the *window*, and on Android the
 * window does not shrink when the on-screen keyboard opens — the keyboard is
 * drawn over it. So the layout keeps believing it has a full screen, the
 * composer stays where it was, and the thing you are typing into is behind the
 * keyboard. Which is precisely the bug: you tap the box, it disappears.
 *
 * `100dvh` fixes the address bar, not this. The only thing that actually knows
 * is `visualViewport` — the rectangle you can currently see — so its height
 * becomes a CSS variable and the shell is sized from that instead.
 *
 * A `keyboard-up` class rides along on <html>, because knowing the keyboard is
 * open is worth more than the height alone: with ~300px gone, the arc reactor
 * is a luxury and the conversation is the point, so the CSS shrinks one to keep
 * the other readable.
 */

const KEYBOARD_MARGIN = 120; // px of lost height that means "a keyboard", not a toolbar

export function trackViewport(): () => void {
  const root = document.documentElement;
  const vv = window.visualViewport;

  // The tallest this viewport has ever been, which is what "no keyboard" looks
  // like. Comparing against window.innerHeight would seem more direct and is
  // wrong in the Android app: the manifest asks for adjustResize, so the window
  // shrinks along with the viewport and the difference between them is always
  // zero. The high-water mark survives that, and survives a browser hiding its
  // address bar too.
  let tallest = 0;

  function apply() {
    const height = vv ? vv.height : window.innerHeight;
    tallest = Math.max(tallest, height);
    root.style.setProperty("--app-height", `${Math.round(height)}px`);
    // The offset matters on iOS, where the visual viewport can be scrolled up
    // inside the layout viewport instead of resized; without it a fixed shell
    // sits above the visible area rather than in it.
    root.style.setProperty("--app-offset", `${Math.round(vv?.offsetTop ?? 0)}px`);
    root.classList.toggle("keyboard-up", tallest - height > KEYBOARD_MARGIN);
  }

  function reset() {
    // Turning the phone changes what "full height" means, so the mark is retaken
    // rather than kept — otherwise portrait's height makes landscape look like a
    // permanently open keyboard.
    tallest = 0;
    apply();
  }

  apply();
  vv?.addEventListener("resize", apply);
  vv?.addEventListener("scroll", apply);
  window.addEventListener("resize", apply);
  window.addEventListener("orientationchange", reset);

  return () => {
    vv?.removeEventListener("resize", apply);
    vv?.removeEventListener("scroll", apply);
    window.removeEventListener("resize", apply);
    window.removeEventListener("orientationchange", reset);
  };
}
