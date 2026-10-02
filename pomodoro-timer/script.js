/* pomodoro-timer/script.js
 * Static, dependency-free Pomodoro timer state machine.
 * Wrapped in an IIFE so nothing leaks onto `window`.
 * Pure browser APIs only: no third-party libraries, no build step.
 */
(function () {
    "use strict";

    // ---------- Constants ----------

    const TOTAL_SECONDS = 25 * 60;
    const STORAGE_KEY = "pomodoro:completed";

    // ---------- Module-scoped state ----------

    // In-memory counter fallback. Always reflects the canonical count for the
    // current session; on a fresh page (no prior call to readCounter), it
    // defaults to 0. Survives reloads only when persistence is supported.
    let completedCount = 0;

    // ---------- Pure helpers ----------

    /**
     * Format an integer number of seconds as a zero-padded `mm:ss` string.
     * Negative inputs clamp to zero so the display cannot go below 00:00.
     *
     * @param {number} s - integer seconds (may be negative)
     * @returns {string} zero-padded "mm:ss" representation
     */
    function formatMmSs(s) {
        const total = s > 0 ? Math.floor(s) : 0;
        const minutes = Math.floor(total / 60);
        const seconds = total % 60;
        const mm = minutes < 10 ? "0" + minutes : String(minutes);
        const ss = seconds < 10 ? "0" + seconds : String(seconds);
        return mm + ":" + ss;
    }

    // ---------- Persistence (safe localStorage access) ----------

    /**
     * Returns true when localStorage is reachable. Feature-detects the
     * global and wraps a probe access in try/catch so restricted browsing
     * contexts (some file:// profiles) fall back silently to the in-memory
     * counter instead of throwing.
     */
    function storageAvailable() {
        try {
            return typeof window !== "undefined"
                && typeof window.localStorage !== "undefined"
                && window.localStorage !== null;
        } catch (_err) {
            return false;
        }
    }

    /**
     * Read the completed-pomodoros count from localStorage. Validates that
     * the stored value is a non-negative integer (JSON-encoded); on any
     * missing, corrupt, or invalid value, returns 0 and leaves the in-memory
     * counter at 0. Never throws.
     *
     * @returns {number} validated non-negative integer count
     */
    function readCounter() {
        let parsed = 0;
        if (!storageAvailable()) {
            completedCount = 0;
            return completedCount;
        }
        try {
            const raw = window.localStorage.getItem(STORAGE_KEY);
            if (raw === null || raw === undefined || raw === "") {
                parsed = 0;
            } else {
                const value = JSON.parse(raw);
                if (Number.isInteger(value) && value >= 0) {
                    parsed = value;
                } else {
                    parsed = 0;
                }
            }
        } catch (_err) {
            parsed = 0;
        }
        completedCount = parsed;
        return completedCount;
    }

    /**
     * Increment the completed-pomodoros counter by one and persist the new
     * value to localStorage when available. Storage failures are swallowed
     * silently so the in-memory count is still authoritative for the
     * current session (per REQ-5 §4 and NFR §Usability: no console errors).
     */
    function bumpCounter() {
        completedCount = completedCount + 1;
        if (!storageAvailable()) {
            return;
        }
        try {
            window.localStorage.setItem(
                STORAGE_KEY,
                JSON.stringify(completedCount)
            );
        } catch (_err) {
            // Silent: in-memory count is still updated above.
        }
    }

    // ---------- Audio cue (Web Audio API) ----------

    // Lazily-created AudioContext. Stored at module scope so we construct at
    // most one per page load. Construction is deferred until the first call
    // to playBeep(), which is in turn called from a user-gesture handler
    // (Start/Pause/Reset). This satisfies browser autoplay policies that
    // require user activation before audio playback.
    let audioCtx = null;

    /**
     * Returns true if the Web Audio API appears to be available on this
     * platform. Feature-detects both `window.AudioContext` and the
     * standardized `window.webkitAudioContext` fallback used by older
     * WebKit-derived browsers.
     */
    function audioAvailable() {
        try {
            return typeof window !== "undefined"
                && (typeof window.AudioContext !== "undefined"
                    || typeof window.webkitAudioContext !== "undefined");
        } catch (_err) {
            return false;
        }
    }

    /**
     * Lazily construct and return a single AudioContext for the page. Returns
     * null when the API is unavailable or construction throws. Wrapped in
     * try/catch so restricted browsing contexts never produce a console
     * error (per NFR §Usability: no console errors during normal operation).
     *
     * @returns {AudioContext|null}
     */
    function getAudioContext() {
        if (audioCtx !== null) {
            return audioCtx;
        }
        if (!audioAvailable()) {
            return null;
        }
        try {
            const Ctor = window.AudioContext || window.webkitAudioContext;
            audioCtx = new Ctor();
            return audioCtx;
        } catch (_err) {
            audioCtx = null;
            return null;
        }
    }

    /**
     * Play a brief completion beep using the Web Audio API. Generates a
     * short sine tone (~880 Hz) routed through a gain envelope so the
     * oscillator's abrupt on/off does not produce an audible click.
     *
     * The cue is ~200 ms total with a quick attack (~10 ms) and a longer
     * exponential decay (~190 ms) so the tone fades out smoothly.
     *
     * Safe by design: any failure in construction or scheduling is swallowed
     * silently so the visual `.completed` CSS hook still fires (REQ-3 §1)
     * and no uncaught exception or console error is produced
     * (NFR §Usability + NFR §Reliability).
     *
     * Called from a user-gesture stack (Start/Pause/Reset click handler);
     * satisfies browser autoplay policies on the first invocation.
     */
    function playBeep() {
        try {
            const ctx = getAudioContext();
            if (ctx === null) {
                return;
            }

            const now = ctx.currentTime;
            const duration = 0.2; // seconds, total audible length
            const attack = 0.01; // 10 ms linear ramp-up to suppress click
            const release = duration - attack; // ~190 ms exponential decay

            const osc = ctx.createOscillator();
            osc.type = "sine";
            osc.frequency.setValueAtTime(880, now); // ~A5

            const gain = ctx.createGain();
            // Start at ~0, ramp to peak at the end of the attack window,
            // then exponential decay to a near-silent value at `now + duration`.
            gain.gain.setValueAtTime(0.0001, now);
            gain.gain.exponentialRampToValueAtTime(0.3, now + attack);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

            osc.connect(gain);
            gain.connect(ctx.destination);

            osc.start(now);
            osc.stop(now + release);

            // Disconnect nodes once they have finished so the AudioContext
            // graph does not accumulate idle oscillators across cycles.
            osc.onended = function () {
                try {
                    osc.disconnect();
                    gain.disconnect();
                } catch (_err) {
                    // Already disconnected or context closed; ignore.
                }
            };
        } catch (_err) {
            // Silent: visual .completed signal still fires from the caller.
        }
    }

    // Expose a minimal testing surface so future Node-based harnesses can
    // exercise the pure helpers without a DOM. The IIFE prevents any leak
    // onto `window` in production (browsers ignore this assignment).
    if (typeof module !== "undefined" && module.exports) {
        module.exports = {
            TOTAL_SECONDS: TOTAL_SECONDS,
            STORAGE_KEY: STORAGE_KEY,
            formatMmSs: formatMmSs,
            readCounter: readCounter,
            bumpCounter: bumpCounter,
            storageAvailable: storageAvailable,
            audioAvailable: audioAvailable,
            playBeep: playBeep,
            // Test-only hook to reset the lazily-created AudioContext.
            _resetAudioContext: function () { audioCtx = null; },
            // Internal counter accessor for tests only.
            _getCompletedCount: function () { return completedCount; },
            _setCompletedCount: function (n) {
                if (Number.isInteger(n) && n >= 0) {
                    completedCount = n;
                }
            },
        };
    }
})();