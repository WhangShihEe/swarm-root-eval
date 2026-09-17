// Java-bridge smoke agent (ticket 07) — a TEMPLATE, not a RootBeer bypass.
//
// Proves the frida-17 Java bridge is usable end to end: it requires the bridge (no built-in
// `Java` global on frida 17), enters a Java VM context, reads a class, and hooks a method —
// then signals completion so `frida-run` exits cleanly. Copy this shape to build a real bypass
// (e.g. hook com.scottyab.rootbeer.RootBeer#isRooted to return false).
//
// Compile it against the baked bridge, then run it non-interactively:
//   cd /opt/frida-agent
//   frida-compile examples/java-bridge-smoke.js -o /tmp/smoke.js
//   frida-run -f <package> -l /tmp/smoke.js -t 30

const Java = require('frida-java-bridge');

Java.perform(() => {
  try {
    // A class that always exists — proof we're in a live Java VM with the bridge working.
    const System = Java.use('java.lang.System');

    // Hook a method to prove interception works. currentTimeMillis is harmless and always called.
    const original = System.currentTimeMillis;
    let hooked = false;
    original.implementation = function () {
      hooked = true;
      return original.call(this);
    };
    System.currentTimeMillis();

    send({ type: 'done', ok: hooked, note: 'java-bridge-smoke: hooked System.currentTimeMillis' });
  } catch (err) {
    send({ type: 'done', ok: false, note: `java-bridge-smoke failed: ${err}` });
  }
});
