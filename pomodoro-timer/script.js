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

    // ---------- Timer state machine ----------

    // Module-scoped timer state. Invariants:
    //   - running === false  =>  intervalId === null
    //   - startedAt !== null =>  running === true
    //   - 0 <= remaining <= TOTAL_SECONDS
    let remaining = TOTAL_SECONDS;
    let running = false;
    let intervalId = null;
    let startedAt = null;

    // DOM element references. Populated during DOMContentLoaded init
    // (Task 6). Held at module scope so render() / reset() can update the
    // DOM without re-querying on every tick. Safe to leave as null
    // before init: all DOM writes are guarded by null checks.
    let timerEl = null;
    let counterEl = null;
    let statusEl = null;

    // Tracks whether we have already announced "Pomodoro complete" for the
    // current cycle. Set true exactly once when the timer transitions
    // into the Completed state; reset to false on reset() and on a fresh
    // start() so the live-region announcement only fires once per cycle.
    let completedAnnounced = false;

    /**
     * Render the current timer state into the DOM.
     *
     *   - #timer text: "mm:ss" derived from `remaining`.
     *   - #timer.completed class: present iff `remaining <= 0`.
     *   - #count text: the in-memory completedCount value.
     *   - #status text: "Pomodoro complete" iff `completedAnnounced`; empty
     *     otherwise. The flag is the only thing that determines whether
     *     the live region fires for the current cycle, ensuring the
     *     announcement happens once (on the transition) and not on every
     *     tick afterwards.
     *
     * Safe to call before init (all DOM writes are null-guarded); in that
     * case this becomes a no-op and the caller still drives state forward.
     */
    function render() {
        if (timerEl !== null) {
            timerEl.textContent = formatMmSs(remaining);
            if (remaining <= 0) {
                timerEl.classList.add("completed");
            } else {
                timerEl.classList.remove("completed");
            }
        }
        if (counterEl !== null) {
            counterEl.textContent = String(completedCount);
        }
        if (statusEl !== null) {
            statusEl.textContent = completedAnnounced ? "Pomodoro complete" : "";
        }
    }

    /**
     * Begin (or resume) the countdown. Idempotent: a second Start while
     * already running is a no-op so we cannot leak duplicate intervals.
     *
     * When resuming, the drift-corrected tick must pick up from the exact
     * retained `remaining` value (REQ-2 §4). We achieve this by setting
     * `startedAt` to a synthetic past time so that
     * `TOTAL_SECONDS - Math.floor((Date.now() - startedAt) / 1000)`
     * equals the retained `remaining` on the very first tick.
     *
     * Start from the Completed state is a deliberate no-op until Reset
     * has been clicked (design §Error Handling §6): this prevents an
     * unexpected auto-restart and matches REQ-3 §3's "until the timer
     * has been reset and once again reaches 00:00" spirit.
     */
    function start() {
        if (running) {
            return;
        }
        if (remaining <= 0) {
            // Completed (or never-started) state; require Reset first.
            return;
        }
        startedAt = Date.now() - (TOTAL_SECONDS - remaining) * 1000;
        running = true;
        completedAnnounced = false;
        intervalId = setInterval(tick, 250);
    }

    /**
     * Halt the countdown at its current value. Idempotent: pausing while
     * already paused is a no-op.
     *
     * Captures the wall-clock-derived remaining time BEFORE clearing the
     * interval, so resume continues from the exact same value the user
     * last saw (REQ-2 §3). Clamps to the [0, TOTAL_SECONDS] invariant.
     */
    function pause() {
        if (!running) {
            return;
        }
        const captured = TOTAL_SECONDS
            - Math.floor((Date.now() - startedAt) / 1000);
        let next = captured;
        if (next < 0) {
            next = 0;
        } else if (next > TOTAL_SECONDS) {
            next = TOTAL_SECONDS;
        }
        remaining = next;
        clearInterval(intervalId);
        intervalId = null;
        running = false;
        startedAt = null;
    }

    /**
     * Stop the timer (if running), restore the display to 25:00, and
     * clear the completion signal. Does NOT touch completedCount or
     * localStorage — resetting an in-progress or completed pomodoro
     * never alters the persisted count (REQ-2 §5/§6, REQ-3 §4, REQ-5 §3).
     */
    function reset() {
        if (intervalId !== null) {
            clearInterval(intervalId);
            intervalId = null;
        }
        running = false;
        startedAt = null;
        remaining = TOTAL_SECONDS;
        completedAnnounced = false;
        // Clear the completion signal directly so it disappears even
        // before render() runs.
        if (timerEl !== null) {
            timerEl.classList.remove("completed");
        }
        if (statusEl !== null) {
            statusEl.textContent = "";
        }
        render();
    }

    /**
     * Drift-corrected tick handler. Scheduled at 250 ms for fine-grained
     * UI freshness, but never accumulates tick counts: remaining is
     * recomputed from wall-clock elapsed on every fire. This keeps
     * drift to <=1 second over a full 25-minute interval (NFR
     * §Performance) and means backgrounded/throttled tabs jump to the
     * correct value on resume (NFR §Reliability).
     *
     * When remaining reaches 0 we clamp, stop the interval, mark the
     * completion (visual + live-region + beep + counter bump), and
     * render — exactly once per cycle. Subsequent ticks cannot re-enter
     * the completion branch because `running` is cleared above.
     */
    function tick() {
        if (!running || startedAt === null) {
            return;
        }
        let next = TOTAL_SECONDS
            - Math.floor((Date.now() - startedAt) / 1000);
        if (next < 0) {
            next = 0;
        } else if (next > TOTAL_SECONDS) {
            next = TOTAL_SECONDS;
        }
        remaining = next;

        if (remaining <= 0) {
            clearInterval(intervalId);
            intervalId = null;
            running = false;
            startedAt = null;
            completedAnnounced = true;
            playBeep();
            bumpCounter();
        }
        render();
    }

    // ---------- DOMContentLoaded init & event wiring ----------

    /**
     * One-shot bootstrap invoked when the DOM is ready.
     *
     *   - Caches references to #timer, #count, and #status into the
     *     module-scoped element slots so render() / reset() / start() /
     *     pause() / tick() can update the DOM without re-querying.
     *   - Caches references to the Start / Pause / Reset buttons.
     *   - Synchronously reads the persisted counter from localStorage
     *     (NFR §Performance: must complete in <=50 ms) and renders the
     *     initial 25:00 + counter so the first paint is correct without
     *     a layout shift.
     *   - Attaches click listeners wiring each button to its handler.
     *     Listeners are registered on the cached button nodes (not
     *     re-queried inside the handlers) so a missing button simply
     *     results in no listener being attached rather than a throw.
     *
     * Safe against a missing #status: the live region is only used for
     * the completion announcement and the rest of the app continues to
     * function without it.
     */
    function init() {
        timerEl = document.getElementById("timer");
        counterEl = document.getElementById("count");
        statusEl = document.getElementById("status");

        const startBtn = document.getElementById("start");
        const pauseBtn = document.getElementById("pause");
        const resetBtn = document.getElementById("reset");

        // Synchronous persistence read + initial render. This must run
        // before any user gesture so the counter reflects the persisted
        // value on the very first paint (REQ-5 §2).
        readCounter();
        render();

        if (startBtn !== null) {
            startBtn.addEventListener("click", start);
        }
        if (pauseBtn !== null) {
            pauseBtn.addEventListener("click", pause);
        }
        if (resetBtn !== null) {
            resetBtn.addEventListener("click", reset);
        }
    }

    // Single DOMContentLoaded listener (Task 6). The script is loaded with
    // `defer`, so when this IIFE runs the DOM has been parsed but
    // DOMContentLoaded has not yet fired; registering here is safe and
    // guarantees init runs after the parser has produced the elements we
    // query. We also short-circuit when the document is already past the
    // "loading" state so a Node-based test harness that loads script.js
    // after the DOM exists can call init() without waiting on an event
    // that will never fire.
    if (typeof document !== "undefined"
        && typeof document.addEventListener === "function"
        && document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
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
            render: render,
            start: start,
            pause: pause,
            reset: reset,
            tick: tick,
            // Test-only hook to reset the lazily-created AudioContext.
            _resetAudioContext: function () { audioCtx = null; },
            // Test-only hook to inject DOM element refs without a real DOM.
            _setElements: function (refs) {
                if (refs && typeof refs === "object") {
                    timerEl = refs.timerEl !== undefined ? refs.timerEl : timerEl;
                    counterEl = refs.counterEl !== undefined ? refs.counterEl : counterEl;
                    statusEl = refs.statusEl !== undefined ? refs.statusEl : statusEl;
                }
            },
            // Internal counter accessor for tests only.
            _getCompletedCount: function () { return completedCount; },
            _setCompletedCount: function (n) {
                if (Number.isInteger(n) && n >= 0) {
                    completedCount = n;
                }
            },
            // Internal timer-state accessors for tests only.
            _getRemaining: function () { return remaining; },
            _setRemaining: function (n) {
                if (Number.isInteger(n) && n >= 0 && n <= TOTAL_SECONDS) {
                    remaining = n;
                }
            },
            _getRunning: function () { return running; },
            _setStartedAt: function (ms) { startedAt = ms; },
            _getIntervalId: function () { return intervalId; },
            _isCompletedAnnounced: function () { return completedAnnounced; },
        };
    }
})();