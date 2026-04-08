/**
 * sse-notifications.js
 *
 * Manages the EventSource connection to /api/sse/stream and renders
 * in-page toast notifications when a node or workflow execution completes.
 *
 * Public API exposed on ``window.__sseNotifications``:
 *   .connect()     — open the EventSource (called automatically on load)
 *   .disconnect()  — close the EventSource intentionally (no auto-reconnect)
 *   .isConnected   — boolean, read-only
 *
 * Design decisions
 * ----------------
 *  - Auto-reconnect with exponential back-off (2 s → 30 s cap).
 *  - At most MAX_TOASTS toasts visible simultaneously; oldest is removed first.
 *  - Clicking a toast (outside the × button) opens the History tab and refreshes it.
 *  - Each toast auto-dismisses after TOAST_DURATION_MS with a progress bar countdown.
 *  - All DOM mutations are wrapped in try/catch so a rendering error never
 *    breaks the connection lifecycle.
 */

(function (window) {
    'use strict';

    // ── Constants ─────────────────────────────────────────────────────────────

    /** REST endpoint that serves the SSE stream. */
    const SSE_ENDPOINT = '/api/sse/stream';

    /** Milliseconds before a toast auto-dismisses. */
    const TOAST_DURATION_MS = 7000;

    /** Maximum number of toasts visible at the same time. */
    const MAX_TOASTS = 5;

    /** Initial reconnect delay in ms (doubles on each failure, capped at MAX_RECONNECT). */
    const INITIAL_RECONNECT_DELAY_MS = 2000;

    /** Maximum reconnect delay in ms. */
    const MAX_RECONNECT_DELAY_MS = 30000;

    // ── State ─────────────────────────────────────────────────────────────────

    /** @type {EventSource|null} */
    let _eventSource = null;

    /** @type {ReturnType<typeof setTimeout>|null} */
    let _reconnectTimer = null;

    /** Current reconnect delay (ms); resets to INITIAL on successful connection. */
    let _reconnectDelay = INITIAL_RECONNECT_DELAY_MS;

    /** True while the EventSource readyState is OPEN and a "connected" event was received. */
    let _connected = false;

    /** True after disconnect() is called explicitly — prevents auto-reconnect. */
    let _intentionalClose = false;

    // ── Status metadata ───────────────────────────────────────────────────────

    /**
     * Maps a normalised status key → visual properties for the toast.
     * @type {Record<string, {icon: string, cls: string, label: string}>}
     */
    const STATUS_META = {
        success:   { icon: '✓', cls: 'sse-toast--success', label: 'Success'   },
        error:     { icon: '✕', cls: 'sse-toast--error',   label: 'Error'     },
        cancelled: { icon: '⊘', cls: 'sse-toast--warn',    label: 'Cancelled' },
        running:   { icon: '◉', cls: 'sse-toast--info',    label: 'Running'   },
    };

    /**
     * Normalise a raw status string from the server into one of the STATUS_META keys.
     *
     * @param {string|null|undefined} status
     * @returns {keyof STATUS_META}
     */
    function _normaliseStatus(status) {
        if (!status) return 'success';
        const s = status.toLowerCase();
        if (s.includes('error') || s.includes('fail')) return 'error';
        if (s.includes('cancel'))                       return 'cancelled';
        if (s.includes('run'))                          return 'running';
        return 'success';
    }

    // ── Toast DOM helpers ─────────────────────────────────────────────────────

    /**
     * Return (or lazily create) the fixed toast container element.
     *
     * @returns {HTMLElement}
     */
    function _getContainer() {
        let el = document.getElementById('sse-toast-container');
        if (!el) {
            el = document.createElement('div');
            el.id = 'sse-toast-container';
            el.setAttribute('role', 'status');
            el.setAttribute('aria-live', 'polite');
            el.setAttribute('aria-atomic', 'false');
            document.body.appendChild(el);
        }
        return el;
    }

    /**
     * Truncate *str* to *maxLen* characters, appending "…" if needed.
     *
     * @param {string} str
     * @param {number} maxLen
     * @returns {string}
     */
    function _truncate(str, maxLen) {
        if (!str) return '–';
        return str.length > maxLen ? str.slice(0, maxLen - 1) + '…' : str;
    }

    /**
     * Dismiss a toast with a slide-out animation, then remove it from the DOM.
     *
     * @param {HTMLElement} toast
     */
    function _dismissToast(toast) {
        if (!toast || !toast.parentNode) return;
        try {
            clearTimeout(toast._dismissTimer);
            toast.classList.remove('sse-toast--visible');
            toast.classList.add('sse-toast--hide');
            // Remove after CSS transition ends (350 ms matches the transition in console.css)
            setTimeout(function () {
                if (toast.parentNode) toast.remove();
            }, 350);
        } catch (err) {
            console.warn('[sse-notifications] _dismissToast error:', err);
        }
    }

    /**
     * Render a toast notification for a completed execution.
     *
     * @param {{
     *   execution_id: string,
     *   execution_type: string,
     *   plugin_id: string,
     *   status: string,
     *   elapsed_time: string|null,
     *   message: string|null,
     * }} data  Payload from the ``execution_end`` SSE event.
     */
    function _showToast(data) {
        try {
            const container = _getContainer();

            // Enforce max visible toasts — remove the oldest one
            const existing = container.querySelectorAll('.sse-toast');
            if (existing.length >= MAX_TOASTS) {
                _dismissToast(existing[0]);
            }

            const statusKey = _normaliseStatus(data.status);
            const meta      = STATUS_META[statusKey] || STATUS_META.success;
            const execType  = data.execution_type === 'workflow' ? 'Workflow' : 'Node';
            const pluginId  = _truncate(data.plugin_id || '–', 32);
            const elapsed   = data.elapsed_time || '';

            // Build toast element
            const toast = document.createElement('div');
            toast.className = 'sse-toast ' + meta.cls;
            toast.setAttribute('role', 'alert');
            toast.innerHTML =
                '<div class="sse-toast__icon" aria-hidden="true">' + meta.icon + '</div>' +
                '<div class="sse-toast__body">' +
                    '<div class="sse-toast__title">' + execType + ' completed</div>' +
                    '<div class="sse-toast__detail">' +
                        '<span class="sse-toast__plugin" title="' + (data.plugin_id || '') + '">' + pluginId + '</span>' +
                        (elapsed ? '<span class="sse-toast__time">' + elapsed + '</span>' : '') +
                    '</div>' +
                    '<div class="sse-toast__status">' + meta.label + '</div>' +
                '</div>' +
                '<button class="sse-toast__close" aria-label="Dismiss notification">\u00d7</button>' +
                '<div class="sse-toast__progress" aria-hidden="true"></div>';

            // Click on body → open History tab
            toast.addEventListener('click', function (e) {
                if (e.target.closest('.sse-toast__close')) return;
                try {
                    if (typeof window.showTab === 'function') {
                        window.showTab('history');
                    }
                    if (window.__execHistory && typeof window.__execHistory.load === 'function') {
                        window.__execHistory.load();
                    }
                } catch (navErr) {
                    console.warn('[sse-notifications] tab navigation error:', navErr);
                }
                _dismissToast(toast);
            });

            // × button → dismiss only
            toast.querySelector('.sse-toast__close').addEventListener('click', function (e) {
                e.stopPropagation();
                _dismissToast(toast);
            });

            container.appendChild(toast);

            // Trigger slide-in on next paint (CSS transition needs the element in DOM first)
            requestAnimationFrame(function () {
                toast.classList.add('sse-toast--visible');
            });

            // Animate the progress bar countdown
            const progressEl = toast.querySelector('.sse-toast__progress');
            if (progressEl) {
                progressEl.style.animationDuration = TOAST_DURATION_MS + 'ms';
                progressEl.classList.add('sse-toast__progress--run');
            }

            // Auto-dismiss
            toast._dismissTimer = setTimeout(function () {
                _dismissToast(toast);
            }, TOAST_DURATION_MS);

        } catch (err) {
            console.error('[sse-notifications] _showToast unexpected error:', err);
        }
    }

    // ── Connection lifecycle ──────────────────────────────────────────────────

    /**
     * Open the EventSource connection to SSE_ENDPOINT.
     * Safe to call multiple times — no-ops if already open.
     */
    function connect() {
        if (_eventSource) return;
        _intentionalClose = false;

        try {
            _eventSource = new EventSource(SSE_ENDPOINT);
        } catch (err) {
            console.error('[sse-notifications] EventSource construction failed:', err);
            _scheduleReconnect();
            return;
        }

        // ── "connected" — server acknowledged the subscription ──────────────
        _eventSource.addEventListener('connected', function (e) {
            try {
                _connected = true;
                _reconnectDelay = INITIAL_RECONNECT_DELAY_MS; // reset back-off
                const payload = JSON.parse(e.data);
                console.info('[sse-notifications] connected — user:', payload.user_id);
            } catch (parseErr) {
                console.warn('[sse-notifications] "connected" parse error:', parseErr);
            }
        });

        // ── "execution_end" — a node or workflow finished ───────────────────
        _eventSource.addEventListener('execution_end', function (e) {
            try {
                const data = JSON.parse(e.data);
                _showToast(data);
            } catch (parseErr) {
                console.warn('[sse-notifications] "execution_end" parse error:', parseErr);
            }
        });

        // ── "disconnected" — server sent a clean shutdown frame ─────────────
        _eventSource.addEventListener('disconnected', function () {
            _close();
            if (!_intentionalClose) {
                _scheduleReconnect();
            }
        });

        // ── onerror — network failure or server restart ──────────────────────
        _eventSource.onerror = function () {
            _connected = false;
            console.warn(
                '[sse-notifications] connection error — retrying in',
                _reconnectDelay,
                'ms'
            );
            _close();
            if (!_intentionalClose) {
                _scheduleReconnect();
            }
        };
    }

    /**
     * Intentionally close the EventSource.  Auto-reconnect will NOT fire.
     */
    function disconnect() {
        _intentionalClose = true;
        clearTimeout(_reconnectTimer);
        _reconnectTimer = null;
        _close();
    }

    /**
     * Close the EventSource (internal helper).
     * Sets _connected = false but does NOT set _intentionalClose.
     */
    function _close() {
        if (_eventSource) {
            try { _eventSource.close(); } catch (_) { /* ignore */ }
            _eventSource = null;
        }
        _connected = false;
    }

    /**
     * Schedule a reconnect attempt with exponential back-off.
     * Back-off doubles on each failure and is capped at MAX_RECONNECT_DELAY_MS.
     */
    function _scheduleReconnect() {
        clearTimeout(_reconnectTimer);
        _reconnectTimer = setTimeout(function () {
            _reconnectTimer = null;
            _eventSource = null;
            connect();
        }, _reconnectDelay);
        // Exponential back-off — cap at MAX_RECONNECT_DELAY_MS
        _reconnectDelay = Math.min(_reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
    }

    // ── Public API ────────────────────────────────────────────────────────────

    /**
     * Public interface exposed as ``window.__sseNotifications``.
     * Frozen to prevent accidental mutation from application code.
     */
    window.__sseNotifications = Object.freeze({
        connect: connect,
        disconnect: disconnect,
        /** @type {boolean} */
        get isConnected() { return _connected; },
    });

    // ── Auto-connect on page load ─────────────────────────────────────────────

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', connect);
    } else {
        connect();
    }

}(window));
