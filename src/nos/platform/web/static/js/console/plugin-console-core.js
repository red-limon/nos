/**
 * Hythera Plugin Console Core - Injectable command-line component
 *
 * Single source of truth for command line UI.
 * Requires: Socket.IO, upload_progress.js, (optional) Prism.js
 */
'use strict';
/* ==========================================================================
   Console Application - Core (UI and Rendering)
   ========================================================================== */
(function() {
    'use strict';

    const CONFIG = {
        maxEntries: 1000,
        autoScrollThreshold: 50
    };

    const state = {
        socket: null,
        autoScroll: true,
        eventCount: 0,
        connected: false,
        cmdHistory: [],
        cmdHistoryIndex: -1,
        currentPrompt: null,
        splitPrompt: null,
        progressElements: [],
        filterLevels: {
            debug: true,
            info: true,
            success: true,
            warning: true,
            error: true
        },
        currentExecutionId: null,
        _renderTarget: null,  // 'output' when rendering final result to Output panel
        currentOutputContainer: null,   // expandable container for current command output
        currentOutputContainerSplit: null
    };

    const dom = {
        output: document.getElementById('console-output'),
        splitOutput: document.getElementById('split-console-output'),
        empty: document.getElementById('console-empty'),
        outputPanel: document.getElementById('output-panel'),
        outputEmpty: document.getElementById('output-empty'),
        statusDot: document.getElementById('status-dot'),
        statusText: document.getElementById('status-text'),
        statusSessionId: document.getElementById('status-session-id'),
        btnClear: document.getElementById('btn-clear'),
        btnScroll: document.getElementById('btn-scroll'),
        btnFilter: document.getElementById('btn-filter'),
        filterDropdown: document.getElementById('filter-dropdown'),
        splitBtnClear: document.getElementById('split-btn-clear'),
        splitBtnScroll: document.getElementById('split-btn-scroll'),
        splitBtnFilter: document.getElementById('split-btn-filter'),
        splitFilterDropdown: document.getElementById('split-filter-dropdown')
    };

    // Utility Functions
    function formatTime(ts) {
        const date = typeof ts === 'number' 
            ? new Date(ts * 1000) 
            : new Date(ts);
        return date.toLocaleTimeString('en-US', { 
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        }) + '.' + String(date.getMilliseconds()).padStart(3, '0');
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    /**
     * Copy text to clipboard with visual feedback
     */
    function copyToClipboard(text, button) {
        navigator.clipboard.writeText(text).then(() => {
            // Success feedback
            const originalText = button.innerHTML;
            button.innerHTML = '<span class="copy-icon">✓</span><span class="copy-label">Copied!</span>';
            button.classList.add('copy-success');
            setTimeout(() => {
                button.innerHTML = originalText;
                button.classList.remove('copy-success');
            }, 1500);
        }).catch(err => {
            // Fallback for older browsers
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
                button.innerHTML = '<span class="copy-icon">✓</span><span class="copy-label">Copied!</span>';
                button.classList.add('copy-success');
                setTimeout(() => {
                    button.innerHTML = '<span class="copy-icon">⧉</span><span class="copy-label">Copy</span>';
                    button.classList.remove('copy-success');
                }, 1500);
            } catch (e) {
                console.error('Copy failed:', e);
            }
            document.body.removeChild(textarea);
        });
    }

    /**
     * Create a copy button element
     */
    function createCopyButton(textToCopy) {
        const btn = document.createElement('button');
        btn.className = 'output-copy-btn';
        btn.title = 'Copy to clipboard';
        btn.innerHTML = '<span class="copy-icon">⧉</span><span class="copy-label">Copy</span>';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            copyToClipboard(textToCopy, btn);
        });
        return btn;
    }

    function formatJson(obj) {
        try {
            return JSON.stringify(obj, null, 2);
        } catch (e) {
            return String(obj);
        }
    }

    function isScrolledToBottom() {
        const { scrollTop, scrollHeight, clientHeight } = dom.output;
        return scrollHeight - scrollTop - clientHeight < CONFIG.autoScrollThreshold;
    }

    function scrollToBottom() {
        dom.output.scrollTop = dom.output.scrollHeight;
    }

    // Humanize event name for display (e.g. node_start -> Node start, node_execute -> Node execute)

    // Log Entry Rendering
    function createLogEntry(data) {
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        
        const level = (data.level || 'info').toLowerCase();
        entry.setAttribute('data-level', level);
        const eventKey = data.event || 'custom';
        const timestamp = data.timestamp || data.datetime || Date.now() / 1000;
        const message = data.message || '';
        const showEvent = eventKey && eventKey !== 'system' && eventKey !== 'custom';

        const hasData = data && Object.keys(data).length > 0;

        // Toggle first (before timestamp) when row has expandable JSON details
        if (hasData) {
            const toggleSpan = document.createElement('span');
            toggleSpan.className = 'log-toggle';
            toggleSpan.setAttribute('data-action', 'toggle');
            toggleSpan.setAttribute('title', 'Show details');
            toggleSpan.textContent = '▶';
            entry.appendChild(toggleSpan);
        }

        // Header: timestamp | level | [event] | message
        const timestampSpan = document.createElement('span');
        timestampSpan.className = 'log-timestamp';
        timestampSpan.textContent = formatTime(timestamp);
        
        const levelSpan = document.createElement('span');
        levelSpan.className = `log-level log-level--${level}`;
        levelSpan.textContent = level;
        
        entry.appendChild(timestampSpan);
        entry.appendChild(levelSpan);

        if (showEvent) {
            const eventSpan = document.createElement('span');
            eventSpan.className = 'log-event';
            eventSpan.textContent = eventKey;
            entry.appendChild(eventSpan);
        }

        const messageSpan = document.createElement('span');
        messageSpan.className = 'log-message';
        messageSpan.textContent = message;
        entry.appendChild(messageSpan);
        
        if (data.request_id) {
            entry.setAttribute('data-request-id', data.request_id);
        }

        if (hasData) {
            // Section 1: JSON payload
            const details = document.createElement('div');
            details.className = 'log-details';
            
            const treeContainer = document.createElement('div');
            treeContainer.className = 'log-data cmd-output--json-tree';
            const tree = createJsonTreeNode(data, '', 0, false);
            treeContainer.appendChild(tree);
            details.appendChild(treeContainer);
            
            entry.appendChild(details);
        }

        return entry;
    }

    function applyLogFilters() {
        const allEntries = document.querySelectorAll('.log-entry[data-level]');
        allEntries.forEach(function(entry) {
            const level = entry.getAttribute('data-level');
            if (level && state.filterLevels[level] === false) {
                entry.classList.add('filtered');
            } else {
                entry.classList.remove('filtered');
            }
        });
    }

    function addLogEntry(data) {
        if (dom.empty) {
            dom.empty.style.display = 'none';
        }

        const shouldScroll = state.autoScroll && isScrolledToBottom();
        const entry = createLogEntry(data);
        
        const level = data.level || 'info';
        if (state.filterLevels[level] === false) {
            entry.classList.add('filtered');
        }
        
        if (state.currentOutputContainer) {
            state.currentOutputContainer.appendChild(entry);
            if (state.currentOutputContainerSplit) {
                const splitEntry = entry.cloneNode(true);
                reattachEventListeners(splitEntry);
                state.currentOutputContainerSplit.appendChild(splitEntry);
            }
        } else if (state.currentPrompt) {
            dom.output.insertBefore(entry, state.currentPrompt);
        } else {
            dom.output.appendChild(entry);
        }

        // Copy to split when not using command block
        if (dom.splitOutput && !state.currentOutputContainerSplit) {
            const splitEntry = entry.cloneNode(true);
            reattachEventListeners(splitEntry);
            if (state.splitPrompt) {
                dom.splitOutput.insertBefore(splitEntry, state.splitPrompt);
            } else {
                dom.splitOutput.appendChild(splitEntry);
            }
            if (state.autoScroll) {
                dom.splitOutput.scrollTop = dom.splitOutput.scrollHeight;
            }
        }

        state.eventCount++;

        while (dom.output.children.length > CONFIG.maxEntries + 1) {
            const first = dom.output.querySelector('.log-entry');
            if (first) first.remove();
        }
        
        if (dom.splitOutput) {
            while (dom.splitOutput.children.length > CONFIG.maxEntries) {
                const first = dom.splitOutput.querySelector('.log-entry');
                if (first) first.remove();
            }
        }

        if (shouldScroll) {
            scrollToBottom();
        }
    }

    function addSystemMessage(message, level = 'info') {
        addLogEntry({
            event: 'system',
            level: level,
            message: message,
            timestamp: Date.now() / 1000
        });
    }

    /** Simple "ready" welcome message (not a log entry). */
    function addReadyMessage(message) {
        if (!dom.output) return;
        if (dom.empty) dom.empty.style.display = 'none';
        const el = document.createElement('div');
        el.className = 'console-ready-message';
        el.textContent = message;
        if (state.currentPrompt) {
            dom.output.insertBefore(el, state.currentPrompt);
        } else {
            dom.output.appendChild(el);
        }
        if (dom.splitOutput) {
            const splitEl = el.cloneNode(true);
            if (state.splitPrompt) {
                dom.splitOutput.insertBefore(splitEl, state.splitPrompt);
            } else {
                dom.splitOutput.appendChild(splitEl);
            }
        }
    }

    // Command Prompt
    function createPrompt() {
        if (state.currentPrompt) {
            state.currentPrompt.remove();
        }
        if (state.splitPrompt) {
            state.splitPrompt.remove();
        }

        if (dom.empty) {
            dom.empty.style.display = 'none';
        }

        const line = document.createElement('div');
        line.className = 'cmd-line';
        line.innerHTML = `
            <span class="cmd-toggle cmd-toggle--prompt" title="Command output will appear below">\u25B6</span>
            <span class="cmd-prompt">$</span>
            <input type="text" class="cmd-input" placeholder="Type 'help' + Enter for available commands" autofocus>
        `;

        const input = line.querySelector('.cmd-input');

        function handleKeydown(e, inputEl) {
            if (e.ctrlKey && e.key === 'c') {
                e.preventDefault();
                if (!state.connected) {
                    window.dispatchEvent(new CustomEvent('console-cancel-reconnect'));
                    return;
                }
                if (state.currentExecutionId) {
                    executeCommand('stop ' + state.currentExecutionId);
                    appendOutput('info', '^C (sending stop for: ' + state.currentExecutionId + ')');
                } else {
                    appendOutput('warning', '^C (no active execution to stop)');
                }
                return;
            }
            
            if (e.key === 'Enter') {
                e.preventDefault();
                const cmd = inputEl.value.trim();
                if (cmd) {
                    executeCommand(cmd);
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (state.cmdHistory.length > 0) {
                    if (state.cmdHistoryIndex < state.cmdHistory.length - 1) {
                        state.cmdHistoryIndex++;
                    }
                    const histCmd = state.cmdHistory[state.cmdHistory.length - 1 - state.cmdHistoryIndex];
                    inputEl.value = histCmd;
                    syncPromptInputs(histCmd);
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (state.cmdHistoryIndex > 0) {
                    state.cmdHistoryIndex--;
                    const histCmd = state.cmdHistory[state.cmdHistory.length - 1 - state.cmdHistoryIndex];
                    inputEl.value = histCmd;
                    syncPromptInputs(histCmd);
                } else {
                    state.cmdHistoryIndex = -1;
                    inputEl.value = '';
                    syncPromptInputs('');
                }
            }
        }

        input.addEventListener('keydown', (e) => handleKeydown(e, input));
        
        input.addEventListener('input', () => {
            if (state.splitPrompt) {
                const splitInput = state.splitPrompt.querySelector('.cmd-input');
                if (splitInput && splitInput !== document.activeElement) {
                    splitInput.value = input.value;
                }
            }
        });

        dom.output.appendChild(line);
        state.currentPrompt = line;
        state.cmdHistoryIndex = -1;

        // Create split prompt if split output exists
        if (dom.splitOutput) {
            createSplitPrompt();
        }

        input.focus();
        if (state.autoScroll) {
            scrollToBottom();
            if (dom.splitOutput) {
                dom.splitOutput.scrollTop = dom.splitOutput.scrollHeight;
            }
        }
    }
    
    function syncPromptInputs(value) {
        if (state.currentPrompt) {
            const mainInput = state.currentPrompt.querySelector('.cmd-input');
            if (mainInput) mainInput.value = value;
        }
        if (state.splitPrompt) {
            const splitInput = state.splitPrompt.querySelector('.cmd-input');
            if (splitInput) splitInput.value = value;
        }
    }
    
    function createSplitPrompt() {
        if (!dom.splitOutput) return;
        
        if (state.splitPrompt) {
            state.splitPrompt.remove();
        }
        
        const splitLine = document.createElement('div');
        splitLine.className = 'cmd-line';
        splitLine.innerHTML = `
            <span class="cmd-toggle cmd-toggle--prompt" title="Command output will appear below">\u25B6</span>
            <span class="cmd-prompt">$</span>
            <input type="text" class="cmd-input" placeholder="Type 'help' + Enter for available commands">
        `;
        
        const splitInput = splitLine.querySelector('.cmd-input');
        
        function handleKeydown(e, inputEl) {
            if (e.ctrlKey && e.key === 'c') {
                e.preventDefault();
                if (!state.connected) {
                    window.dispatchEvent(new CustomEvent('console-cancel-reconnect'));
                    return;
                }
                if (state.currentExecutionId) {
                    executeCommand('stop ' + state.currentExecutionId);
                    appendOutput('info', '^C (sending stop for: ' + state.currentExecutionId + ')');
                } else {
                    appendOutput('warning', '^C (no active execution to stop)');
                }
                return;
            }
            
            if (e.key === 'Enter') {
                e.preventDefault();
                const cmd = inputEl.value.trim();
                if (cmd) {
                    executeCommand(cmd);
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (state.cmdHistory.length > 0) {
                    if (state.cmdHistoryIndex < state.cmdHistory.length - 1) {
                        state.cmdHistoryIndex++;
                    }
                    const histCmd = state.cmdHistory[state.cmdHistory.length - 1 - state.cmdHistoryIndex];
                    inputEl.value = histCmd;
                    syncPromptInputs(histCmd);
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (state.cmdHistoryIndex > 0) {
                    state.cmdHistoryIndex--;
                    const histCmd = state.cmdHistory[state.cmdHistory.length - 1 - state.cmdHistoryIndex];
                    inputEl.value = histCmd;
                    syncPromptInputs(histCmd);
                } else {
                    state.cmdHistoryIndex = -1;
                    inputEl.value = '';
                    syncPromptInputs('');
                }
            }
        }
        
        splitInput.addEventListener('keydown', (e) => handleKeydown(e, splitInput));
        
        splitInput.addEventListener('input', () => {
            if (state.currentPrompt) {
                const mainInput = state.currentPrompt.querySelector('.cmd-input');
                if (mainInput && mainInput !== document.activeElement) {
                    mainInput.value = splitInput.value;
                }
            }
        });
        
        if (state.currentPrompt) {
            const mainInput = state.currentPrompt.querySelector('.cmd-input');
            if (mainInput) {
                splitInput.value = mainInput.value;
            }
        }
        
        dom.splitOutput.appendChild(splitLine);
        state.splitPrompt = splitLine;
        
        if (state.autoScroll) {
            dom.splitOutput.scrollTop = dom.splitOutput.scrollHeight;
        }
    }

    /**
     * Apply SQL syntax highlighting to a command string
     */
    /**
     * Create SQL highlighted DOM fragment (avoids innerHTML parsing issues)
     * Returns a DocumentFragment with properly styled spans
     */
    function createHighlightedSQL(cmdText) {
        const fragment = document.createDocumentFragment();
        
        // SQL keywords to highlight
        const keywords = new Set([
            'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'IS', 'NULL',
            'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE',
            'CREATE', 'TABLE', 'DROP', 'ALTER', 'INDEX', 'VIEW',
            'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'ON', 'AS',
            'ORDER', 'BY', 'ASC', 'DESC', 'GROUP', 'HAVING',
            'LIMIT', 'OFFSET', 'DISTINCT', 'COUNT', 'SUM', 'AVG', 'MIN', 'MAX',
            'LIKE', 'BETWEEN', 'EXISTS', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
            'PRAGMA', 'EXPLAIN', 'UNION', 'ALL', 'PRIMARY', 'KEY', 'FOREIGN',
            'REFERENCES', 'DEFAULT', 'CONSTRAINT', 'CHECK', 'UNIQUE'
        ]);
        
        // Tokenize the SQL text
        // Match: strings, numbers, words, operators, whitespace, other
        const tokenRegex = /('[^']*')|(\d+\.?\d*)|(\w+)|([\*=!<>]+)|(\s+)|(.)/g;
        let match;
        
        while ((match = tokenRegex.exec(cmdText)) !== null) {
            const [full, str, num, word, op, space, other] = match;
            
            if (str) {
                // String literal
                const span = document.createElement('span');
                span.className = 'sql-string';
                span.textContent = str;
                fragment.appendChild(span);
            } else if (num) {
                // Number
                const span = document.createElement('span');
                span.className = 'sql-number';
                span.textContent = num;
                fragment.appendChild(span);
            } else if (word) {
                // Word - check if keyword
                if (keywords.has(word.toUpperCase())) {
                    const span = document.createElement('span');
                    span.className = 'sql-keyword';
                    span.textContent = word;
                    fragment.appendChild(span);
                } else {
                    // Regular word (could be table/column name)
                    fragment.appendChild(document.createTextNode(word));
                }
            } else if (op) {
                // Operator
                const span = document.createElement('span');
                span.className = 'sql-operator';
                span.textContent = op;
                fragment.appendChild(span);
            } else if (space) {
                // Whitespace
                fragment.appendChild(document.createTextNode(space));
            } else if (other) {
                // Other character
                fragment.appendChild(document.createTextNode(other));
            }
        }
        
        return fragment;
    }

    function makeCommandLineElement(cmd) {
        const line = document.createElement('div');
        line.className = 'cmd-executed';
        const cmdLower = cmd.trim().toLowerCase();
        const isSqlCommand = cmdLower.startsWith('sql ') || cmdLower.startsWith('query ') || cmdLower.startsWith('exec ');
        if (isSqlCommand) line.classList.add('cmd-sql');
        const promptSpan = document.createElement('span');
        promptSpan.className = 'cmd-prompt';
        promptSpan.textContent = '$';
        line.appendChild(promptSpan);
        const textSpan = document.createElement('span');
        textSpan.className = 'cmd-text';
        if (isSqlCommand) {
            const spaceIndex = cmd.indexOf(' ');
            const cmdName = cmd.substring(0, spaceIndex);
            const sqlPart = cmd.substring(spaceIndex + 1);
            const cmdNameSpan = document.createElement('span');
            cmdNameSpan.className = 'sql-cmd';
            cmdNameSpan.textContent = cmdName;
            textSpan.appendChild(cmdNameSpan);
            textSpan.appendChild(document.createTextNode(' '));
            textSpan.appendChild(createHighlightedSQL(sqlPart));
        } else {
            textSpan.textContent = cmd;
        }
        line.appendChild(textSpan);
        return line;
    }

    /** Creates command block: toggle + command line + expandable output container. */
    function createCommandBlock(cmd) {
        const block = document.createElement('div');
        block.className = 'command-block';
        const commandLine = document.createElement('div');
        commandLine.className = 'command-block-line';
        const toggle = document.createElement('span');
        toggle.className = 'cmd-toggle expanded';
        toggle.setAttribute('title', 'Expand/collapse output');
        toggle.textContent = '\u25BC';
        const lineEl = makeCommandLineElement(cmd);
        commandLine.appendChild(toggle);
        commandLine.appendChild(lineEl);
        const outputContainer = document.createElement('div');
        outputContainer.className = 'command-output-container';
        block.appendChild(commandLine);
        block.appendChild(outputContainer);
        toggle.addEventListener('click', function () {
            const expanded = outputContainer.style.display !== 'none';
            outputContainer.style.display = expanded ? 'none' : 'block';
            toggle.textContent = expanded ? '\u25B6' : '\u25BC';
            toggle.classList.toggle('expanded', !expanded);
        });
        var blockSplit = null, outputContainerSplit = null;
        if (dom.splitOutput) {
            blockSplit = document.createElement('div');
            blockSplit.className = 'command-block';
            const commandLineSplit = document.createElement('div');
            commandLineSplit.className = 'command-block-line';
            const toggleSplit = document.createElement('span');
            toggleSplit.className = 'cmd-toggle expanded';
            toggleSplit.setAttribute('title', 'Expand/collapse output');
            toggleSplit.textContent = '\u25BC';
            const lineElSplit = makeCommandLineElement(cmd);
            commandLineSplit.appendChild(toggleSplit);
            commandLineSplit.appendChild(lineElSplit);
            outputContainerSplit = document.createElement('div');
            outputContainerSplit.className = 'command-output-container';
            blockSplit.appendChild(commandLineSplit);
            blockSplit.appendChild(outputContainerSplit);
            toggleSplit.addEventListener('click', function () {
                const expanded = outputContainerSplit.style.display !== 'none';
                outputContainerSplit.style.display = expanded ? 'none' : 'block';
                toggleSplit.textContent = expanded ? '\u25B6' : '\u25BC';
                toggleSplit.classList.toggle('expanded', !expanded);
            });
        }
        return { block: block, outputContainer: outputContainer, blockSplit: blockSplit, outputContainerSplit: outputContainerSplit };
    }

    function showExecutedCommand(cmd) {
        var ob = createCommandBlock(cmd);
        state.currentOutputContainer = ob.outputContainer;
        state.currentOutputContainerSplit = ob.outputContainerSplit;
        if (state.currentPrompt) {
            dom.output.insertBefore(ob.block, state.currentPrompt);
        } else {
            dom.output.appendChild(ob.block);
        }
        if (ob.blockSplit && dom.splitOutput) {
            if (state.splitPrompt) {
                dom.splitOutput.insertBefore(ob.blockSplit, state.splitPrompt);
            } else {
                dom.splitOutput.appendChild(ob.blockSplit);
            }
        }
    }

    function showCommandOutput(text, type = 'info') {
        const levelMap = {
            'info': 'info',
            'success': 'success',
            'error': 'error',
            'warning': 'warning'
        };
        
        addLogEntry({
            event: 'console',
            level: levelMap[type] || 'info',
            message: text,
            timestamp: Date.now() / 1000
        });
    }

    function appendOutput(type, message) {
        showCommandOutput(message, type);
    }

    function loadCreatedCodeIntoEditor(data) {
        if (!data || data.content == null) return;
        var delegated = false;
        if (typeof window.WorkspaceDocumentStage !== 'undefined' && window.WorkspaceDocumentStage.load) {
            window.WorkspaceDocumentStage.load({
                kind: window.WorkspaceDocumentStage.DOCUMENT_KIND.PYTHON,
                data: data
            });
            delegated = true;
        } else if (typeof window.__workspaceOpenPythonDocument === 'function') {
            window.__workspaceOpenPythonDocument(data);
            delegated = true;
        }
        if (!window.__codeEditor) return;

        window.__codeEditor.value = data.content;

        if (window.__splitCodeEditor) {
            window.__splitCodeEditor.value = data.content;
        }

        if (delegated) return;

        window.dispatchEvent(new CustomEvent('code-editor-loaded', {
            detail: { content: data.content, filePath: data.file_path }
        }));

        window.dispatchEvent(new CustomEvent('code-loaded-from-console', {
            detail: {
                action: data.action,
                id: data.node_id || data.workflow_id,
                module_path: data.module_path,
                file_path: data.file_path,
                registration_status: data.registration_status
            }
        }));
    }

    /**
     * Update Workspace *panel* header for the active document (main tab label stays "Workspace").
     */
    function updateWorkspaceActiveDocumentTitle(filePath) {
        if (!filePath) return;

        const filename = filePath.split(/[/\\]/).pop() || 'Workspace';

        const pythonIcon = `<svg class="tab-icon-svg" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
            <path fill="#3776AB" d="M12 0C5.373 0 5.455.256 5.455 2.857v2.143h6.545v.857H3.818C1.364 5.857 0 7.714 0 11.143c0 3.428 1.714 5.143 3.818 5.143h2.455v-2.857c0-2.143 1.818-4 4.091-4h6.545c2.273 0 4.091-1.714 4.091-4V2.857C21 .256 18.727 0 12 0zm-3.273 1.714a1.286 1.286 0 110 2.572 1.286 1.286 0 010-2.572z"/>
            <path fill="#FFD43B" d="M12 24c6.627 0 6.545-.256 6.545-2.857v-2.143h-6.545v-.857h8.182c2.454 0 3.818-1.857 3.818-5.286 0-3.428-1.714-5.143-3.818-5.143h-2.455v2.857c0 2.143-1.818 4-4.091 4H7.091c-2.273 0-4.091 1.714-4.091 4v2.572C3 23.744 5.273 24 12 24zm3.273-1.714a1.286 1.286 0 110-2.572 1.286 1.286 0 010 2.572z"/>
        </svg>`;

        const iconSlot = document.getElementById('workspace-title-icon-slot');
        if (iconSlot) {
            iconSlot.innerHTML = pythonIcon;
        }

        const titleText = document.getElementById('workspace-title-text');
        if (titleText) {
            titleText.textContent = filename;
            titleText.title = filePath;
        }
        const titleRow = document.getElementById('workspace-panel-title');
        if (titleRow) titleRow.title = filePath;

        const splitPanelTitle = document.querySelector('#split-panel-code .panel-title');
        if (splitPanelTitle) {
            splitPanelTitle.innerHTML = `${pythonIcon}<span>${escapeHtml(filename)}</span>`;
            splitPanelTitle.title = filePath;
        }
    }

    window.__workspaceUpdateActiveTitle = updateWorkspaceActiveDocumentTitle;

    /** Workspace header when an execution-result tab is active */
    function updateWorkspaceExecutionTitle(displayTitle, executionId, format) {
        const iconSlot = document.getElementById('workspace-title-icon-slot');
        if (iconSlot) {
            iconSlot.innerHTML = '<span class="workspace-title-icon-default" title="Execution result">◇</span>';
        }
        const label = (displayTitle && String(displayTitle).trim()) || executionId || 'Result';
        const titleText = document.getElementById('workspace-title-text');
        if (titleText) {
            titleText.textContent = label;
            titleText.title = executionId ? `${label} (${executionId})` : label;
        }
        const titleRow = document.getElementById('workspace-panel-title');
        if (titleRow) titleRow.title = executionId || label;
        const tabLabel = document.getElementById('workspace-tab-label');
        if (tabLabel) {
            tabLabel.textContent = 'Workspace';
            tabLabel.title = format ? `Active: ${label} [${format}]` : label;
        }
    }

    window.__workspaceUpdateExecutionTitle = updateWorkspaceExecutionTitle;

    function __workspaceResetChrome() {
        const formatBadge = document.getElementById('workspace-execution-format-badge');
        if (formatBadge) {
            formatBadge.hidden = true;
            formatBadge.textContent = '—';
        }
        const centerHeader = document.getElementById('workspace-center-header');
        if (centerHeader) centerHeader.hidden = true;
        const iconSlot = document.getElementById('workspace-title-icon-slot');
        if (iconSlot) {
            iconSlot.innerHTML = '<span class="workspace-title-icon-default">⟨⟩</span>';
        }
        const titleText = document.getElementById('workspace-title-text');
        if (titleText) {
            titleText.textContent = 'Workspace';
            titleText.title = '';
        }
        const titleRow = document.getElementById('workspace-panel-title');
        if (titleRow) titleRow.title = '';

        const tabLabel = document.getElementById('workspace-tab-label');
        if (tabLabel) {
            tabLabel.textContent = 'Workspace';
            tabLabel.title = '';
        }

        const splitPanelTitle = document.querySelector('#split-panel-code .panel-title');
        if (splitPanelTitle) {
            splitPanelTitle.innerHTML = '<span>⟨⟩</span><span>Code</span>';
            splitPanelTitle.title = '';
        }
    }

    window.__workspaceResetChrome = __workspaceResetChrome;

    function resetWorkspaceTabLabel() {
        if (typeof window.__workspaceResetAllDocuments === 'function') {
            window.__workspaceResetAllDocuments();
            return;
        }

        const shell = document.getElementById('workspace-shell');
        if (shell) {
            shell.setAttribute('data-workspace-kind', 'none');
        }
        const overlay = document.getElementById('workspace-empty-overlay');
        if (overlay) {
            overlay.style.display = '';
            overlay.setAttribute('aria-hidden', 'false');
        }
        __workspaceResetChrome();
    }

    /** @deprecated use resetWorkspaceTabLabel */
    function resetCodeTabLabel() {
        resetWorkspaceTabLabel();
    }

    /* ==========================================================================
       Output Format Dispatcher - Routes rendering based on format type
       ========================================================================== */

    /**
     * Extract payload for format-specific rendering.
     * Node / workflow completion: data.response.output = { output_format, data }.
     * Legacy: data.output.
     */
    /**
     * Resolve the renderable payload from any incoming data shape.
     *
     * Two cases:
     *  - NodeExecutionResult / WorkflowExecutionResult  →  data.response.output = { output_format, data }
     *    → returns { format: output_format, content: data }
     *  - Command/direct payload  →  data IS the content already
     *    → returns { format: format, content: data }
     */
    function resolveRenderPayload(format, data) {
        if (!data) return { format: format || 'json', content: data };
        const responseOutput = (data.response && data.response.output) ? data.response.output : null;
        if (responseOutput && typeof responseOutput === 'object' && 'data' in responseOutput) {
            const resolvedFormat = (responseOutput.output_format || format || 'json').toLowerCase();
            return { format: resolvedFormat, content: responseOutput.data };
        }
        return { format: format || 'json', content: data };
    }

    /**
     * Validate that payload is compatible with requested format.
     * Returns { compatible: boolean, reason: string }.
     * Unified across node output panel and command console paths.
     */
    function validateFormatPayload(format, payload) {
        if (payload === undefined || payload === null) {
            return { compatible: format === 'json', reason: 'payload is null/undefined' };
        }
        switch (format) {
            case 'table':
                if (!payload || typeof payload !== 'object' || Array.isArray(payload) ||
                    !Array.isArray(payload.columns) || !Array.isArray(payload.rows)) {
                    return { compatible: false, reason: 'table format requires {columns: [...], rows: [...]}' };
                }
                return { compatible: true };
            case 'html':
            case 'text':
            case 'code':
                if (typeof payload !== 'string') {
                    return { compatible: false, reason: `'${format}' format requires a string, got ${typeof payload}` };
                }
                return { compatible: true };
            case 'tree':
                if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
                    return { compatible: false, reason: 'tree format requires a non-array object' };
                }
                return { compatible: true };
            case 'json':
            case 'chart':
            case 'download':
            case 'formData':
            default:
                return { compatible: true };
        }
    }

    /**
     * Dispatch rendering to format-specific handlers
     * @param {string} message - Display message
     * @param {string} type - Output type (info, success, error, warning)
     * @param {string} format - Output format (json, text, html, table, code, progress, tree)
     * @param {any} data - Optional data payload
     */
    function renderConsoleOutput(message, type, format, data) {
        // Special formats that render standalone (no wrapper)
        const standaloneFormats = ['text', 'help', 'progress'];
        
        if (standaloneFormats.includes(format)) {
            // These formats render directly without JSON payload section
            const formatHandlers = {
                'text': renderTextOutput,
                'help': renderHelpOutput,
                'progress': renderProgressOutput,
            };
            const handler = formatHandlers[format];
            if (handler) {
                handler(message, type, data);
            }
            return;
        }
        
        // Create wrapper with 2 toggle sections: JSON Payload + Rendered Format
        const wrapper = document.createElement('div');
        wrapper.className = `cmd-output-wrapper cmd-output--${type}`;
        
        // Container for collapsible content (JSON + Form sections)
        const sectionsContainer = document.createElement('div');
        sectionsContainer.className = 'output-sections';
        
        // Header with message and top-level toggle (for formData and similar)
        const header = document.createElement('div');
        header.className = 'output-header';
        const hasTopToggle = format === 'formData';
        header.innerHTML = `
            <span class="output-header-toggle" title="${hasTopToggle ? 'Show/hide form' : ''}" style="${hasTopToggle ? 'cursor:pointer;margin-right:6px;user-select:none;' : 'display:none;'}">▼</span>
            <span class="output-type-icon">${getTypeIcon(type)}</span>
            <span class="output-message">${escapeHtml(message || '')}</span>
        `;
        wrapper.appendChild(header);
        
        // Section 1: JSON Payload (collapsible, collapsed by default) - navigable tree style
        // Skipped for formData and when rendering in the Output panel (target='output')
        if (data && format !== 'formData' && state._renderTarget !== 'output') {
            const jsonSection = document.createElement('div');
            jsonSection.className = 'output-section output-section--json';
            
            const jsonHeader = document.createElement('div');
            jsonHeader.className = 'section-header';
            jsonHeader.innerHTML = `
                <span class="section-toggle">▶</span>
                <span class="section-title">📦 JSON Payload</span>
            `;
            
            const jsonContent = document.createElement('div');
            jsonContent.className = 'section-content';
            jsonContent.style.display = 'none';
            
            // Render navigable JSON tree (like browser dev console)
            const jsonTreeContainer = document.createElement('div');
            jsonTreeContainer.className = 'json-payload json-tree-container';
            const jsonTree = createJsonTreeNode(data, '', 0, false);
            jsonTreeContainer.appendChild(jsonTree);
            jsonContent.appendChild(jsonTreeContainer);
            
            // Toggle handler
            jsonHeader.addEventListener('click', () => {
                const toggle = jsonHeader.querySelector('.section-toggle');
                const expanded = toggle.textContent === '▼';
                toggle.textContent = expanded ? '▶' : '▼';
                jsonContent.style.display = expanded ? 'none' : 'block';
            });
            
            jsonSection.appendChild(jsonHeader);
            jsonSection.appendChild(jsonContent);
            sectionsContainer.appendChild(jsonSection);
        }
        
        // Section 2: Rendered Format (expanded by default)
        const renderSection = document.createElement('div');
        renderSection.className = `output-section output-section--render output-section--${format}`;
        
        const renderHeader = document.createElement('div');
        renderHeader.className = 'section-header section-header--active';
        renderHeader.innerHTML = `
            <span class="section-toggle">▼</span>
            <span class="section-title">${getFormatIcon(format)} ${getFormatLabel(format)}</span>
        `;
        
        const renderContent = document.createElement('div');
        renderContent.className = 'section-content';
        renderContent.style.display = 'block';  // Explicitly visible by default
        
        // Toggle handler
        renderHeader.addEventListener('click', () => {
            const toggle = renderHeader.querySelector('.section-toggle');
            const expanded = toggle.textContent === '▼';
            toggle.textContent = expanded ? '▶' : '▼';
            renderContent.style.display = expanded ? 'none' : 'block';
            renderHeader.classList.toggle('section-header--active', !expanded);
        });
        
        renderSection.appendChild(renderHeader);
        renderSection.appendChild(renderContent);
        sectionsContainer.appendChild(renderSection);
        wrapper.appendChild(sectionsContainer);
        
        // Top-level toggle for formData: collapse/expand entire block (like log-entry toggle)
        if (hasTopToggle) {
            const headerToggle = header.querySelector('.output-header-toggle');
            headerToggle.style.display = '';
            headerToggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const isExpanded = sectionsContainer.style.display !== 'none';
                sectionsContainer.style.display = isExpanded ? 'none' : '';
                headerToggle.textContent = isExpanded ? '▶' : '▼';
            });
        }
        
        // Resolve renderable {format, content} from any payload shape (NodeResult or direct command payload)
        const resolved = resolveRenderPayload(format, data);
        let renderPayload = resolved.content;
        let effectiveFormat = resolved.format;
        const validation = validateFormatPayload(effectiveFormat, renderPayload);
        if (!validation.compatible) {
            if (state._renderTarget === 'output') {
                addLogEntry({
                    level: 'warning',
                    event: 'output format mismatch',
                    message: `Output data incompatible with format '${effectiveFormat}': ${validation.reason}. Rendering as JSON.`,
                    datetime: new Date().toISOString(),
                });
            }
            effectiveFormat = 'json';
            renderPayload = data;
            renderSection.className = renderSection.className.replace(
                `output-section--${resolved.format}`,
                'output-section--json output-section--format-fallback'
            );
            renderHeader.querySelector('.section-title').innerHTML =
                `${getFormatIcon('json')} JSON View <span class="format-fallback-hint">(requested ${resolved.format} incompatible with payload)</span>`;
        }

        // Render the format content BEFORE inserting into DOM (avoids rendering issues)
        const formatHandlers = {
            'json': renderJsonTreeInto,
            'html': renderHtmlInto,
            'table': renderTableInto,
            'code': renderCodeInto,
            'tree': renderFileTreeInto,
            'formData': renderFormDataInto,
            'chart': renderChartInto,
            'download': renderDownloadInto
        };

        // html/code: payload is guaranteed to be a string (validated above); tree: object
        const formatContent = (['html', 'code', 'tree'].includes(effectiveFormat) && renderPayload != null)
            ? (typeof renderPayload === 'string' ? renderPayload : JSON.stringify(renderPayload, null, 2))
            : message;
        const handler = formatHandlers[effectiveFormat] || formatHandlers['json'];
        handler(renderContent, formatContent, type, renderPayload);
        
        // NOW insert the fully-rendered wrapper into the DOM
        insertOutput(wrapper);
    }
    
    function getTypeIcon(type) {
        const icons = {
            'success': '✅',
            'error': '❌',
            'warning': '⚠️',
            'info': 'ℹ️',
            'debug': '🔍'
        };
        return icons[type] || 'ℹ️';
    }
    
    function getFormatIcon(format) {
        const icons = {
            'json': '{ }',
            'table': '📊',
            'chart': '📈',
            'download': '⬇️',
            'tree': '🌳',
            'html': '🌐',
            'code': '⟨⟩',
            'formData': '📝'
        };
        return icons[format] || '📄';
    }
    
    function getFormatLabel(format) {
        const labels = {
            'json': 'JSON View',
            'table': 'Table View',
            'chart': 'Chart View',
            'download': 'Download',
            'tree': 'Tree View',
            'html': 'HTML View',
            'code': 'Code View',
            'formData': 'Form Input'
        };
        return labels[format] || 'Output';
    }
    
    // =========================================================================
    // Format renderers that render INTO a container (for wrapper structure)
    // =========================================================================
    
    function renderJsonTreeInto(container, message, type, data) {
        if (data === undefined || data === null) {
            if (data === null) {
                container.innerHTML = '<span class="json-null">null</span>';
            }
            return;
        }
        // Use createJsonTreeNode - start collapsed, user expands what they need
        const treeEl = createJsonTreeNode(data, '', 0, false);
        container.appendChild(treeEl);
    }
    
    function renderHtmlInto(container, message, type, data) {
        container.innerHTML = sanitizeHtml(message || data || '');
    }
    
    function validateTablePayload(data) {
        if (!data || typeof data !== 'object') {
            return { valid: false, error: 'Table payload: data is missing or not an object' };
        }
        if (!Array.isArray(data.columns)) {
            return { valid: false, error: 'Table payload: data.columns must be an array of column names' };
        }
        if (!Array.isArray(data.rows)) {
            return { valid: false, error: 'Table payload: data.rows must be an array of row objects' };
        }
        if (data.columns.length === 0 && data.rows.length > 0) {
            return { valid: false, error: 'Table payload: data.columns is empty but data.rows has items' };
        }
        return { valid: true };
    }

    function renderTableInto(container, message, type, data) {
        var validation = validateTablePayload(data);
        if (!validation.valid) {
            console.error('[Table render] ' + validation.error, { data: data });
            showCommandOutput(validation.error, 'error');
            container.innerHTML = '<span class="no-data table-validation-error">' + escapeHtml(validation.error) + '</span>';
            return;
        }
        if (data.rows.length === 0) {
            container.innerHTML = '<span class="no-data">No data</span>';
            return;
        }

        // Table container for horizontal scroll
        const tableContainer = document.createElement('div');
        tableContainer.className = 'table-container';
        
        // Create table
        const table = document.createElement('table');
        table.className = 'data-table';
        table.setAttribute('data-columns', JSON.stringify(data.columns));
        
        // Header row
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        
        data.columns.forEach((col, index) => {
            const th = document.createElement('th');
            th.setAttribute('draggable', 'true');
            th.setAttribute('data-col-index', index);
            th.setAttribute('data-col-name', col);
            
            const colLabel = document.createElement('span');
            colLabel.className = 'col-label';
            colLabel.textContent = col;
            th.appendChild(colLabel);
            
            // Add resize handle
            const resizer = document.createElement('div');
            resizer.className = 'col-resizer';
            resizer.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                initColumnResize(e, th, table);
            });
            th.appendChild(resizer);
            
            // Drag & drop handlers
            th.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', index);
                th.classList.add('dragging');
            });
            th.addEventListener('dragend', () => {
                th.classList.remove('dragging');
            });
            th.addEventListener('dragover', (e) => {
                e.preventDefault();
                th.classList.add('drag-over');
            });
            th.addEventListener('dragleave', () => {
                th.classList.remove('drag-over');
            });
            th.addEventListener('drop', (e) => {
                e.preventDefault();
                th.classList.remove('drag-over');
                const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
                const toIndex = index;
                if (fromIndex !== toIndex) {
                    reorderTableColumns(table, data, fromIndex, toIndex);
                }
            });
            
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);
        
        // Body rows
        const tbody = document.createElement('tbody');
        const totalRows = data.rows.length;
        
        for (let i = 0; i < totalRows; i++) {
            const row = data.rows[i];
            const tr = document.createElement('tr');
            
            data.columns.forEach((col, colIndex) => {
                const td = document.createElement('td');
                const value = row[col] !== undefined ? row[col] : row[colIndex];
                
                if (value === null) {
                    td.innerHTML = '<span class="null-value">NULL</span>';
                } else if (typeof value === 'boolean') {
                    td.innerHTML = value ? '<span class="bool-true">true</span>' : '<span class="bool-false">false</span>';
                } else if (typeof value === 'number') {
                    td.className = 'cell-number';
                    td.textContent = value;
                } else {
                    td.textContent = String(value);
                }
                
                tr.appendChild(td);
            });
            
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        
        tableContainer.appendChild(table);
        container.appendChild(tableContainer);
        
        // Footer with info
        const footer = document.createElement('div');
        footer.className = 'table-footer';
        
        const info = document.createElement('span');
        info.className = 'table-info';
        info.textContent = `Showing ${totalRows} row${totalRows !== 1 ? 's' : ''}`;
        if (data.execution_time_ms) {
            info.textContent += ` (${data.execution_time_ms}ms)`;
        }
        footer.appendChild(info);
        
        // Download CSV button
        const csvBtn = document.createElement('button');
        csvBtn.className = 'table-copy-btn table-export-btn';
        csvBtn.innerHTML = '📋 CSV';
        csvBtn.title = 'Download as CSV';
        csvBtn.addEventListener('click', () => {
            downloadTableData(data.columns, data.rows, 'csv', csvBtn);
        });
        footer.appendChild(csvBtn);
        
        // Download JSON button
        const jsonBtn = document.createElement('button');
        jsonBtn.className = 'table-copy-btn table-export-btn';
        jsonBtn.innerHTML = '{ } JSON';
        jsonBtn.title = 'Download as JSON';
        jsonBtn.addEventListener('click', () => {
            downloadTableData(data.columns, data.rows, 'json', jsonBtn);
        });
        footer.appendChild(jsonBtn);
        
        // Download Excel button
        const excelBtn = document.createElement('button');
        excelBtn.className = 'table-copy-btn table-export-btn table-excel-btn';
        excelBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8 17l2-4-2-4h1.5l1.25 2.5L12 9h1.5l-2 4 2 4H12l-1.25-2.5L9.5 17H8z"/></svg> Excel';
        excelBtn.title = 'Download as Excel';
        excelBtn.addEventListener('click', () => {
            downloadTableData(data.columns, data.rows, 'excel', excelBtn);
        });
        footer.appendChild(excelBtn);
        
        container.appendChild(footer);
    }
    
    function reorderTableColumns(table, data, fromIndex, toIndex) {
        // Reorder columns array
        const columns = [...data.columns];
        const [moved] = columns.splice(fromIndex, 1);
        columns.splice(toIndex, 0, moved);
        data.columns = columns;
        
        // Reorder header cells
        const headerRow = table.querySelector('thead tr');
        const headerCells = Array.from(headerRow.children);
        const [movedHeader] = headerCells.splice(fromIndex, 1);
        headerCells.splice(toIndex, 0, movedHeader);
        headerRow.innerHTML = '';
        headerCells.forEach((cell, i) => {
            cell.setAttribute('data-col-index', i);
            headerRow.appendChild(cell);
        });
        
        // Reorder body cells
        const bodyRows = table.querySelectorAll('tbody tr');
        bodyRows.forEach(row => {
            const cells = Array.from(row.children);
            const [movedCell] = cells.splice(fromIndex, 1);
            cells.splice(toIndex, 0, movedCell);
            row.innerHTML = '';
            cells.forEach(cell => row.appendChild(cell));
        });
    }
    
    function renderCodeInto(container, message, type, data) {
        const lang = (data?.language || 'plaintext').toLowerCase();
        const code = message || '';
        const pre = document.createElement('pre');
        pre.className = 'code-block';
        pre.setAttribute('data-lang', lang);
        const codeEl = document.createElement('code');
        if (lang !== 'plaintext') codeEl.className = 'language-' + lang;
        codeEl.textContent = code;
        pre.appendChild(codeEl);
        container.appendChild(pre);
        if (typeof Prism !== 'undefined' && lang !== 'plaintext' && Prism.languages[lang]) {
            Prism.highlightElement(codeEl);
        }
    }
    
    function renderFileTreeInto(container, message, type, data) {
        container.innerHTML = `<pre class="file-tree">${escapeHtml(message || '')}</pre>`;
    }
    
    function renderFormDataInto(container, message, type, data) {
        // Use existing form rendering logic
        const formContent = buildFormContent(data);
        container.appendChild(formContent);
    }

    const EXECUTION_FORM_SHEET_ID = 'nos-execution-form-sheet';

    function getExecutionFormFocusables(panel) {
        if (!panel) return [];
        const sel = [
            'a[href]',
            'button:not([disabled])',
            'input:not([disabled]):not([type="hidden"])',
            'textarea:not([disabled])',
            'select:not([disabled])',
            '[tabindex]:not([tabindex="-1"])',
        ].join(', ');
        return Array.from(panel.querySelectorAll(sel)).filter(function (el) {
            if (!el || el.getAttribute('aria-hidden') === 'true') return false;
            if (typeof el.checkVisibility === 'function' && !el.checkVisibility()) return false;
            const st = window.getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden') return false;
            return true;
        });
    }

    function focusExecutionFormElement(el) {
        if (!el || typeof el.focus !== 'function') return;
        try {
            el.focus({ preventScroll: true });
        } catch (_e) {
            try { el.focus(); } catch (_e2) { /* noop */ }
        }
    }

    function restoreExecutionFormPreviousFocus(prev) {
        if (!prev || typeof prev.focus !== 'function') return;
        try {
            if (prev.isConnected) focusExecutionFormElement(prev);
        } catch (_e) { /* noop */ }
    }

    function teardownExecutionFormSheetModality(sheet) {
        if (!sheet) return;
        const kd = sheet._nosExecutionFormKeydown;
        if (kd) {
            document.removeEventListener('keydown', kd);
            sheet._nosExecutionFormKeydown = null;
        }
        const fi = sheet._nosExecutionFormFocusIn;
        if (fi) {
            document.removeEventListener('focusin', fi, true);
            sheet._nosExecutionFormFocusIn = null;
        }
    }

    function closeExecutionFormSheet(sheet) {
        if (!sheet || !sheet.parentNode) return;
        teardownExecutionFormSheetModality(sheet);
        sheet.classList.remove('is-open');
        const panel = sheet.querySelector('.execution-form-sheet-panel');
        let finished = false;
        const done = function () {
            if (finished) return;
            finished = true;
            if (panel) {
                panel.removeEventListener('transitionend', onTransitionEnd);
            }
            clearTimeout(fallbackTimer);
            const returnEl = sheet._nosReturnFocus;
            sheet._nosReturnFocus = null;
            restoreExecutionFormPreviousFocus(returnEl);
            sheet.remove();
        };
        const onTransitionEnd = function (e) {
            if (e.target === panel && (e.propertyName === 'transform' || e.propertyName === 'opacity')) {
                done();
            }
        };
        if (panel) {
            panel.addEventListener('transitionend', onTransitionEnd);
        }
        const fallbackTimer = setTimeout(done, 420);
    }

    /**
     * Opens the execution input form in a bottom sheet (not inside the log row detail).
     * Log lines stay JSON-only in .log-details; the interactive form lives in the overlay.
     */
    function appendFormToLogEntry(requestId, formPayload) {
        const existing = document.getElementById(EXECUTION_FORM_SHEET_ID);
        if (existing) {
            teardownExecutionFormSheetModality(existing);
            restoreExecutionFormPreviousFocus(existing._nosReturnFocus);
            existing._nosReturnFocus = null;
            existing.remove();
        }

        const sheet = document.createElement('div');
        sheet.id = EXECUTION_FORM_SHEET_ID;
        sheet.className = 'execution-form-sheet';
        sheet.setAttribute('data-request-id', requestId || '');

        const panel = document.createElement('div');
        panel.className = 'execution-form-sheet-panel';
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-modal', 'true');
        panel.setAttribute('aria-labelledby', 'nos-execution-form-sheet-title');

        const header = document.createElement('div');
        header.className = 'execution-form-sheet-header';
        const titleText = formPayload.title || 'Configure execution';
        const metaParts = [];
        if (formPayload.node_id) metaParts.push(String(formPayload.node_id));
        if (formPayload.workflow_id) metaParts.push(String(formPayload.workflow_id));
        const metaHtml = metaParts.length
            ? `<span class="execution-form-sheet-meta">[${metaParts.map(escapeHtml).join(' · ')}]</span>`
            : '';
        header.innerHTML = `
            <div class="execution-form-sheet-handle" aria-hidden="true"></div>
            <div class="execution-form-sheet-title-row">
                <span class="execution-form-sheet-icon" aria-hidden="true">⚙</span>
                <span class="execution-form-sheet-title" id="nos-execution-form-sheet-title">${escapeHtml(titleText)}</span>
                ${metaHtml}
            </div>
        `;

        const body = document.createElement('div');
        body.className = 'execution-form-sheet-body';
        body.appendChild(buildFormContent(formPayload));

        panel.appendChild(header);
        panel.appendChild(body);
        sheet.appendChild(panel);

        sheet.addEventListener('click', function (e) {
            if (e.target !== sheet) return;
            const form = sheet.querySelector('.interactive-form');
            if (!form) return;
            const sendBtn = form.querySelector('.form-send-btn');
            if (sendBtn && sendBtn.disabled) return;
            handleFormSubmit(requestId, form, true);
        });

        sheet._nosReturnFocus = document.activeElement;

        const onFocusIn = function (e) {
            if (!sheet.isConnected || !sheet.classList.contains('is-open')) return;
            if (panel.contains(e.target)) return;
            const list = getExecutionFormFocusables(panel);
            if (list.length) focusExecutionFormElement(list[0]);
        };
        sheet._nosExecutionFormFocusIn = onFocusIn;
        document.addEventListener('focusin', onFocusIn, true);

        const onKeydown = function (e) {
            if (document.getElementById(EXECUTION_FORM_SHEET_ID) !== sheet) return;
            const form = sheet.querySelector('.interactive-form');
            const sendBtn = form && form.querySelector('.form-send-btn');

            if (e.key === 'Escape') {
                if (!form) return;
                if (sendBtn && sendBtn.disabled) return;
                e.preventDefault();
                handleFormSubmit(requestId, form, true);
                return;
            }

            if (e.key === 'Tab') {
                const list = getExecutionFormFocusables(panel);
                if (list.length === 0) return;
                const first = list[0];
                const last = list[list.length - 1];
                const active = document.activeElement;
                if (e.shiftKey) {
                    if (active === first || !panel.contains(active)) {
                        e.preventDefault();
                        focusExecutionFormElement(last);
                    }
                } else {
                    if (active === last || !panel.contains(active)) {
                        e.preventDefault();
                        focusExecutionFormElement(first);
                    }
                }
            }
        };
        sheet._nosExecutionFormKeydown = onKeydown;
        document.addEventListener('keydown', onKeydown);

        document.body.appendChild(sheet);
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                sheet.classList.add('is-open');
                const list = getExecutionFormFocusables(panel);
                if (list.length) focusExecutionFormElement(list[0]);
            });
        });

        if (state.autoScroll) scrollToBottom();
    }
    
    function renderChartInto(container, message, type, data) {
        if (!data) return;
        
        // Chart controls
        const controls = document.createElement('div');
        controls.className = 'chart-controls';
        controls.innerHTML = `
            <select class="chart-type-select">
                <option value="bar" ${data.type === 'bar' ? 'selected' : ''}>📊 Bar</option>
                <option value="line" ${data.type === 'line' ? 'selected' : ''}>📈 Line</option>
                <option value="pie" ${data.type === 'pie' ? 'selected' : ''}>🥧 Pie</option>
                <option value="doughnut" ${data.type === 'doughnut' ? 'selected' : ''}>🍩 Doughnut</option>
            </select>
        `;
        container.appendChild(controls);
        
        // Chart canvas
        const chartContainer = document.createElement('div');
        chartContainer.className = 'chart-canvas-container';
        const chartSvg = createSimpleChart(data);
        chartContainer.appendChild(chartSvg);
        container.appendChild(chartContainer);
        
        // Legend
        if (data.labels && data.datasets) {
            const legend = createChartLegend(data);
            container.appendChild(legend);
        }
        
        // Type change handler
        const typeSelect = controls.querySelector('.chart-type-select');
        typeSelect.addEventListener('change', () => {
            data.type = typeSelect.value;
            chartContainer.innerHTML = '';
            chartContainer.appendChild(createSimpleChart(data));
        });
    }
    
    function renderDownloadInto(container, message, type, data) {
        if (!data || !data.url) return;
        
        const filename = data.filename || data.url.split('/').pop() || 'download';
        const ext = filename.split('.').pop().toLowerCase();
        const icon = getFileIcon(ext);
        const sizeStr = data.size ? formatFileSize(data.size) : '';
        
        container.innerHTML = `
            <a href="${escapeHtml(data.url)}" class="download-link" download="${escapeHtml(filename)}" target="_blank">
                <span class="download-icon">${icon}</span>
                <div class="download-info">
                    <span class="download-filename">${escapeHtml(filename)}</span>
                    ${sizeStr ? `<span class="download-size">${sizeStr}</span>` : ''}
                    ${message ? `<span class="download-desc">${escapeHtml(message)}</span>` : ''}
                </div>
                <span class="download-action">⬇️ Download</span>
            </a>
        `;
    }
    
    /**
     * Build form content for formData format
     */
    function buildFormContent(data) {
        const form = document.createElement('form');
        form.className = 'interactive-form';
        form.setAttribute('data-request-id', data.request_id || '');
        
        // State section
        if (data.state && data.state.fields && data.state.fields.length > 0) {
            const stateSection = createFormSection('state', data.state);
            form.appendChild(stateSection);
        }
        
        // Params section
        if (data.params && data.params.fields && data.params.fields.length > 0) {
            const paramsSection = createFormSection('params', data.params);
            form.appendChild(paramsSection);
        }
        
        // Button row
        const buttonRow = document.createElement('div');
        buttonRow.className = 'form-button-row';
        
        const sendBtn = document.createElement('button');
        sendBtn.type = 'button';
        sendBtn.className = 'form-send-btn';
        sendBtn.innerHTML = '<span class="send-icon">➤</span> Send';
        
        sendBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            handleFormSubmit(data.request_id, form, false);
        });
        
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'form-cancel-btn';
        cancelBtn.innerHTML = '<span class="cancel-icon">✕</span> Cancel';
        
        cancelBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            handleFormSubmit(data.request_id, form, true);
        });
        
        buttonRow.appendChild(cancelBtn);
        buttonRow.appendChild(sendBtn);
        form.appendChild(buttonRow);
        
        // Prevent native form submission
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            e.stopPropagation();
            return false;
        });
        
        return form;
    }

    /**
     * Text output renderer - handles newlines and preserves formatting
     */
    function renderTextOutput(message, type, data) {
        if (!message && !data) return;
        
        const output = document.createElement('div');
        output.className = `cmd-output cmd-output--text cmd-output--${type}`;
        
        // Prepare full text for copy
        let fullText = message || '';
        
        // Create header with copy button
        const header = document.createElement('div');
        header.className = 'output-header';
        header.appendChild(createCopyButton(fullText));
        output.appendChild(header);
        
        // Create text content with preserved whitespace
        const textContent = document.createElement('pre');
        textContent.className = 'cmd-text-content';
        textContent.textContent = message || '';
        output.appendChild(textContent);
        
        // If there's additional data, render it below
        if (data) {
            let dataText;
            try {
                dataText = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
            } catch (e) {
                dataText = String(data);
            }
            fullText += '\n\n' + dataText;
            
            const dataContent = document.createElement('pre');
            dataContent.className = 'cmd-text-data';
            dataContent.textContent = dataText;
            output.appendChild(dataContent);
            
            // Update copy button with full text
            header.innerHTML = '';
            header.appendChild(createCopyButton(fullText));
        }
        
        insertOutput(output);
    }
    
    /**
     * Help output renderer - shows a short message with a link to the full help page (opens in new tab).
     */
    function renderHelpOutput(message, type, data) {
        const output = document.createElement('div');
        output.className = 'cmd-output cmd-output--help';
        const link = document.createElement('a');
        const pathPrefix = (typeof window !== 'undefined' && window.location && window.location.pathname)
            ? window.location.pathname.replace(/\/(engine\/)?console.*$/, '') : '';
        link.href = pathPrefix + '/engine/help';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = 'Apri il riferimento comandi (Help)';
        link.className = 'help-page-link';
        const text = document.createElement('span');
        text.className = 'help-page-message';
        text.textContent = 'Full console commands reference: description, parameters and examples. ';
        output.appendChild(text);
        output.appendChild(link);
        link.textContent = 'Open Help page';
        output.appendChild(document.createTextNode('.'));
        insertOutput(output);
    }

    /* ==========================================================================
       Form Data Renderer - Interactive forms for state/params editing
       ========================================================================== */
    
    /**
     * Render an interactive form for editing state and parameters.
     * Used for node/workflow configuration during execution.
     * 
     * @param {string} message - Optional header message
     * @param {string} type - Output type (info, success, etc.)
     * @param {object} data - Form data with structure:
     *   {
     *     request_id: string,      // For response routing
     *     title: string,           // Form title
     *     node_id: string,         // Node identifier
     *     state: { label, description, collapsed, fields: [...] },
     *     params: { label, description, collapsed, fields: [...] }
     *   }
     */
    function renderFormDataOutput(message, type, data) {
        if (!data) return;
        
        const output = document.createElement('div');
        output.className = 'cmd-output cmd-output--form';
        
        // Form title header
        const header = document.createElement('div');
        header.className = 'form-header';
        header.innerHTML = `
            <span class="form-icon">⚙</span>
            <span class="form-title">${escapeHtml(data.title || 'Configure Execution')}</span>
            ${data.node_id ? `<span class="form-node-id">[${escapeHtml(data.node_id)}]</span>` : ''}
        `;
        output.appendChild(header);
        
        // Create form element
        const form = document.createElement('form');
        form.className = 'interactive-form';
        form.setAttribute('data-request-id', data.request_id || '');
        
        // State section
        if (data.state && data.state.fields) {
            const stateSection = createFormSection('state', data.state);
            form.appendChild(stateSection);
        }
        
        // Params section
        if (data.params && data.params.fields) {
            const paramsSection = createFormSection('params', data.params);
            form.appendChild(paramsSection);
        }
        
        // Send button - use type="button" to prevent form submission
        const buttonRow = document.createElement('div');
        buttonRow.className = 'form-button-row';
        
        const sendBtn = document.createElement('button');
        sendBtn.type = 'button';
        sendBtn.className = 'form-send-btn';
        sendBtn.innerHTML = '<span class="send-icon">➤</span><span class="send-label">Send</span>';
        
        sendBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            handleFormSubmit(data.request_id, form, false);
        });
        
        buttonRow.appendChild(sendBtn);
        
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'form-cancel-btn';
        cancelBtn.innerHTML = '<span class="cancel-icon">✕</span><span class="cancel-label">Cancel</span>';
        
        cancelBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            handleFormSubmit(data.request_id, form, true);
        });
        
        buttonRow.appendChild(cancelBtn);
        
        form.appendChild(buttonRow);
        
        // Prevent any form submission (backup)
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            e.stopPropagation();
            return false;
        });
        
        output.appendChild(form);
        insertOutput(output);
        
        // Focus first input
        const firstInput = form.querySelector('input, select, textarea');
        if (firstInput) {
            setTimeout(() => firstInput.focus(), 100);
        }
    }
    
    /**
     * Create a collapsible form section (State or Params)
     */
    function createFormSection(sectionName, sectionData) {
        sectionData = sectionData || { label: sectionName, fields: [] };
        const fields = Array.isArray(sectionData.fields) ? sectionData.fields : [];
        const section = document.createElement('div');
        section.className = `form-section form-section--${sectionName}`;
        
        const isCollapsed = sectionData.collapsed !== false && fields.length === 0;
        
        // Section header with toggle
        const sectionHeader = document.createElement('div');
        sectionHeader.className = 'form-section-header';
        sectionHeader.innerHTML = `
            <span class="section-toggle ${isCollapsed ? '' : 'expanded'}">${isCollapsed ? '▶' : '▼'}</span>
            <span class="section-label">${escapeHtml(sectionData.label || sectionName)}</span>
            <span class="section-count">(${fields.length} fields)</span>
        `;
        
        // Section content
        const sectionContent = document.createElement('div');
        sectionContent.className = 'form-section-content';
        sectionContent.style.display = isCollapsed ? 'none' : 'flex';
        
        if (sectionData.description && fields.length === 0) {
            const desc = document.createElement('div');
            desc.className = 'section-empty-message';
            desc.textContent = sectionData.description;
            sectionContent.appendChild(desc);
        }
        
        // Render fields
        fields.forEach(field => {
            const fieldEl = createFormField(field, sectionName);
            sectionContent.appendChild(fieldEl);
        });
        
        // Toggle click handler
        sectionHeader.addEventListener('click', () => {
            const toggle = sectionHeader.querySelector('.section-toggle');
            const expanded = toggle.classList.toggle('expanded');
            toggle.textContent = expanded ? '▼' : '▶';
            sectionContent.style.display = expanded ? 'flex' : 'none';
        });
        
        section.appendChild(sectionHeader);
        section.appendChild(sectionContent);
        
        return section;
    }
    
    /**
     * Create a form field based on its type
     */
    function createFormField(field, sectionName) {
        const wrapper = document.createElement('div');
        wrapper.className = `form-field form-field--${field.type}`;
        
        // Label
        const label = document.createElement('label');
        label.className = 'field-label';
        label.setAttribute('for', `${sectionName}-${field.name}`);
        label.innerHTML = `
            ${escapeHtml(field.label)}
            ${field.required ? '<span class="field-required">*</span>' : ''}
        `;
        wrapper.appendChild(label);
        
        // Input element based on type
        let input;
        const inputId = `${sectionName}-${field.name}`;
        const inputName = `${sectionName}[${field.name}]`;
        
        switch (field.type) {
            case 'json':
                // JSON textarea: stringify object/array for display, parse on submit (decode: "json")
                input = document.createElement('textarea');
                input.rows = field.rows || 6;
                input.placeholder = field.placeholder || '{"key": "value"}';
                if (field.value !== undefined && field.value !== null) {
                    input.value = (typeof field.value === 'object')
                        ? JSON.stringify(field.value, null, 2)
                        : (typeof field.value === 'string' ? field.value : String(field.value));
                } else {
                    input.value = '';
                }
                input.setAttribute('data-decode', 'json');
                wrapper.classList.add('form-field--json');
                input.addEventListener('input', () => {
                    input.classList.remove('field-error');
                    const f = input.closest('.interactive-form');
                    if (f) {
                        const errEl = f.querySelector('.form-validation-error');
                        if (errEl) errEl.remove();
                    }
                });
                break;
                
            case 'textarea':
                input = document.createElement('textarea');
                input.rows = field.rows || 4;
                input.value = field.value || '';
                break;
                
            case 'select':
                input = document.createElement('select');
                if (field.options) {
                    field.options.forEach(opt => {
                        const option = document.createElement('option');
                        option.value = opt.value;
                        option.textContent = opt.label || opt.value;
                        if (opt.value === field.value) option.selected = true;
                        input.appendChild(option);
                    });
                }
                break;
                
            case 'checkbox':
                input = document.createElement('input');
                input.type = 'checkbox';
                input.checked = field.value === true;
                wrapper.classList.add('form-field--inline');
                break;
                
            case 'range':
                // Slider with value display
                const sliderWrapper = document.createElement('div');
                sliderWrapper.className = 'slider-wrapper';
                
                input = document.createElement('input');
                input.type = 'range';
                if (field.min !== undefined) input.min = field.min;
                if (field.max !== undefined) input.max = field.max;
                if (field.step !== undefined) input.step = field.step;
                input.value = field.value !== undefined ? field.value : (field.min || 0);
                
                const valueDisplay = document.createElement('span');
                valueDisplay.className = 'slider-value';
                valueDisplay.textContent = input.value;
                
                input.addEventListener('input', () => {
                    valueDisplay.textContent = input.value;
                });
                
                sliderWrapper.appendChild(input);
                sliderWrapper.appendChild(valueDisplay);
                // label is already appended before the switch; only append sliderWrapper here
                wrapper.appendChild(sliderWrapper);
                
                // Add description if present
                if (field.description) {
                    const desc = document.createElement('div');
                    desc.className = 'field-description';
                    desc.textContent = field.description;
                    wrapper.appendChild(desc);
                }
                
                // Set data attributes for form collection
                input.id = inputId;
                input.name = inputName;
                input.setAttribute('data-field-name', field.name);
                input.setAttribute('data-section', sectionName);
                if (field.required) input.required = true;
                
                return wrapper;
                
            case 'file':
                input = document.createElement('input');
                input.type = 'file';
                if (field.accept) input.accept = field.accept;
                if (field.multiple) input.multiple = true;
                wrapper.classList.add('form-field--file');
                if (field.max_size_mb != null || (field.extra && field.extra.max_size_mb != null)) {
                    wrapper.setAttribute('data-max-size-mb', String(field.max_size_mb != null ? field.max_size_mb : field.extra.max_size_mb));
                }
                if (field.accept) wrapper.setAttribute('data-accept', field.accept);
                var progressPlaceholder = document.createElement('div');
                progressPlaceholder.className = 'upload-progress-placeholder';
                progressPlaceholder.style.minHeight = '0';
                input.id = inputId;
                input.name = inputName;
                input.className = 'field-input';
                input.setAttribute('data-field-name', field.name);
                input.setAttribute('data-section', sectionName);
                if (field.required) input.required = true;
                if (field.disabled) input.disabled = true;
                if (field.readonly) input.readOnly = true;
                wrapper.appendChild(input);
                wrapper.appendChild(progressPlaceholder);
                if (field.description) {
                    var fileDesc = document.createElement('div');
                    fileDesc.className = 'field-description';
                    fileDesc.textContent = field.description;
                    wrapper.appendChild(fileDesc);
                }
                return wrapper;
                
            default:
                // text, number, email, password, url, date, time, color, etc.
                input = document.createElement('input');
                input.type = field.type || 'text';
                input.value = field.value !== undefined ? field.value : '';
                if (field.min !== undefined) input.min = field.min;
                if (field.max !== undefined) input.max = field.max;
                if (field.step !== undefined) input.step = field.step;
                if (field.minLength !== undefined) input.minLength = field.minLength;
                if (field.maxLength !== undefined) input.maxLength = field.maxLength;
                if (field.pattern) input.pattern = field.pattern;
                if (field.placeholder) input.placeholder = field.placeholder;
                break;
        }
        
        // Common input attributes
        input.id = inputId;
        input.name = inputName;
        input.className = 'field-input';
        input.setAttribute('data-field-name', field.name);
        input.setAttribute('data-section', sectionName);
        if (field.required) input.required = true;
        if (field.disabled) input.disabled = true;
        if (field.readonly) input.readOnly = true;
        
        // Password field: wrap input + show/hide toggle in a row
        if ((field.type || '') === 'password') {
            const row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:4px;';
            row.appendChild(input);
            const toggleBtn = document.createElement('button');
            toggleBtn.type = 'button';
            toggleBtn.className = 'field-password-toggle';
            toggleBtn.setAttribute('aria-label', 'Show password');
            toggleBtn.title = 'Show / hide';
            toggleBtn.innerHTML = '&#128065;'; // eye
            toggleBtn.style.cssText = 'padding:4px 8px;cursor:pointer;border:1px solid #444;border-radius:4px;background:#2a2a2a;color:#ccc;font-size:1em;';
            toggleBtn.addEventListener('click', function () {
                if (input.type === 'password') {
                    input.type = 'text';
                    toggleBtn.innerHTML = '&#128064;'; // eye-slash
                    toggleBtn.setAttribute('aria-label', 'Hide password');
                } else {
                    input.type = 'password';
                    toggleBtn.innerHTML = '&#128065;';
                    toggleBtn.setAttribute('aria-label', 'Show password');
                }
            });
            row.appendChild(toggleBtn);
            wrapper.appendChild(row);
        } else {
            wrapper.appendChild(input);
        }
        
        // Description
        if (field.description) {
            const desc = document.createElement('div');
            desc.className = 'field-description';
            desc.textContent = field.description;
            wrapper.appendChild(desc);
        }
        
        return wrapper;
    }
    
    /**
     * Validate JSON-decodeable fields before submit. Returns { valid, errors }.
     */
    function validateFormJsonFields(form) {
        const errors = [];
        const inputs = form.querySelectorAll('[data-field-name][data-decode="json"]');
        inputs.forEach(input => {
            const fieldName = input.getAttribute('data-field-name');
            const section = input.getAttribute('data-section');
            const raw = (input.tagName === 'TEXTAREA' ? input.value : input.value).trim();
            if (raw === '') return;  // empty is ok (optional) or will be handled by required
            try {
                JSON.parse(raw);
            } catch (e) {
                errors.push({
                    field: fieldName,
                    section,
                    message: e.message || 'Invalid JSON'
                });
            }
        });
        return { valid: errors.length === 0, errors };
    }

    var UPLOAD_TEMP_URL = '/api/upload/temp';

    /**
     * Collect form data, uploading file fields via HTTP first to get upload_id(s).
     * Returns Promise<{ state, params }>. Uses UploadProgress for progress bar.
     */
    async function collectFormDataWithFileUploads(form) {
        const result = { state: {}, params: {} };
        const inputs = form.querySelectorAll('[data-field-name]');
        const fileUploadPromises = [];

        for (const input of inputs) {
            const fieldName = input.getAttribute('data-field-name');
            const section = input.getAttribute('data-section');
            const decode = input.getAttribute('data-decode');

            if (input.type === 'file' && input.files && input.files.length > 0) {
                const multiple = input.multiple;
                const fieldWrapper = input.closest('.form-field');
                const placeholder = fieldWrapper ? fieldWrapper.querySelector('.upload-progress-placeholder') : null;
                const uploadFd = new FormData();
                for (let i = 0; i < input.files.length; i++) {
                    uploadFd.append(multiple ? 'files[]' : 'file', input.files[i]);
                }
                var fw = input.closest('.form-field');
                if (fw && fw.getAttribute('data-max-size-mb')) uploadFd.append('max_size_mb', fw.getAttribute('data-max-size-mb'));
                if (fw && fw.getAttribute('data-accept')) uploadFd.append('accept', fw.getAttribute('data-accept'));
                const uploadPromise = (typeof window !== 'undefined' && window.UploadProgress && window.UploadProgress.uploadWithProgress
                    ? window.UploadProgress.uploadWithProgress(UPLOAD_TEMP_URL, uploadFd, { progressContainer: placeholder || null })
                    : Promise.resolve({ success: false, error: 'UploadProgress not loaded', uploads: [] })
                ).then(function (res) {
                    if (!res.success) throw new Error(res.error || 'Upload failed');
                    const ids = (res.uploads || []).map(function (u) { return u.upload_id; });
                    return { fieldName, section, value: multiple && ids.length > 1 ? ids : (ids[0] || null) };
                });
                fileUploadPromises.push(uploadPromise);
            } else {
                let value;
                if (input.type === 'checkbox') {
                    value = input.checked;
                } else if (input.type === 'number' || input.type === 'range') {
                    value = input.value === '' ? null : parseFloat(input.value);
                } else if (input.type === 'file') {
                    value = null;
                } else if (decode === 'json') {
                    const raw = (input.tagName === 'TEXTAREA' ? input.value : input.value).trim();
                    if (raw === '') value = {};
                    else {
                        try { value = JSON.parse(raw); } catch (e) { value = raw; }
                    }
                } else {
                    value = input.value;
                }
                if (section === 'state') result.state[fieldName] = value;
                else if (section === 'params') result.params[fieldName] = value;
            }
        }

        const fileResults = await Promise.all(fileUploadPromises);
        fileResults.forEach(function (r) {
            if (r.section === 'state') result.state[r.fieldName] = r.value;
            else if (r.section === 'params') result.params[r.fieldName] = r.value;
        });
        return result;
    }

    /**
     * Collect form data from all fields (synchronous; file fields return filename - use collectFormDataWithFileUploads for upload_id)
     */
    function collectFormData(form) {
        const result = {
            state: {},
            params: {}
        };
        
        const inputs = form.querySelectorAll('[data-field-name]');
        inputs.forEach(input => {
            const fieldName = input.getAttribute('data-field-name');
            const section = input.getAttribute('data-section');
            const decode = input.getAttribute('data-decode');
            
            let value;
            if (input.type === 'checkbox') {
                value = input.checked;
            } else if (input.type === 'number' || input.type === 'range') {
                value = input.value === '' ? null : parseFloat(input.value);
            } else if (input.type === 'file') {
                value = input.files.length > 0 ? input.files[0].name : null;
            } else if (decode === 'json') {
                const raw = (input.tagName === 'TEXTAREA' ? input.value : input.value).trim();
                if (raw === '') {
                    value = {};
                } else {
                    try {
                        value = JSON.parse(raw);
                    } catch (e) {
                        value = raw;  // fallback if validation was skipped
                    }
                }
            } else {
                value = input.value;
            }
            
            if (section === 'state') {
                result.state[fieldName] = value;
            } else if (section === 'params') {
                result.params[fieldName] = value;
            }
        });
        
        return result;
    }

    /* ==========================================================================
       JSON Tree Renderer - Browser DevTools-style navigable tree
       ========================================================================== */
    
    /**
     * Render JSON as an interactive navigable tree (like browser dev console)
     */
    function renderJsonTreeOutput(message, type, data) {
        // Show message first
        if (message) {
            showCommandOutput(message, type);
        }
        
        // If no data, nothing more to render
        if (data === undefined || data === null) {
            if (data === null) {
                const output = document.createElement('div');
                output.className = 'cmd-output cmd-output--json-tree';
                output.innerHTML = '<span class="json-null">null</span>';
                insertOutput(output);
            }
            return;
        }
        
        const output = document.createElement('div');
        output.className = 'cmd-output cmd-output--json-tree';
        
        // Add copy button header
        const header = document.createElement('div');
        header.className = 'output-header';
        try {
            const jsonText = JSON.stringify(data, null, 2);
            header.appendChild(createCopyButton(jsonText));
        } catch (e) {
            header.appendChild(createCopyButton(String(data)));
        }
        output.appendChild(header);
        
        // Build the tree - start collapsed (false), user expands what they need
        const tree = createJsonTreeNode(data, '', 0, false);
        output.appendChild(tree);
        
        insertOutput(output);
    }
    
    /**
     * Create a JSON tree node recursively
     * @param {any} value - The value to render
     * @param {string} key - The key name (empty for root)
     * @param {number} depth - Current nesting depth
     * @param {boolean} isExpanded - Whether to start expanded
     * @returns {HTMLElement}
     */
    function createJsonTreeNode(value, key, depth, isExpanded) {
        const node = document.createElement('div');
        node.className = 'json-tree-node';
        node.style.paddingLeft = (depth * 16) + 'px';
        
        const type = getJsonType(value);
        
        if (type === 'object' || type === 'array') {
            // Expandable node
            const isArray = type === 'array';
            const keys = isArray ? value : Object.keys(value);
            const count = isArray ? value.length : keys.length;
            const isEmpty = count === 0;
            
            // Toggle button
            const toggle = document.createElement('span');
            toggle.className = 'json-tree-toggle' + (isExpanded && !isEmpty ? ' expanded' : '');
            toggle.textContent = isEmpty ? ' ' : (isExpanded ? '▼' : '▶');
            toggle.style.cursor = isEmpty ? 'default' : 'pointer';
            
            // Key name (if not root)
            const keySpan = document.createElement('span');
            keySpan.className = 'json-tree-key';
            if (key !== '') {
                keySpan.innerHTML = `<span class="json-key">"${escapeHtml(key)}"</span>: `;
            }
            
            // Preview/summary
            const preview = document.createElement('span');
            preview.className = 'json-tree-preview';
            
            if (isEmpty) {
                preview.innerHTML = isArray ? '<span class="json-bracket">[]</span>' : '<span class="json-bracket">{}</span>';
            } else {
                const openBracket = isArray ? '[' : '{';
                const closeBracket = isArray ? ']' : '}';
                const previewText = isArray 
                    ? `Array(${count})`
                    : `{${Object.keys(value).slice(0, 3).map(k => escapeHtml(k)).join(', ')}${count > 3 ? '...' : ''}}`;
                preview.innerHTML = `<span class="json-bracket">${openBracket}</span><span class="json-preview-text">${previewText}</span>`;
            }
            
            // Children container
            const children = document.createElement('div');
            children.className = 'json-tree-children';
            children.style.display = (isExpanded && !isEmpty) ? 'block' : 'none';
            
            if (!isEmpty) {
                if (isArray) {
                    value.forEach((item, index) => {
                        children.appendChild(createJsonTreeNode(item, String(index), depth + 1, false));
                    });
                } else {
                    Object.keys(value).forEach(k => {
                        children.appendChild(createJsonTreeNode(value[k], k, depth + 1, false));
                    });
                }
                
                // Closing bracket
                const closingBracket = document.createElement('div');
                closingBracket.className = 'json-tree-closing';
                closingBracket.style.paddingLeft = (depth * 16) + 'px';
                closingBracket.innerHTML = `<span class="json-bracket">${isArray ? ']' : '}'}</span>`;
                children.appendChild(closingBracket);
            }
            
            // Toggle click handler
            if (!isEmpty) {
                toggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const expanded = toggle.classList.toggle('expanded');
                    toggle.textContent = expanded ? '▼' : '▶';
                    children.style.display = expanded ? 'block' : 'none';
                    
                    // Update preview visibility
                    const previewText = preview.querySelector('.json-preview-text');
                    if (previewText) {
                        previewText.style.display = expanded ? 'none' : 'inline';
                    }
                });
                
                // Also toggle on key click
                keySpan.style.cursor = 'pointer';
                keySpan.addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggle.click();
                });
            }
            
            node.appendChild(toggle);
            node.appendChild(keySpan);
            node.appendChild(preview);
            node.appendChild(children);
            
        } else {
            // Primitive value (string, number, boolean, null)
            const toggle = document.createElement('span');
            toggle.className = 'json-tree-toggle';
            toggle.textContent = ' ';  // Space placeholder for alignment
            
            const keySpan = document.createElement('span');
            keySpan.className = 'json-tree-key';
            if (key !== '') {
                keySpan.innerHTML = `<span class="json-key">"${escapeHtml(key)}"</span>: `;
            }
            
            const valueSpan = document.createElement('span');
            valueSpan.className = 'json-tree-value json-' + type;
            valueSpan.textContent = formatPrimitiveValue(value, type);
            
            node.appendChild(toggle);
            node.appendChild(keySpan);
            node.appendChild(valueSpan);
        }
        
        return node;
    }
    
    /**
     * Get the JSON type of a value
     */
    function getJsonType(value) {
        if (value === null) return 'null';
        if (Array.isArray(value)) return 'array';
        const t = typeof value;
        if (t === 'object') return 'object';
        if (t === 'string') return 'string';
        if (t === 'number') return 'number';
        if (t === 'boolean') return 'boolean';
        return 'unknown';
    }
    
    /**
     * Format a primitive value for display
     */
    function formatPrimitiveValue(value, type) {
        if (type === 'string') {
            // Truncate long strings
            const maxLen = 100;
            const str = String(value);
            if (str.length > maxLen) {
                return '"' + str.substring(0, maxLen) + '..."';
            }
            return '"' + str + '"';
        }
        if (type === 'null') return 'null';
        if (type === 'boolean') return value ? 'true' : 'false';
        return String(value);
    }

    /**
     * Render expandable JSON tree into a container (engine console v2 Output tab).
     * Reuses createJsonTreeNode (DevTools-style). Clears only when data === undefined.
     */
    window.__renderJsonTreeIntoElement = function (targetEl, data) {
        if (!targetEl) return;
        targetEl.innerHTML = '';
        if (data === undefined) return;
        if (data === null) {
            const n = document.createElement('div');
            n.className = 'v2-json-tree-root cmd-output cmd-output--json-tree';
            n.innerHTML = '<span class="json-null">null</span>';
            targetEl.appendChild(n);
            return;
        }
        const wrap = document.createElement('div');
        wrap.className = 'v2-json-tree-root cmd-output cmd-output--json-tree';
        wrap.appendChild(createJsonTreeNode(data, '', 0, false));
        targetEl.appendChild(wrap);
    };

    /**
     * Render file/folder tree structure (for plugin tree, etc.)
     */
    function renderFileTreeOutput(message, type, data) {
        const output = document.createElement('div');
        output.className = `cmd-output cmd-output--tree ${type}`;
        output.innerHTML = `<pre>${escapeHtml(message)}</pre>`;
        insertOutput(output);
    }

    function renderHtmlOutput(message, type) {
        const output = document.createElement('div');
        output.className = `cmd-output cmd-output--html ${type}`;
        output.innerHTML = sanitizeHtml(message);
        insertOutput(output);
    }

    /**
     * Render data as an interactive table with resizable columns and pagination
     */
    function renderTableOutput(message, type, data) {
        showCommandOutput(message, type);

        var validation = validateTablePayload(data);
        if (!validation.valid) {
            console.error('[Table render] ' + validation.error, { data: data });
            showCommandOutput(validation.error, 'error');
            return;
        }
        if (data.rows.length === 0) {
            return;
        }

        const output = document.createElement('div');
        output.className = 'cmd-output cmd-output--table';
        
        // Table container for horizontal scroll
        const tableContainer = document.createElement('div');
        tableContainer.className = 'table-container';
        
        // Create table
        const table = document.createElement('table');
        table.className = 'data-table';
        
        // Header row
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        
        data.columns.forEach((col, index) => {
            const th = document.createElement('th');
            th.textContent = col;
            th.setAttribute('data-col-index', index);
            
            // Add resize handle
            const resizer = document.createElement('div');
            resizer.className = 'col-resizer';
            resizer.addEventListener('mousedown', (e) => {
                e.preventDefault();
                initColumnResize(e, th, table);
            });
            th.appendChild(resizer);
            
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);
        
        // Body rows
        const tbody = document.createElement('tbody');
        const pageSize = data.page_size || data.limit || 100;
        const currentPage = data.page || 1;
        const totalRows = data.rows.length;
        const startIndex = 0;  // Already paginated from server
        const endIndex = totalRows;
        
        for (let i = startIndex; i < endIndex; i++) {
            const row = data.rows[i];
            const tr = document.createElement('tr');
            
            data.columns.forEach((col, colIndex) => {
                const td = document.createElement('td');
                const value = row[col] !== undefined ? row[col] : row[colIndex];
                
                if (value === null) {
                    td.innerHTML = '<span class="null-value">NULL</span>';
                } else if (typeof value === 'boolean') {
                    td.innerHTML = value ? '<span class="bool-true">true</span>' : '<span class="bool-false">false</span>';
                } else if (typeof value === 'number') {
                    td.className = 'cell-number';
                    td.textContent = value;
                } else {
                    td.textContent = String(value);
                }
                
                tr.appendChild(td);
            });
            
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        
        tableContainer.appendChild(table);
        output.appendChild(tableContainer);
        
        // Footer with info and pagination
        const footer = document.createElement('div');
        footer.className = 'table-footer';
        
        // Row count info
        const info = document.createElement('span');
        info.className = 'table-info';
        info.textContent = `Showing ${totalRows} row${totalRows !== 1 ? 's' : ''}`;
        if (data.execution_time_ms) {
            info.textContent += ` (${data.execution_time_ms}ms)`;
        }
        footer.appendChild(info);
        
        // Download CSV button
        const csvBtn = document.createElement('button');
        csvBtn.className = 'table-copy-btn table-export-btn';
        csvBtn.innerHTML = '📋 CSV';
        csvBtn.title = 'Download as CSV';
        csvBtn.addEventListener('click', () => {
            downloadTableData(data.columns, data.rows, 'csv', csvBtn);
        });
        footer.appendChild(csvBtn);
        
        // Download JSON button
        const jsonBtn = document.createElement('button');
        jsonBtn.className = 'table-copy-btn table-export-btn';
        jsonBtn.innerHTML = '{ } JSON';
        jsonBtn.title = 'Download as JSON';
        jsonBtn.addEventListener('click', () => {
            downloadTableData(data.columns, data.rows, 'json', jsonBtn);
        });
        footer.appendChild(jsonBtn);
        
        // Download Excel button
        const excelBtn = document.createElement('button');
        excelBtn.className = 'table-copy-btn table-export-btn table-excel-btn';
        excelBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8 17l2-4-2-4h1.5l1.25 2.5L12 9h1.5l-2 4 2 4H12l-1.25-2.5L9.5 17H8z"/></svg> Excel';
        excelBtn.title = 'Download as Excel';
        excelBtn.addEventListener('click', () => {
            downloadTableData(data.columns, data.rows, 'excel', excelBtn);
        });
        footer.appendChild(excelBtn);
        
        output.appendChild(footer);
        insertOutput(output);
    }
    
    /**
     * Convert table data to CSV string
     */
    function tableToCSV(columns, rows) {
        const escape = (val) => {
            if (val === null || val === undefined) return '';
            const str = String(val);
            if (str.includes(',') || str.includes('"') || str.includes('\n')) {
                return '"' + str.replace(/"/g, '""') + '"';
            }
            return str;
        };
        
        const header = columns.map(escape).join(',');
        const body = rows.map(row => {
            return columns.map(col => escape(row[col] !== undefined ? row[col] : '')).join(',');
        }).join('\n');
        
        return header + '\n' + body;
    }
    
    /**
     * Download table data via backend export API (CSV, Excel, JSON).
     */
    async function downloadTableData(columns, rows, format, btn) {
        const originalText = btn.innerHTML;
        btn.innerHTML = '⏳ ...';
        btn.disabled = true;
        
        const defaultFilenames = { csv: 'export.csv', excel: 'export.xlsx', json: 'export.json' };
        
        try {
            const response = await fetch('/api/console/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    columns: columns,
                    rows: rows,
                    format: format
                })
            });
            
            if (!response.ok) {
                throw new Error('Export failed');
            }
            
            const result = await response.json();
            
            if (result.success && result.download_url) {
                const link = document.createElement('a');
                link.href = result.download_url.startsWith('/') ? result.download_url : '/api/' + result.download_url;
                link.download = result.filename || defaultFilenames[format] || 'export';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                
                btn.innerHTML = '✅ Done';
                setTimeout(() => { btn.innerHTML = originalText; }, 2000);
            } else {
                throw new Error(result.error || 'Export failed');
            }
        } catch (error) {
            console.error('Export error:', error);
            btn.innerHTML = '❌ Error';
            setTimeout(() => { btn.innerHTML = originalText; }, 2000);
        } finally {
            btn.disabled = false;
        }
    }
    
    /**
     * Initialize column resize drag
     */
    function initColumnResize(e, th, table) {
        e.preventDefault();
        e.stopPropagation();
        
        const startX = e.clientX;
        const startWidth = th.getBoundingClientRect().width;
        const colIndex = parseInt(th.getAttribute('data-col-index'));
        
        // Add resizing class to body
        document.body.classList.add('resizing-column');
        th.classList.add('resizing');
        
        function onMouseMove(e) {
            e.preventDefault();
            const diff = e.clientX - startX;
            const newWidth = Math.max(50, startWidth + diff);
            th.style.width = newWidth + 'px';
            th.style.minWidth = newWidth + 'px';
            th.style.maxWidth = newWidth + 'px';
            
            // Also resize all cells in this column
            const cells = table.querySelectorAll(`tbody td:nth-child(${colIndex + 1})`);
            cells.forEach(cell => {
                cell.style.width = newWidth + 'px';
                cell.style.minWidth = newWidth + 'px';
                cell.style.maxWidth = newWidth + 'px';
            });
        }
        
        function onMouseUp(e) {
            e.preventDefault();
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            document.body.classList.remove('resizing-column');
            th.classList.remove('resizing');
        }
        
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    }

    /* ==========================================================================
       Chart Output - Dynamic charts (bar, pie, line, etc.)
       ========================================================================== */
    
    /**
     * Render interactive chart with dynamic controls
     * @param {string} message - Chart title/description
     * @param {string} type - Output type
     * @param {object} data - Chart data: { type, labels, datasets, options }
     */
    function renderChartOutput(message, type, data) {
        if (!data) return;
        
        const output = document.createElement('div');
        output.className = 'cmd-output cmd-output--chart';
        
        // Chart header
        const header = document.createElement('div');
        header.className = 'chart-header';
        header.innerHTML = `
            <span class="chart-title">${escapeHtml(message || 'Chart')}</span>
            <div class="chart-controls">
                <select class="chart-type-select">
                    <option value="bar" ${data.type === 'bar' ? 'selected' : ''}>📊 Bar</option>
                    <option value="line" ${data.type === 'line' ? 'selected' : ''}>📈 Line</option>
                    <option value="pie" ${data.type === 'pie' ? 'selected' : ''}>🥧 Pie</option>
                    <option value="doughnut" ${data.type === 'doughnut' ? 'selected' : ''}>🍩 Doughnut</option>
                </select>
            </div>
        `;
        output.appendChild(header);
        
        // Chart canvas container
        const chartContainer = document.createElement('div');
        chartContainer.className = 'chart-canvas-container';
        
        // Use simple SVG-based chart rendering (no external libs)
        const chartSvg = createSimpleChart(data);
        chartContainer.appendChild(chartSvg);
        output.appendChild(chartContainer);
        
        // Chart legend
        if (data.labels && data.datasets) {
            const legend = createChartLegend(data);
            output.appendChild(legend);
        }
        
        // Type change handler
        const typeSelect = header.querySelector('.chart-type-select');
        typeSelect.addEventListener('change', () => {
            const newType = typeSelect.value;
            data.type = newType;
            chartContainer.innerHTML = '';
            chartContainer.appendChild(createSimpleChart(data));
        });
        
        insertOutput(output);
    }
    
    /**
     * Create simple SVG chart
     */
    function createSimpleChart(data) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 400 250');
        svg.setAttribute('class', 'chart-svg');
        
        const labels = data.labels || [];
        const values = data.datasets?.[0]?.data || data.values || [];
        const colors = data.datasets?.[0]?.backgroundColor || generateColors(values.length);
        const chartType = data.type || 'bar';
        
        if (chartType === 'bar') {
            renderBarChart(svg, labels, values, colors);
        } else if (chartType === 'line') {
            renderLineChart(svg, labels, values, colors);
        } else if (chartType === 'pie' || chartType === 'doughnut') {
            renderPieChart(svg, labels, values, colors, chartType === 'doughnut');
        }
        
        return svg;
    }
    
    function renderBarChart(svg, labels, values, colors) {
        const maxVal = Math.max(...values, 1);
        const barWidth = 300 / Math.max(values.length, 1);
        const padding = 50;
        
        // Y axis
        const yAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        yAxis.setAttribute('x1', padding);
        yAxis.setAttribute('y1', 20);
        yAxis.setAttribute('x2', padding);
        yAxis.setAttribute('y2', 200);
        yAxis.setAttribute('stroke', 'var(--log-debug)');
        svg.appendChild(yAxis);
        
        // X axis
        const xAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        xAxis.setAttribute('x1', padding);
        xAxis.setAttribute('y1', 200);
        xAxis.setAttribute('x2', 380);
        xAxis.setAttribute('y2', 200);
        xAxis.setAttribute('stroke', 'var(--log-debug)');
        svg.appendChild(xAxis);
        
        // Bars
        values.forEach((val, i) => {
            const barHeight = (val / maxVal) * 170;
            const x = padding + 10 + i * barWidth;
            const y = 200 - barHeight;
            
            const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            rect.setAttribute('x', x);
            rect.setAttribute('y', y);
            rect.setAttribute('width', barWidth - 8);
            rect.setAttribute('height', barHeight);
            rect.setAttribute('fill', colors[i % colors.length]);
            rect.setAttribute('rx', '3');
            svg.appendChild(rect);
            
            // Value label
            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', x + (barWidth - 8) / 2);
            text.setAttribute('y', y - 5);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('fill', 'var(--term-fg)');
            text.setAttribute('font-size', '10');
            text.textContent = val;
            svg.appendChild(text);
            
            // Label
            const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            label.setAttribute('x', x + (barWidth - 8) / 2);
            label.setAttribute('y', 215);
            label.setAttribute('text-anchor', 'middle');
            label.setAttribute('fill', 'var(--log-debug)');
            label.setAttribute('font-size', '9');
            label.textContent = labels[i] || '';
            svg.appendChild(label);
        });
    }
    
    function renderLineChart(svg, labels, values, colors) {
        const maxVal = Math.max(...values, 1);
        const width = 300;
        const height = 170;
        const padding = 50;
        
        // Axes
        const yAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        yAxis.setAttribute('x1', padding);
        yAxis.setAttribute('y1', 20);
        yAxis.setAttribute('x2', padding);
        yAxis.setAttribute('y2', 200);
        yAxis.setAttribute('stroke', 'var(--log-debug)');
        svg.appendChild(yAxis);
        
        const xAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        xAxis.setAttribute('x1', padding);
        xAxis.setAttribute('y1', 200);
        xAxis.setAttribute('x2', 380);
        xAxis.setAttribute('y2', 200);
        xAxis.setAttribute('stroke', 'var(--log-debug)');
        svg.appendChild(xAxis);
        
        // Line
        const points = values.map((val, i) => {
            const x = padding + 10 + (i * width / Math.max(values.length - 1, 1));
            const y = 200 - (val / maxVal) * height;
            return `${x},${y}`;
        }).join(' ');
        
        const polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        polyline.setAttribute('points', points);
        polyline.setAttribute('fill', 'none');
        polyline.setAttribute('stroke', colors[0] || 'var(--accent)');
        polyline.setAttribute('stroke-width', '2');
        svg.appendChild(polyline);
        
        // Points
        values.forEach((val, i) => {
            const x = padding + 10 + (i * width / Math.max(values.length - 1, 1));
            const y = 200 - (val / maxVal) * height;
            
            const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            circle.setAttribute('cx', x);
            circle.setAttribute('cy', y);
            circle.setAttribute('r', '4');
            circle.setAttribute('fill', colors[0] || 'var(--accent)');
            svg.appendChild(circle);
        });
    }
    
    function renderPieChart(svg, labels, values, colors, isDoughnut) {
        const total = values.reduce((a, b) => a + b, 0) || 1;
        const cx = 200;
        const cy = 110;
        const r = 80;
        const innerR = isDoughnut ? 40 : 0;
        
        let startAngle = -Math.PI / 2;
        
        values.forEach((val, i) => {
            const sliceAngle = (val / total) * 2 * Math.PI;
            const endAngle = startAngle + sliceAngle;
            
            const x1 = cx + r * Math.cos(startAngle);
            const y1 = cy + r * Math.sin(startAngle);
            const x2 = cx + r * Math.cos(endAngle);
            const y2 = cy + r * Math.sin(endAngle);
            
            const largeArc = sliceAngle > Math.PI ? 1 : 0;
            
            let d;
            if (isDoughnut) {
                const ix1 = cx + innerR * Math.cos(startAngle);
                const iy1 = cy + innerR * Math.sin(startAngle);
                const ix2 = cx + innerR * Math.cos(endAngle);
                const iy2 = cy + innerR * Math.sin(endAngle);
                d = `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} L ${ix2} ${iy2} A ${innerR} ${innerR} 0 ${largeArc} 0 ${ix1} ${iy1} Z`;
            } else {
                d = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
            }
            
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', d);
            path.setAttribute('fill', colors[i % colors.length]);
            path.setAttribute('stroke', 'rgba(0,0,0,0.2)');
            path.setAttribute('stroke-width', '1');
            svg.appendChild(path);
            
            startAngle = endAngle;
        });
    }
    
    function createChartLegend(data) {
        const legend = document.createElement('div');
        legend.className = 'chart-legend';
        
        const labels = data.labels || [];
        const colors = data.datasets?.[0]?.backgroundColor || generateColors(labels.length);
        
        labels.forEach((label, i) => {
            const item = document.createElement('span');
            item.className = 'legend-item';
            item.innerHTML = `<span class="legend-color" style="background:${colors[i % colors.length]}"></span>${escapeHtml(label)}`;
            legend.appendChild(item);
        });
        
        return legend;
    }
    
    function generateColors(count) {
        const palette = [
            '#4dc9f6', '#f67019', '#f53794', '#537bc4', '#acc236',
            '#166a8f', '#00a950', '#58595b', '#8549ba', '#ff6384'
        ];
        return Array.from({length: count}, (_, i) => palette[i % palette.length]);
    }

    /* ==========================================================================
       Download Output - Styled download link with file icon
       ========================================================================== */
    
    /**
     * Render styled download link with dynamic file icon
     * @param {string} message - Download description
     * @param {string} type - Output type
     * @param {object} data - { url, filename, size, mime_type }
     */
    function renderDownloadOutput(message, type, data) {
        if (!data || !data.url) return;
        
        const output = document.createElement('div');
        output.className = 'cmd-output cmd-output--download';
        
        const filename = data.filename || data.url.split('/').pop() || 'download';
        const ext = filename.split('.').pop().toLowerCase();
        const icon = getFileIcon(ext);
        const sizeStr = data.size ? formatFileSize(data.size) : '';
        
        output.innerHTML = `
            <a href="${escapeHtml(data.url)}" class="download-link" download="${escapeHtml(filename)}" target="_blank">
                <span class="download-icon">${icon}</span>
                <div class="download-info">
                    <span class="download-filename">${escapeHtml(filename)}</span>
                    ${sizeStr ? `<span class="download-size">${sizeStr}</span>` : ''}
                    ${message ? `<span class="download-desc">${escapeHtml(message)}</span>` : ''}
                </div>
                <span class="download-action">⬇️ Download</span>
            </a>
        `;
        
        insertOutput(output);
    }
    
    /**
     * Get emoji icon based on file extension
     */
    function getFileIcon(ext) {
        const icons = {
            // Documents
            'pdf': '📕',
            'doc': '📘', 'docx': '📘',
            'xls': '📗', 'xlsx': '📗',
            'ppt': '📙', 'pptx': '📙',
            'txt': '📄',
            'md': '📝',
            'csv': '📊',
            // Code
            'js': '🟨', 'ts': '🟦',
            'py': '🐍',
            'html': '🌐', 'css': '🎨',
            'json': '{ }',
            'xml': '📋',
            'sql': '🗃️',
            // Images
            'jpg': '🖼️', 'jpeg': '🖼️', 'png': '🖼️', 'gif': '🖼️', 'svg': '🖼️', 'webp': '🖼️',
            // Archives
            'zip': '📦', 'rar': '📦', 'tar': '📦', 'gz': '📦', '7z': '📦',
            // Media
            'mp3': '🎵', 'wav': '🎵', 'ogg': '🎵',
            'mp4': '🎬', 'avi': '🎬', 'mov': '🎬', 'mkv': '🎬',
            // Data
            'db': '💾', 'sqlite': '💾',
            // Default
            'default': '📁'
        };
        return icons[ext] || icons['default'];
    }
    
    /**
     * Format file size in human readable format
     */
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function renderCodeOutput(message, type, data) {
        const output = document.createElement('div');
        output.className = `cmd-output cmd-output--code ${type}`;
        const lang = data?.language || 'plaintext';
        output.innerHTML = `<pre class="code-block" data-lang="${escapeHtml(lang)}">${escapeHtml(message)}</pre>`;
        insertOutput(output);
    }

    function renderProgressOutput(message, type) {
        const output = document.createElement('div');
        output.className = `cmd-output cmd-output--progress ${type}`;
        output.innerHTML = `<span class="progress-spinner"></span><span class="progress-message">${escapeHtml(message)}</span>`;
        insertOutput(output);
        state.progressElements.push(output);
    }

    function renderTreeOutput(message, type, data) {
        const output = document.createElement('div');
        output.className = `cmd-output cmd-output--tree ${type}`;
        output.innerHTML = `<pre>${escapeHtml(message)}</pre>`;
        insertOutput(output);
    }

    function clearProgressIndicators() {
        state.progressElements.forEach(el => {
            if (el && el.parentNode) {
                el.parentNode.removeChild(el);
            }
        });
        state.progressElements = [];
        
        if (dom.splitOutput) {
            const splitProgress = dom.splitOutput.querySelectorAll('.cmd-output--progress');
            splitProgress.forEach(el => el.remove());
        }
    }

    function insertOutputPanel(element) {
        if (!dom.outputPanel) return;
        dom.outputPanel.appendChild(element);
        if (dom.outputEmpty) dom.outputEmpty.style.display = 'none';
        dom.outputPanel.scrollTop = dom.outputPanel.scrollHeight;
    }

    function clearOutputPanel() {
        if (typeof window.__workspaceClearActiveExecutionBody === 'function') {
            window.__workspaceClearActiveExecutionBody();
        }
        var body = document.getElementById('workspace-execution-body');
        if (body && body.tagName === 'TEXTAREA') {
            body.value = '';
        }
        var htmlPrev = document.getElementById('workspace-execution-html-preview');
        if (htmlPrev) {
            htmlPrev.innerHTML = '';
            htmlPrev.hidden = true;
        }
        if (body) body.classList.remove('execution-doc-editor--half');
        if (!dom.outputPanel) return;
        var empty = dom.outputEmpty;
        dom.outputPanel.innerHTML = '';
        if (empty) {
            dom.outputPanel.appendChild(empty);
            empty.style.display = 'block';
        }
    }

    /**
     * Validate that `data` is compatible with `format`.
     * Returns { valid: bool, reason: string }.
     */
    /**
     * Render node execution output into the Output panel (or fall back to the terminal).
     * Resolution of output_format and data extraction from NodeExecutionResult is handled
     * centrally by resolveRenderPayload inside renderConsoleOutput.
     */
    function renderOutputPanel(message, type, format, data) {
        if (typeof window.__workspaceOpenExecutionResult === 'function') {
            window.__workspaceOpenExecutionResult({
                message: message,
                outputType: type,
                format: format,
                data: data,
            });
            return;
        }
        state._renderTarget = 'output';
        renderConsoleOutput(message, type, format, data);
    }

    function insertOutput(element) {
        if (state._renderTarget === 'output') {
            state._renderTarget = null;
            if (dom.outputPanel) {
                insertOutputPanel(element);
                return;
            }
            // Output panel not available: fall through to main console
        }
        if (state.currentOutputContainer) {
            state.currentOutputContainer.appendChild(element);
            if (state.currentOutputContainerSplit) {
                const splitElement = element.cloneNode(true);
                reattachEventListeners(splitElement);
                state.currentOutputContainerSplit.appendChild(splitElement);
            }
        } else if (state.currentPrompt) {
            dom.output.insertBefore(element, state.currentPrompt);
        } else {
            dom.output.appendChild(element);
        }
        if (dom.splitOutput && !state.currentOutputContainerSplit) {
            const splitElement = element.cloneNode(true);
            reattachEventListeners(splitElement);
            if (state.splitPrompt) {
                dom.splitOutput.insertBefore(splitElement, state.splitPrompt);
            } else {
                dom.splitOutput.appendChild(splitElement);
            }
            if (state.autoScroll) dom.splitOutput.scrollTop = dom.splitOutput.scrollHeight;
        }
        
        if (state.autoScroll) {
            scrollToBottom();
        }
    }
    
    /**
     * Wire expand/collapse toggles on command blocks (e.g. after session restore from HTML).
     */
    function wireCommandBlockToggles(root) {
        if (!root || !root.querySelectorAll) return;
        root.querySelectorAll('.command-block').forEach(function(block) {
            const line = block.querySelector(':scope > .command-block-line');
            const toggle = line && line.querySelector('.cmd-toggle');
            const output = block.querySelector(':scope > .command-output-container');
            if (!toggle || !output) return;
            toggle.addEventListener('click', function(e) {
                e.stopPropagation();
                const expanded = output.style.display !== 'none' && output.style.display !== '';
                output.style.display = expanded ? 'none' : 'block';
                toggle.textContent = expanded ? '\u25B6' : '\u25BC';
                toggle.classList.toggle('expanded', !expanded);
            });
        });
    }

    function collectTerminalChildrenHTML(outputEl) {
        if (!outputEl) return '';
        const parts = [];
        Array.from(outputEl.children).forEach(function(child) {
            if (child.id === 'console-empty') return;
            if (child.classList.contains('cmd-line') && child.querySelector('input.cmd-input')) return;
            parts.push(child.outerHTML);
        });
        return parts.join('');
    }

    function clearTerminalStaticContent(outputEl) {
        if (!outputEl) return;
        Array.from(outputEl.children).forEach(function(child) {
            if (child.id === 'console-empty') return;
            child.remove();
        });
    }

    function injectTerminalHTML(outputEl, html) {
        if (!outputEl) return;
        clearTerminalStaticContent(outputEl);
        if (html && String(html).trim()) {
            if (dom.empty) dom.empty.style.display = 'none';
            const wrap = document.createElement('div');
            wrap.innerHTML = html;
            while (wrap.firstChild) {
                outputEl.appendChild(wrap.firstChild);
            }
            reattachEventListeners(outputEl);
            wireCommandBlockToggles(outputEl);
        } else if (dom.empty && !outputEl.querySelector('.log-entry, .command-block, .console-ready-message')) {
            dom.empty.style.display = '';
        }
    }

    function serializeTerminalForSession() {
        return {
            main_html: collectTerminalChildrenHTML(dom.output),
            split_html: dom.splitOutput ? collectTerminalChildrenHTML(dom.splitOutput) : '',
            command_history: state.cmdHistory.slice()
        };
    }

    function restoreTerminalFromSession(t) {
        if (!t || typeof t !== 'object') return;
        if (state.currentPrompt) {
            state.currentPrompt.remove();
            state.currentPrompt = null;
        }
        if (state.splitPrompt) {
            state.splitPrompt.remove();
            state.splitPrompt = null;
        }
        state.currentOutputContainer = null;
        state.currentOutputContainerSplit = null;

        injectTerminalHTML(dom.output, t.main_html || '');
        if (dom.splitOutput) {
            dom.splitOutput.innerHTML = '';
            if (t.split_html && String(t.split_html).trim()) {
                injectTerminalHTML(dom.splitOutput, t.split_html);
            } else {
                syncConsoleToSplit();
            }
        }

        state.cmdHistory = Array.isArray(t.command_history) ? t.command_history.slice() : [];
        state.cmdHistoryIndex = -1;

        if (state.connected) {
            createPrompt();
        }
    }

    /**
     * Re-attach event listeners to cloned elements for split view
     */
    function reattachEventListeners(element) {
        // Log entry toggle (CUSTOM etc. - expand/collapse details)
        element.querySelectorAll('.log-entry .log-toggle').forEach(toggle => {
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const entry = toggle.closest('.log-entry');
                if (entry) {
                    entry.classList.toggle('expanded');
                    toggle.textContent = entry.classList.contains('expanded') ? '▼' : '▶';
                    toggle.title = entry.classList.contains('expanded') ? 'Hide JSON payload' : 'Show full JSON payload';
                }
            });
        });

        // Section toggle headers
        element.querySelectorAll('.section-header').forEach(header => {
            header.addEventListener('click', () => {
                const toggle = header.querySelector('.section-toggle');
                if (toggle) {
                    const expanded = toggle.textContent === '▼';
                    toggle.textContent = expanded ? '▶' : '▼';
                    const content = header.nextElementSibling;
                    if (content && content.classList.contains('section-content')) {
                        content.style.display = expanded ? 'none' : 'block';
                    }
                    header.classList.toggle('section-header--active', !expanded);
                }
            });
        });
        
        // JSON tree toggle nodes (for navigable tree)
        element.querySelectorAll('.json-tree-toggle').forEach(toggle => {
            if (toggle.textContent.trim() !== '') {
                toggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const node = toggle.closest('.json-tree-node');
                    if (node) {
                        const children = node.querySelector('.json-tree-children');
                        if (children) {
                            const isExpanded = toggle.classList.toggle('expanded');
                            toggle.textContent = isExpanded ? '▼' : '▶';
                            children.style.display = isExpanded ? 'block' : 'none';
                        }
                    }
                });
            }
        });
        
        // Form section headers (State/Params togglers)
        element.querySelectorAll('.form-section-header').forEach(header => {
            header.addEventListener('click', () => {
                const toggle = header.querySelector('.section-toggle');
                if (toggle) {
                    const expanded = toggle.classList.toggle('expanded');
                    toggle.textContent = expanded ? '▼' : '▶';
                    const content = header.nextElementSibling;
                    if (content && content.classList.contains('form-section-content')) {
                        content.style.display = expanded ? 'flex' : 'none';
                    }
                }
            });
        });
        
        // Table column resizers
        element.querySelectorAll('.col-resizer').forEach(resizer => {
            const th = resizer.closest('th');
            const table = resizer.closest('table');
            if (th && table) {
                resizer.addEventListener('mousedown', (e) => {
                    e.stopPropagation();
                    initColumnResize(e, th, table);
                });
            }
        });
        
        // Table column drag & drop
        element.querySelectorAll('.data-table th[draggable="true"]').forEach(th => {
            const table = th.closest('table');
            const colIndex = parseInt(th.getAttribute('data-col-index'));
            
            th.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', colIndex);
                th.classList.add('dragging');
            });
            th.addEventListener('dragend', () => {
                th.classList.remove('dragging');
            });
            th.addEventListener('dragover', (e) => {
                e.preventDefault();
                th.classList.add('drag-over');
            });
            th.addEventListener('dragleave', () => {
                th.classList.remove('drag-over');
            });
            th.addEventListener('drop', (e) => {
                e.preventDefault();
                th.classList.remove('drag-over');
                const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
                const toIndex = colIndex;
                if (fromIndex !== toIndex && table) {
                    // Simple column reorder for cloned table
                    reorderClonedTableColumns(table, fromIndex, toIndex);
                }
            });
        });
        
        // Table download/export buttons
        element.querySelectorAll('.table-export-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const tableContainer = btn.closest('.cmd-output-wrapper') || btn.closest('.output-section--render');
                const table = tableContainer?.querySelector('.data-table');
                if (table) {
                    const data = extractTableData(table);
                    const btnText = btn.textContent || '';
                    let format = 'csv';
                    if (btnText.includes('Excel') || btn.classList.contains('table-excel-btn')) format = 'excel';
                    else if (btnText.includes('JSON')) format = 'json';
                    downloadTableData(data.columns, data.rows, format, btn);
                }
            });
        });
        
        // Chart type selector
        element.querySelectorAll('.chart-type-select').forEach(select => {
            const chartContainer = select.closest('.output-section--render')?.querySelector('.chart-canvas-container');
            if (chartContainer) {
                select.addEventListener('change', () => {
                    // Chart type change not fully functional in clone - would need data
                });
            }
        });
        
        // Form buttons - fully functional in split view
        element.querySelectorAll('.interactive-form').forEach(form => {
            const requestId = form.getAttribute('data-request-id');
            
            const sendBtn = form.querySelector('.form-send-btn');
            const cancelBtn = form.querySelector('.form-cancel-btn');
            
            if (sendBtn) {
                sendBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleFormSubmit(requestId, form, false);
                });
            }
            
            if (cancelBtn) {
                cancelBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleFormSubmit(requestId, form, true);
                });
            }
        });
    }
    
    /**
     * Reorder columns in a cloned table (simplified version without data reference)
     */
    function reorderClonedTableColumns(table, fromIndex, toIndex) {
        // Reorder header cells
        const headerRow = table.querySelector('thead tr');
        if (headerRow) {
            const headerCells = Array.from(headerRow.children);
            const [movedHeader] = headerCells.splice(fromIndex, 1);
            headerCells.splice(toIndex, 0, movedHeader);
            headerRow.innerHTML = '';
            headerCells.forEach((cell, i) => {
                cell.setAttribute('data-col-index', i);
                headerRow.appendChild(cell);
            });
        }
        
        // Reorder body cells
        table.querySelectorAll('tbody tr').forEach(row => {
            const cells = Array.from(row.children);
            const [movedCell] = cells.splice(fromIndex, 1);
            cells.splice(toIndex, 0, movedCell);
            row.innerHTML = '';
            cells.forEach(cell => row.appendChild(cell));
        });
    }
    
    /**
     * Handle form submit from any panel (main or split)
     * Disables ALL forms with same request_id to prevent duplicates.
     * File fields are uploaded via HTTP first (with progress bar), then form sends upload_id(s).
     */
    async function handleFormSubmit(requestId, sourceForm, isCancelled) {
        if (!requestId) {
            console.warn('handleFormSubmit: no requestId provided');
            return;
        }
        
        // Validate JSON fields before submit (block Send if invalid)
        if (!isCancelled) {
            const validation = validateFormJsonFields(sourceForm);
            if (!validation.valid) {
                sourceForm.querySelectorAll('.field-error').forEach(el => el.classList.remove('field-error'));
                const prevErr = sourceForm.querySelector('.form-validation-error');
                if (prevErr) prevErr.remove();
                const first = validation.errors[0];
                const inputEl = sourceForm.querySelector(`[data-field-name="${first.field}"][data-section="${first.section}"]`);
                if (inputEl) {
                    inputEl.classList.add('field-error');
                    inputEl.focus();
                    inputEl.title = first.message;
                }
                const errMsg = document.createElement('div');
                errMsg.className = 'form-validation-error';
                errMsg.textContent = `${first.field}: ${first.message}`;
                sourceForm.insertBefore(errMsg, sourceForm.firstChild);
                return;
            }
        }
        
        // Find ALL forms with this request_id in both main and split panels
        const allForms = document.querySelectorAll(`.interactive-form[data-request-id="${requestId}"]`);
        const hasFileUploads = !isCancelled && sourceForm.querySelectorAll('input[type="file"][data-field-name]').length > 0 &&
            Array.from(sourceForm.querySelectorAll('input[type="file"]')).some(function (inp) { return inp.files && inp.files.length > 0; });

        // Show "Uploading..." during file upload
        if (hasFileUploads) {
            allForms.forEach(function (form) {
                const sendBtn = form.querySelector('.form-send-btn');
                if (sendBtn) {
                    sendBtn.disabled = true;
                    sendBtn.innerHTML = '<span class="send-icon">⏳</span> Uploading...';
                }
            });
        }

        let formData;
        try {
            formData = isCancelled ? { cancelled: true } : await collectFormDataWithFileUploads(sourceForm);
        } catch (err) {
            console.error('handleFormSubmit: collect/upload failed', err);
            allForms.forEach(function (form) {
                const sendBtn = form.querySelector('.form-send-btn');
                if (sendBtn) {
                    sendBtn.disabled = false;
                    sendBtn.innerHTML = '<span class="send-icon">✓</span> Send';
                }
            });
            const prevErr = sourceForm.querySelector('.form-validation-error');
            if (prevErr) prevErr.remove();
            const errMsg = document.createElement('div');
            errMsg.className = 'form-validation-error';
            errMsg.textContent = 'Upload failed: ' + (err && err.message ? err.message : String(err));
            sourceForm.insertBefore(errMsg, sourceForm.firstChild);
            return;
        }
        
        console.log('handleFormSubmit:', { requestId, isCancelled, formData, formsFound: allForms.length });
        if (formData && formData.params && !isCancelled) {
            console.log('handleFormSubmit params being sent:', JSON.stringify(formData.params, null, 2));
        }
        
        // Disable all matching forms
        allForms.forEach(form => {
            const wrapper = form.closest('.execution-form-sheet-panel')
                || form.closest('.cmd-output-wrapper')
                || form.closest('.cmd-output--form');
            const sendBtn = form.querySelector('.form-send-btn');
            const cancelBtn = form.querySelector('.form-cancel-btn');
            
            if (sendBtn) {
                sendBtn.disabled = true;
                sendBtn.innerHTML = isCancelled 
                    ? '<span class="send-icon">✕</span> Cancelled'
                    : '<span class="send-icon">✓</span> Sent';
            }
            if (cancelBtn) {
                cancelBtn.disabled = true;
            }
            
            if (wrapper) {
                wrapper.classList.add(isCancelled ? 'form-cancelled' : 'form-submitted');
            }
        });
        
        // Emit socket event ONCE with correct field name 'response'
        if (state.socket && state.socket.connected) {
            state.socket.emit('execution_response', {
                request_id: requestId,
                response: formData  // Backend expects 'response', not 'data'
            });
            console.log('execution_response emitted for:', requestId);
            const sheet = sourceForm.closest('.execution-form-sheet');
            if (sheet) {
                closeExecutionFormSheet(sheet);
            }
        } else {
            console.warn('Socket not connected, cannot emit execution_response');
        }
    }
    
    /**
     * Extract data from table DOM for copy operations
     */
    function extractTableData(table) {
        const columns = [];
        const rows = [];
        
        table.querySelectorAll('thead th').forEach(th => {
            const label = th.querySelector('.col-label');
            columns.push(label ? label.textContent : th.textContent);
        });
        
        table.querySelectorAll('tbody tr').forEach(tr => {
            const row = {};
            tr.querySelectorAll('td').forEach((td, i) => {
                const nullSpan = td.querySelector('.null-value');
                const boolSpan = td.querySelector('.bool-true, .bool-false');
                if (nullSpan) {
                    row[columns[i]] = null;
                } else if (boolSpan) {
                    row[columns[i]] = boolSpan.classList.contains('bool-true');
                } else {
                    row[columns[i]] = td.textContent;
                }
            });
            rows.push(row);
        });
        
        return { columns, rows };
    }

    function syntaxHighlightJson(json) {
        return json
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, 
                function (match) {
                    let cls = 'json-number';
                    if (/^"/.test(match)) {
                        cls = /:$/.test(match) ? 'json-key' : 'json-string';
                    } else if (/true|false/.test(match)) {
                        cls = 'json-boolean';
                    } else if (/null/.test(match)) {
                        cls = 'json-null';
                    }
                    return '<span class="' + cls + '">' + match + '</span>';
                });
    }

    function sanitizeHtml(html) {
        const allowedTags = ['b', 'i', 'u', 'strong', 'em', 'span', 'br', 'p', 'a', 'code', 'pre'];
        const div = document.createElement('div');
        div.innerHTML = html;
        
        const walk = (node) => {
            const children = [...node.childNodes];
            children.forEach(child => {
                if (child.nodeType === 1) {
                    if (!allowedTags.includes(child.tagName.toLowerCase())) {
                        const text = document.createTextNode(child.textContent);
                        node.replaceChild(text, child);
                    } else {
                        [...child.attributes].forEach(attr => {
                            if (attr.name.startsWith('on') || attr.name === 'style') {
                                child.removeAttribute(attr.name);
                            }
                            if (attr.name === 'href' && !attr.value.startsWith('http')) {
                                child.removeAttribute(attr.name);
                            }
                        });
                        walk(child);
                    }
                }
            });
        };
        walk(div);
        return div.innerHTML;
    }

    function executeCommand(cmd, savePayload) {
        var parts = cmd.split(/\s+/);
        var command = parts[0].toLowerCase();

        if (command === 'save' && !savePayload) {
            var getPayload = window.HytheraConsole && window.HytheraConsole.getSavePayload;
            if (getPayload) {
                var result = getPayload();
                if (result.error) {
                    state.cmdHistory.push(cmd);
                    if (state.cmdHistory.length > 100) state.cmdHistory.shift();
                    showExecutedCommand(cmd);
                    if (state.currentPrompt) { state.currentPrompt.remove(); state.currentPrompt = null; }
                    if (state.splitPrompt) { state.splitPrompt.remove(); state.splitPrompt = null; }
                    showCommandOutput(result.error, 'error');
                    if (state.connected) createPrompt();
                    return;
                }
                if (result.payload) savePayload = result.payload;
            }
        }

        state.cmdHistory.push(cmd);
        if (state.cmdHistory.length > 100) {
            state.cmdHistory.shift();
        }
        showExecutedCommand(cmd);

        // Remove BOTH prompts (main and split)
        if (state.currentPrompt) {
            state.currentPrompt.remove();
            state.currentPrompt = null;
        }
        if (state.splitPrompt) {
            state.splitPrompt.remove();
            state.splitPrompt = null;
        }

        if (command === 'save' && savePayload) {
            var prepare = window.HytheraConsole && window.HytheraConsole.prepareSaveForSend;
            if (prepare) prepare();
        }

        if (command === 'history') {
            if (state.cmdHistory.length === 0) {
                showCommandOutput('No command history', 'info');
            } else {
                const historyText = state.cmdHistory
                    .map((c, i) => `  ${i + 1}. ${c}`)
                    .join('\n');
                showCommandOutput(`Command history:\n${historyText}`, 'info');
            }
            if (state.connected) createPrompt();
            return;
        }

        if (!state.connected) {
            showCommandOutput('Error: Not connected to server', 'error');
            createPrompt();  // Recreate prompt even on error
            return;
        }

        // Emit via Socket.IO
        if (state.socket) {
            const payload = { raw_command: cmd };
            if (savePayload) payload.save_payload = savePayload;
            state.socket.emit('console_command', payload);
        }
    }

    function updateConnectionStatus(connected) {
        state.connected = connected;
        if (dom.statusDot) dom.statusDot.classList.toggle('connected', connected);
        if (dom.statusText) dom.statusText.textContent = connected ? 'Connected' : 'Disconnected';
        if (dom.statusSessionId) {
            if (connected) {
                if (!state.fakeSessionId) {
                    state.fakeSessionId = Array.from(crypto.getRandomValues(new Uint8Array(4)))
                        .map(function (b) { return b.toString(16).padStart(2, '0'); }).join('');
                }
                dom.statusSessionId.textContent = ' · ' + state.fakeSessionId;
                dom.statusSessionId.setAttribute('aria-hidden', 'false');
            } else {
                dom.statusSessionId.textContent = '';
                dom.statusSessionId.setAttribute('aria-hidden', 'true');
            }
        }
    }

    function handleClear() {
        const entries = dom.output.querySelectorAll('.log-entry, .cmd-executed, .cmd-output, .cmd-line, .command-block');
        entries.forEach(e => e.remove());
        state.currentPrompt = null;
        state.splitPrompt = null;
        state.currentOutputContainer = null;
        state.currentOutputContainerSplit = null;
        
        if (dom.splitOutput) {
            dom.splitOutput.innerHTML = '';
        }
        
        state.eventCount = 0;
        
        if (!state.connected && dom.empty) {
            dom.empty.style.display = 'flex';
        }
        
        addSystemMessage('Console cleared', 'debug');
        
        if (state.connected) {
            createPrompt();
        }
    }

    function handleToggleScroll() {
        state.autoScroll = !state.autoScroll;
        dom.btnScroll.classList.toggle('active', state.autoScroll);
        dom.btnScroll.title = state.autoScroll ? 'Auto-scroll: ON' : 'Auto-scroll: OFF';
        
        if (state.autoScroll) {
            scrollToBottom();
        }
    }

    function handleReconnect() {
        addSystemMessage('Reconnecting...', 'info');
        window.dispatchEvent(new CustomEvent('console-reconnect'));
    }

    function syncConsoleToSplit() {
        if (!dom.splitOutput || !dom.output) return;
        
        dom.splitOutput.innerHTML = '';
        state.splitPrompt = null;
        
        // Clone top-level children only (so .command-block goes as a whole)
        Array.from(dom.output.children).forEach(function(entry) {
            if (entry.classList.contains('cmd-line') && entry.querySelector('input')) return;
            const clone = entry.cloneNode(true);
            reattachEventListeners(clone);
            dom.splitOutput.appendChild(clone);
        });
        
        if (state.connected && state.currentPrompt) {
            createSplitPrompt();
        }
        
        if (state.autoScroll) {
            dom.splitOutput.scrollTop = dom.splitOutput.scrollHeight;
        }
    }

    function init() {
        if (dom.btnClear) dom.btnClear.addEventListener('click', handleClear);
        if (dom.btnScroll) dom.btnScroll.addEventListener('click', handleToggleScroll);
        var btnClearOutput = document.getElementById('btn-clear-output');
        if (btnClearOutput) btnClearOutput.addEventListener('click', clearOutputPanel);

        window.addEventListener('menu-reconnect', handleReconnect);
        
        window.addEventListener('console-command', function(e) {
            if (e.detail && e.detail.command) {
                executeCommand(e.detail.command, e.detail.save_payload);
            }
        });
        
        function handleToggleClick(e) {
            const toggle = e.target.closest('.log-toggle');
            if (toggle) {
                e.stopPropagation();
                const entry = toggle.closest('.log-entry');
                if (entry) {
                    entry.classList.toggle('expanded');
                    toggle.textContent = entry.classList.contains('expanded') ? '▼' : '▶';
                    toggle.title = entry.classList.contains('expanded') ? 'Hide JSON payload' : 'Show full JSON payload';
                }
                return;
            }
            const headerToggle = e.target.closest('.output-header-toggle');
            if (headerToggle) {
                e.stopPropagation();
                const wrapper = headerToggle.closest('.cmd-output-wrapper');
                if (wrapper) {
                    const sectionsContainer = wrapper.querySelector('.output-sections');
                    if (sectionsContainer) {
                        const isExpanded = sectionsContainer.style.display !== 'none';
                        sectionsContainer.style.display = isExpanded ? 'none' : '';
                        headerToggle.textContent = isExpanded ? '▶' : '▼';
                    }
                }
            }
        }
        
        if (dom.output) {
            dom.output.addEventListener('click', handleToggleClick);
        }
        
        if (dom.splitOutput) {
            dom.splitOutput.addEventListener('click', handleToggleClick);
        }

        if (dom.splitBtnClear) {
            dom.splitBtnClear.addEventListener('click', handleClear);
        }
        if (dom.splitBtnScroll) {
            dom.splitBtnScroll.addEventListener('click', function() {
                handleToggleScroll();
                this.classList.toggle('active', state.autoScroll);
            });
        }

        function closeAllFilterDropdowns() {
            if (dom.filterDropdown) dom.filterDropdown.classList.remove('open');
            if (dom.splitFilterDropdown) dom.splitFilterDropdown.classList.remove('open');
        }

        function toggleFilterDropdown(dropdown, otherDropdown) {
            if (otherDropdown) otherDropdown.classList.remove('open');
            if (dropdown) dropdown.classList.toggle('open');
        }

        function syncFilterCheckboxes(sourceDropdown, targetDropdown) {
            if (!targetDropdown) return;
            Object.keys(state.filterLevels).forEach(function(level) {
                const checkbox = targetDropdown.querySelector(`input[data-level="${level}"]`);
                if (checkbox) checkbox.checked = state.filterLevels[level];
            });
        }

        function handleFilterChange(checkbox) {
            const level = checkbox.getAttribute('data-level');
            state.filterLevels[level] = checkbox.checked;
            applyLogFilters();
            localStorage.setItem('nos-log-filters', JSON.stringify(state.filterLevels));
            syncFilterCheckboxes(null, dom.filterDropdown);
            syncFilterCheckboxes(null, dom.splitFilterDropdown);
        }

        if (dom.btnFilter) {
            dom.btnFilter.addEventListener('click', function(e) {
                e.stopPropagation();
                toggleFilterDropdown(dom.filterDropdown, dom.splitFilterDropdown);
            });
        }

        if (dom.splitBtnFilter) {
            dom.splitBtnFilter.addEventListener('click', function(e) {
                e.stopPropagation();
                toggleFilterDropdown(dom.splitFilterDropdown, dom.filterDropdown);
            });
        }

        if (dom.filterDropdown) {
            dom.filterDropdown.querySelectorAll('input[type="checkbox"]').forEach(function(checkbox) {
                checkbox.addEventListener('change', function() {
                    handleFilterChange(this);
                });
            });
        }

        if (dom.splitFilterDropdown) {
            dom.splitFilterDropdown.querySelectorAll('input[type="checkbox"]').forEach(function(checkbox) {
                checkbox.addEventListener('change', function() {
                    handleFilterChange(this);
                });
            });
        }

        document.addEventListener('click', function(e) {
            const container = e.target.closest('.filter-dropdown-container');
            if (!container) {
                closeAllFilterDropdowns();
            }
        });

        const savedFilters = localStorage.getItem('nos-log-filters');
        if (savedFilters) {
            try {
                const filters = JSON.parse(savedFilters);
                Object.assign(state.filterLevels, filters);
                syncFilterCheckboxes(null, dom.filterDropdown);
                syncFilterCheckboxes(null, dom.splitFilterDropdown);
            } catch (e) {}
        }
        
        window.addEventListener('split-view-enabled', function() {
            syncConsoleToSplit();
        });

        addReadyMessage('nOS Engine Console ready. Type "help" and press Enter for commands.');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose API for console-socket.js
    window.HytheraConsole = {
        state: state,
        dom: dom,
        addLogEntry: addLogEntry,
        addSystemMessage: addSystemMessage,
        appendFormToLogEntry: appendFormToLogEntry,
        createPrompt: createPrompt,
        showCommandOutput: showCommandOutput,
        renderConsoleOutput: renderConsoleOutput,
        renderOutputPanel: renderOutputPanel,
        clearOutputPanel: clearOutputPanel,
        loadCreatedCodeIntoEditor: loadCreatedCodeIntoEditor,
        clearProgressIndicators: clearProgressIndicators,
        updateConnectionStatus: updateConnectionStatus,
        handleClear: handleClear,
        reattachEventListeners: reattachEventListeners,
        wireCommandBlockToggles: wireCommandBlockToggles,
        serializeTerminalForSession: serializeTerminalForSession,
        restoreTerminalFromSession: restoreTerminalFromSession
    };

})();

/* ==========================================================================
   Code Editor Application
   ========================================================================== */
