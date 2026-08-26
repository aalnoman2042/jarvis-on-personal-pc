import type { CapacitorConfig } from "@capacitor/cli";

/* Wrapping the HUD as a real Android app.
 *
 * The app ships the built HUD inside the APK and talks to the cloud core over
 * HTTPS — so it opens instantly with no network round-trip for the UI, and the
 * conversation, memory and PC control all still come from the one cloud brain.
 * Same account, same memory, whichever way Rohan opens Jarvis.
 */
const config: CapacitorConfig = {
  appId: "dev.vondo.jarvis",
  appName: "Jarvis",
  webDir: "dist",

  android: {
    // Debug builds are what gets sideloaded; without this Android 9+ blocks the
    // dev server over plain http and the whole screen is blank with no clue why.
    allowMixedContent: false,
  },

  plugins: {
    SplashScreen: {
      launchShowDuration: 900,
      backgroundColor: "#05080d",
      androidSplashResourceName: "splash",
      showSpinner: false,
    },
    StatusBar: {
      // The HUD paints its own dark ground; the bar should disappear into it
      // rather than sitting as a light strip above a black app.
      style: "DARK",
      backgroundColor: "#05080d",
      overlaysWebView: false,
    },
  },
};

export default config;
