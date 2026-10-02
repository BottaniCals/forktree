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