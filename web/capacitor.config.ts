import type { CapacitorConfig } from "@capacitor/cli";

/* Wrapping the HUD as a real Android app.
 *
 * **The app loads its screens from the cloud, not from inside the APK.** That is
 * the whole point of this config. A sideloaded APK has no update channel —
 * there is no Play Store to notice a new version — so a bundled copy of the HUD
 * freezes at whatever the build was, and every change to a screen would mean
 * downloading and installing by hand. Loading from the core means `git push` is
 * the entire release process for the app as well as the server.
 *
 * What it costs, honestly:
 *   * The very first launch needs signal. After that the service worker has the
 *     shell and it opens offline — which it could not do before, because
 *     Capacitor's own origin is not one a service worker will run on.
 *   * The app's storage is keyed to the origin, so moving from https://localhost
 *     to the cloud address means signing in with the PIN once more.
 *
 * The bundled copy is still in the APK and still built by CI — it is what
 * `errorPath` shows when the cloud cannot be reached at all, instead of the
 * WebView's own "webpage not available".
 */
const CLOUD = process.env.VONDO_APP_URL || "https://vondo-core.onrender.com";

const config: CapacitorConfig = {
  appId: "dev.vondo.jarvis",
  appName: "Jarvis",
  webDir: "dist",

  android: {
    allowMixedContent: false,
  },

  server: {
    // https://localhost rather than the http default. It makes the app a secure
    // context — which the microphone needs in phase 06 — and it is one of the
    // origins the cloud core allows, so cross-origin calls actually go through.
    // Only in force for the bundled fallback now that `url` is set.
    androidScheme: "https",

    // Where the screens come from. Override with VONDO_APP_URL at build time to
    // point a debug APK at a laptop.
    url: CLOUD,
    cleartext: false,

    // Shown when the cloud is unreachable on a cold start, in place of the
    // WebView's default error page. Part of the bundled copy, so it is always
    // there.
    errorPath: "offline.html",
  },

  plugins: {
    SplashScreen: {
      // Held while the HUD is fetched, then hidden by main.tsx the moment React
      // mounts — see the note there. Auto-hide stays ON as the backstop: with it
      // off there is no ceiling at all, so a build whose JS failed to load would
      // sit on the splash screen for good rather than showing anything.
      launchAutoHide: true,
      launchShowDuration: 20000,
      backgroundColor: "#05080d",
      androidSplashResourceName: "splash",
      showSpinner: false,
    },
    StatusBar: {
      // The HUD paints its own dark ground; the bar should disappear into it
      // rather than sitting as a light strip above a black app.
      style: "DARK",
      backgroundColor: "#060d16",
      // TRUE, and this is what fullscreen actually means here: the WebView is
      // laid out behind the status bar rather than starting underneath it.
      // With this false the system kept its own strip and the app could never
      // reach the top of the screen no matter what the web manifest said —
      // the manifest governs the installed PWA and has no say over the APK.
      // The layout is already written against env(safe-area-inset-*), so
      // nothing ends up under the notch.
      overlaysWebView: true,
    },
  },
};

export default config;
