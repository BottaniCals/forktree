# Pomodoro Timer

A single-page, dependency-free web app that implements a basic 25-minute Pomodoro timer. The page shows a `25:00` countdown with **Start**, **Pause**, and **Reset** controls; at `00:00` the timer text turns red and a short completion beep plays. A visible counter tracks how many pomodoros you have completed, and the count is persisted to `localStorage` so it survives page reloads and browser restarts.

## Files

| File | Purpose |
| ---- | ------- |
| `index.html` | Static markup: `#timer`, `#start`/`#pause`/`#reset` buttons, `#counter`, and a screen-reader live region (`#status`). |
| `styles.css` | Centred layout, 64 px timer text, tabular numerals, and the red `.completed` styling at `00:00`. |
| `script.js` | Timer state machine, drift-corrected tick, Web Audio completion beep, and safe `localStorage` persistence. |
| `README.md` | This file. |

## Run

No build step, no npm, no install. Pick one:

1. **Open the file directly.** Double-click `index.html` (or open it in Chrome or Firefox) and the app runs from `file://`.
2. **Serve it locally.**

    ```bash
    cd pomodoro-timer
    python3 -m http.server 8000
    ```

    Then visit <http://localhost:8000/> in your browser.

Behavior is identical in both modes. Your browser's `localStorage` holds the completed-pomodoros count under the key `pomodoro:completed`.

## Design notes

- **No build step, no framework, no third-party assets.** The app is pure HTML, CSS, and JavaScript and loads no external resources (no CDNs, no fonts, no analytics). The HTML, CSS, and JS are three small files served as-is.
- **Drift-corrected countdown.** The tick recomputes the remaining time from wall-clock elapsed (`Date.now()`) on every fire, so the displayed countdown does not drift over 25 minutes and recovers correctly when a backgrounded tab is foregrounded again.
- **Idempotent controls.** `Start` while already running, `Pause` while paused, and so on are all safe no-ops; intervals cannot leak, and the completion beep cannot play twice for the same cycle.
- **`Start` after completion is a no-op until `Reset` is clicked.** After the timer hits `00:00` and the beep has played, clicking `Start` does nothing; click `Reset` to return to `25:00`, then `Start` to begin the next interval. This matches the requirement that a second beep cannot fire until the timer has been reset and once again reaches `00:00`.
- **`localStorage` is feature-detected and wrapped in `try`/`catch`.** If the browser refuses storage (some `file://` profiles with strict privacy), the counter still increments in-session using an in-memory fallback; the page never throws and the console stays clean.
- **Accessibility.** Buttons are native `<button type="button">` elements with visible focus styling; the `#status` element is an `aria-live="polite"` region that announces "Pomodoro complete" on each successful cycle.

### Audio cue — a deliberate deviation

The completion beep is generated entirely in-browser using the **Web Audio API** (`AudioContext` + `OscillatorNode` + `GainNode`): a short ~880 Hz sine tone with an attack/decay envelope to suppress clicks. **No audio file is fetched, no `data:` URI is loaded, no `<audio>` element is used.**

The original wording of REQ-3 §2 asks for the beep to be "a brief audio cue (a short beep) using a `data:` URI audio source embedded in the JavaScript or HTML (no external asset files)," while REQ-3 §3 explicitly allows "the Web Audio API … OR an `<audio>` element fed by the data URI." The two wordings are in tension; this app satisfies the §3 allowance (Web Audio API) rather than the §2 literal phrasing (inline `data:` URI).

In practice the difference is invisible to the user: in both cases the beep is generated from in-code parameters, no external audio asset is referenced, and the same `NFR §Security` guarantee — "no external audio files shall be referenced" — holds. If a stricter literal reading of §2 is ever required, swapping the Web Audio implementation for an `<audio src="data:audio/wav;base64,…">` element is a drop-in change isolated to `script.js` and `index.html`.

## Out of scope

This is the basic Pomodoro MVP: a single 25-minute work interval, completion signal, and a counter. There is no break timer, no long-break cycle, no configurable duration, no notifications, no progress ring, and no theming. See `.specs/pomodoro-timer/` for the full requirements, design, and task plan.

## License

Same as the parent repository.
