/**
 * Chat Model Tab — nOS Engine Console
 *
 * Handles the full lifecycle of the Chat tab:
 *   - Config panel toggle (model, temperature, max_tokens, system prompt)
 *   - Auto-resize textarea
 *   - Attachment chips (file, image, URL)
 *   - Message rendering (user / assistant bubbles)
 *   - Thinking indicator
 *   - Copy last response / clear history
 *
 * Real API integration: override window.__chatModel.dispatch(payload)
 * with your actual fetch/socket call and call window.__chatModel.addMessage()
 * with the assistant response.
 */
(function () {
    'use strict';

    /* ──────────────────────────────────────────────
       State
    ────────────────────────────────────────────── */
    var state = {
        messages: [],
        attachments: [],
        configOpen: false,
        lastAssistantText: ''
    };

    /* ──────────────────────────────────────────────
       DOM refs (populated in init())
    ────────────────────────────────────────────── */
    var $history, $input, $sendBtn, $configPanel, $configToggle;
    var $historyEmpty, $attachments, $modelLabel, $tempDisplay;

    /* ──────────────────────────────────────────────
       Init
    ────────────────────────────────────────────── */
    function init() {
        $history       = document.getElementById('chat-history');
        $input         = document.getElementById('chat-input');
        $sendBtn       = document.getElementById('chat-send-btn');
        $configPanel   = document.getElementById('chat-config-panel');
        $configToggle  = document.getElementById('chat-config-toggle');
        $historyEmpty  = document.getElementById('chat-history-empty');
        $attachments   = document.getElementById('chat-attachments');
        $modelLabel    = document.getElementById('chat-model-label');
        $tempDisplay   = document.getElementById('chat-temp-display');

        if (!$history) return; // tab not mounted

        bindEvents();
    }

    /* ──────────────────────────────────────────────
       Event bindings
    ────────────────────────────────────────────── */
    function bindEvents() {
        // Config toggle
        on($configToggle, 'click', toggleConfig);

        // Send
        on($sendBtn, 'click', sendMessage);

        // Textarea: Enter → send, Shift+Enter → newline, auto-resize
        on($input, 'keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        on($input, 'input', autoResize);

        // Temperature slider label sync
        var $temp = document.getElementById('chat-config-temperature');
        on($temp, 'input', function () {
            if ($tempDisplay) $tempDisplay.textContent = parseFloat($temp.value).toFixed(1);
        });

        // Model selector → update badge label
        var $modelSelect = document.getElementById('chat-config-model');
        on($modelSelect, 'change', function () {
            if ($modelLabel) $modelLabel.textContent = $modelSelect.value;
        });

        // Attachments
        var $attachFile  = document.getElementById('chat-attach-file');
        var $attachImage = document.getElementById('chat-attach-image');
        var $attachUrl   = document.getElementById('chat-attach-url');
        var $fileInput   = document.getElementById('chat-file-input');

        on($attachFile, 'click', function () { $fileInput && $fileInput.click(); });

        on($fileInput, 'change', function (e) {
            Array.from(e.target.files || []).forEach(function (f) {
                addAttachment({ type: 'file', icon: '📄', name: f.name, data: f });
            });
            e.target.value = '';
        });

        on($attachImage, 'click', function () {
            var inp = document.createElement('input');
            inp.type = 'file';
            inp.accept = 'image/*';
            inp.multiple = true;
            inp.onchange = function (e) {
                Array.from(e.target.files || []).forEach(function (f) {
                    addAttachment({ type: 'image', icon: '🖼', name: f.name, data: f });
                });
            };
            inp.click();
        });

        on($attachUrl, 'click', function () {
            var url = prompt('Incolla un URL da aggiungere al contesto:');
            if (url && url.trim()) {
                addAttachment({ type: 'url', icon: '🔗', name: url.trim() });
            }
        });

        // Toolbar actions
        on(document.getElementById('chat-clear-btn'), 'click', clearHistory);
        on(document.getElementById('chat-copy-btn'),  'click', copyLastResponse);
    }

    /* ──────────────────────────────────────────────
       Config panel
    ────────────────────────────────────────────── */
    function toggleConfig() {
        state.configOpen = !state.configOpen;
        $configPanel && $configPanel.classList.toggle('open', state.configOpen);
        $configPanel && $configPanel.setAttribute('aria-hidden', String(!state.configOpen));
        if ($configToggle) {
            $configToggle.classList.toggle('active', state.configOpen);
            $configToggle.setAttribute('aria-pressed', String(state.configOpen));
            $configToggle.title = state.configOpen ? 'Hide configuration' : 'Show configuration';
        }
    }

    /* ──────────────────────────────────────────────
       Textarea auto-resize
    ────────────────────────────────────────────── */
    function autoResize() {
        if (!$input) return;
        $input.style.height = 'auto';
        $input.style.height = Math.min($input.scrollHeight, 130) + 'px';
    }

    /* ──────────────────────────────────────────────
       Attachments
    ────────────────────────────────────────────── */
    function addAttachment(att) {
        state.attachments.push(att);
        renderAttachments();
    }

    function removeAttachment(idx) {
        state.attachments.splice(idx, 1);
        renderAttachments();
    }

    function renderAttachments() {
        if (!$attachments) return;
        $attachments.innerHTML = '';
        state.attachments.forEach(function (att, idx) {
            var chip = document.createElement('div');
            chip.className = 'chat-attachment-chip';
            chip.innerHTML =
                '<span>' + att.icon + '</span>' +
                '<span class="chat-attachment-chip-name" title="' + escHtml(att.name) + '">' + escHtml(att.name) + '</span>' +
                '<span class="chat-attachment-chip-remove" title="Remove">×</span>';
            chip.querySelector('.chat-attachment-chip-remove').addEventListener('click', function () {
                removeAttachment(idx);
            });
            $attachments.appendChild(chip);
        });
    }

    /* ──────────────────────────────────────────────
       Send message
    ────────────────────────────────────────────── */
    function sendMessage() {
        if (!$input) return;
        var text = $input.value.trim();
        if (!text) return;

        var modelEl = document.getElementById('chat-config-model');
        var tempEl  = document.getElementById('chat-config-temperature');
        var maxEl   = document.getElementById('chat-config-max-tokens');
        var sysEl   = document.getElementById('chat-config-system');

        var payload = {
            message:     text,
            model:       modelEl  ? modelEl.value              : 'gpt-4o',
            temperature: tempEl   ? parseFloat(tempEl.value)   : 0.7,
            max_tokens:  maxEl    ? parseInt(maxEl.value, 10)  : 1024,
            system:      sysEl    ? sysEl.value.trim()         : '',
            attachments: state.attachments.slice()
        };

        // Append user bubble
        appendMessage({ role: 'user', text: text, attachments: payload.attachments });

        // Reset composer
        $input.value = '';
        $input.style.height = 'auto';
        state.attachments = [];
        renderAttachments();
        scrollToBottom();

        // Show thinking indicator
        var thinkId = 'chat-thinking-' + Date.now();
        addThinking(thinkId);
        scrollToBottom();

        // Dispatch to integration layer (default: stub)
        dispatch(payload, thinkId);
    }

    /* ──────────────────────────────────────────────
       Dispatch (override for real API)
       window.__chatModel.dispatch(payload, thinkId)
    ────────────────────────────────────────────── */
    function dispatch(payload, thinkId) {
        // Stub response — replace with real socket/fetch call
        setTimeout(function () {
            removeThinking(thinkId);
            appendMessage({
                role: 'assistant',
                text: '[Stub] Chat API integration not configured yet.\n\nModel: ' + payload.model +
                      ' | Temp: ' + payload.temperature + ' | MaxTokens: ' + payload.max_tokens
            });
            scrollToBottom();
        }, 900 + Math.random() * 400);
    }

    /* ──────────────────────────────────────────────
       Message rendering
    ────────────────────────────────────────────── */
    function appendMessage(msg) {
        state.messages.push(msg);

        if ($historyEmpty) $historyEmpty.style.display = 'none';

        var el = buildMessageEl(msg);
        if ($history) $history.appendChild(el);

        if (msg.role === 'assistant') {
            state.lastAssistantText = msg.text;
        }
    }

    function buildMessageEl(msg) {
        var isUser = msg.role === 'user';
        var now    = new Date();
        var time   = pad2(now.getHours()) + ':' + pad2(now.getMinutes());
        var initials = isUser ? 'YOU' : 'AI';

        var wrap = document.createElement('div');
        wrap.className = 'chat-message chat-message--' + msg.role;

        // Avatar
        var avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = initials;

        // Content column
        var content = document.createElement('div');
        content.className = 'chat-message-content';

        // Bubble
        var bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        bubble.innerHTML = escHtml(msg.text).replace(/\n/g, '<br>');

        content.appendChild(bubble);

        // Attachment chips in message
        if (msg.attachments && msg.attachments.length) {
            var attRow = document.createElement('div');
            attRow.className = 'chat-bubble-attachments';
            msg.attachments.forEach(function (att) {
                var chip = document.createElement('span');
                chip.className = 'chat-attachment-chip';
                chip.innerHTML = '<span>' + att.icon + '</span><span class="chat-attachment-chip-name">' + escHtml(att.name) + '</span>';
                attRow.appendChild(chip);
            });
            content.appendChild(attRow);
        }

        // Timestamp
        var meta = document.createElement('div');
        meta.className = 'chat-message-meta';
        meta.textContent = time;
        content.appendChild(meta);

        wrap.appendChild(avatar);
        wrap.appendChild(content);
        return wrap;
    }

    /* ──────────────────────────────────────────────
       Thinking indicator
    ────────────────────────────────────────────── */
    function addThinking(id) {
        if (!$history) return;
        var wrap = document.createElement('div');
        wrap.id = id;
        wrap.className = 'chat-message chat-message--assistant';
        wrap.innerHTML =
            '<div class="chat-avatar">AI</div>' +
            '<div class="chat-message-content">' +
              '<div class="chat-bubble chat-thinking">' +
                '<div class="chat-thinking-dot"></div>' +
                '<div class="chat-thinking-dot"></div>' +
                '<div class="chat-thinking-dot"></div>' +
              '</div>' +
            '</div>';
        $history.appendChild(wrap);
        if ($historyEmpty) $historyEmpty.style.display = 'none';
    }

    function removeThinking(id) {
        var el = document.getElementById(id);
        if (el) el.remove();
    }

    /* ──────────────────────────────────────────────
       Clear & Copy
    ────────────────────────────────────────────── */
    function clearHistory() {
        state.messages = [];
        state.lastAssistantText = '';
        if ($history) {
            Array.from($history.querySelectorAll('.chat-message')).forEach(function (el) { el.remove(); });
        }
        if ($historyEmpty) $historyEmpty.style.display = '';
    }

    function copyLastResponse() {
        if (!state.lastAssistantText) return;
        if (navigator.clipboard) {
            navigator.clipboard.writeText(state.lastAssistantText).then(function () {
                flashToolbarBtn(document.getElementById('chat-copy-btn'), '✓');
            });
        } else {
            var ta = document.createElement('textarea');
            ta.value = state.lastAssistantText;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            flashToolbarBtn(document.getElementById('chat-copy-btn'), '✓');
        }
    }

    /* ──────────────────────────────────────────────
       Helpers
    ────────────────────────────────────────────── */
    function scrollToBottom() {
        if ($history) $history.scrollTop = $history.scrollHeight;
    }

    function escHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function pad2(n) { return n < 10 ? '0' + n : String(n); }

    function on(el, event, fn) { if (el) el.addEventListener(event, fn); }

    function flashToolbarBtn(btn, symbol) {
        if (!btn) return;
        var orig = btn.innerHTML;
        btn.innerHTML = symbol;
        btn.style.color = 'var(--log-success)';
        setTimeout(function () {
            btn.innerHTML = orig;
            btn.style.color = '';
        }, 1400);
    }

    /* ──────────────────────────────────────────────
       Bootstrap
    ────────────────────────────────────────────── */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    /* Public API */
    window.__chatModel = {
        /** Send an incoming assistant message programmatically */
        addMessage: appendMessage,
        /** Override to integrate real API */
        dispatch:   dispatch,
        /** Current messages snapshot */
        getMessages: function () { return state.messages.slice(); },
        /** Clear history */
        clear: clearHistory
    };

})();
