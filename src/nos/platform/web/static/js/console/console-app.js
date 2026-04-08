/**
 * nOS Console Application - Core Functionality
 * 
 * This file contains all the core UI logic for the console:
 * - Menu Bar management
 * - Explorer Panel (file tree & outline)
 * - Tab System
 * - Console rendering functions
 * - Code Editor management
 * 
 * Socket.IO event handling is in console-socket.js
 */

'use strict';

/* ==========================================================================
   IDE Menu Bar
   ========================================================================== */
(function() {
    'use strict';

    const menuState = {
        openMenu: null,
        currentTheme: 'nos-dark',
        autosaveEnabled: false,
        splitViewEnabled: false,
        compactViewEnabled: false
    };

    const themes = {
        'nos': {
            '--term-bg': '#1e1e2e',
            '--term-fg': '#cdd6f4',
            '--term-border': '#313244',
            '--term-selection': '#45475a',
            '--header-bg': '#11111b',
            '--header-fg': '#cdd6f4',
            '--log-info': '#89b4fa',
            '--log-debug': '#a6adc8',
            '--log-warning': '#f9e2af',
            '--log-error': '#f38ba8',
            '--log-success': '#a6e3a1'
        },
        'light': {
            '--term-bg': '#f5f5f7',
            '--term-fg': '#1d1d1f',
            '--term-border': '#d2d2d7',
            '--term-selection': '#d1e7ff',
            '--header-bg': '#e8e8ed',
            '--header-fg': '#1d1d1f',
            '--log-info': '#0066cc',
            '--log-debug': '#666666',
            '--log-warning': '#b58900',
            '--log-error': '#c53030',
            '--log-success': '#2aa198'
        }
    };

    function closeAllMenus() {
        document.querySelectorAll('.menu-item').forEach(function(item) {
            item.classList.remove('open');
        });
        menuState.openMenu = null;
    }
    window.closeAllMenus = closeAllMenus;

    function toggleMenu(menuItem) {
        const isOpen = menuItem.classList.contains('open');
        closeAllMenus();
        if (!isOpen) {
            menuItem.classList.add('open');
            menuState.openMenu = menuItem;
        }
    }

    function applyTheme(themeName) {
        const theme = themes[themeName];
        if (!theme) return;

        const root = document.documentElement;
        Object.keys(theme).forEach(function(prop) {
            root.style.setProperty(prop, theme[prop]);
        });

        document.body.classList.remove('theme-nos', 'theme-light');
        document.body.classList.add('theme-' + themeName);

        document.documentElement.setAttribute('data-theme', themeName);

        document.querySelectorAll('button.menu-option[data-theme]').forEach(function(btn) {
            btn.classList.toggle('active', btn.getAttribute('data-theme') === themeName);
        });

        menuState.currentTheme = themeName;
        localStorage.setItem('nos-theme', themeName);
    }

    function toggleCompactView() {
        menuState.compactViewEnabled = !menuState.compactViewEnabled;
        document.body.classList.toggle('compact-view', menuState.compactViewEnabled);
        const btn = document.getElementById('menu-compact-view');
        if (btn) {
            btn.classList.toggle('active', menuState.compactViewEnabled);
        }
        localStorage.setItem('nos-compact-view', menuState.compactViewEnabled);
    }

    function toggleAutosave() {
        menuState.autosaveEnabled = !menuState.autosaveEnabled;
        const btn = document.getElementById('menu-autosave');
        if (btn) {
            btn.classList.toggle('active', menuState.autosaveEnabled);
        }
        localStorage.setItem('nos-autosave', menuState.autosaveEnabled);
    }

    function toggleSplitView() {
        menuState.splitViewEnabled = !menuState.splitViewEnabled;
        document.body.classList.toggle('layout-split', menuState.splitViewEnabled);
        
        const btn = document.getElementById('menu-split-view');
        if (btn) {
            btn.classList.toggle('active', menuState.splitViewEnabled);
        }
        
        localStorage.setItem('nos-split-view', menuState.splitViewEnabled);
        
        if (menuState.splitViewEnabled) {
            initSplitResizer();
            restoreSplitRatio();
            syncContentToSplit();
        }
    }

    function initSplitResizer() {
        const resizer = document.getElementById('split-resizer');
        const leftPanel = document.getElementById('split-panel-console');
        const rightPanel = document.getElementById('split-panel-code');
        const container = document.getElementById('split-container');
        
        if (!resizer || !leftPanel || !rightPanel || !container) return;
        
        let isDragging = false;
        
        resizer.addEventListener('mousedown', function(e) {
            isDragging = true;
            resizer.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
        
        document.addEventListener('mousemove', function(e) {
            if (!isDragging) return;
            
            const containerRect = container.getBoundingClientRect();
            const containerWidth = containerRect.width;
            const offsetX = e.clientX - containerRect.left;
            
            let leftPercent = (offsetX / containerWidth) * 100;
            leftPercent = Math.max(15, Math.min(85, leftPercent));
            const rightPercent = 100 - leftPercent;
            
            leftPanel.style.flex = '0 0 ' + leftPercent + '%';
            rightPanel.style.flex = '0 0 ' + rightPercent + '%';
            
            localStorage.setItem('nos-split-ratio', leftPercent);
        });
        
        document.addEventListener('mouseup', function() {
            if (isDragging) {
                isDragging = false;
                resizer.classList.remove('dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    }

    function restoreSplitRatio() {
        const savedRatio = localStorage.getItem('nos-split-ratio');
        if (savedRatio) {
            const leftPercent = parseFloat(savedRatio);
            const rightPercent = 100 - leftPercent;
            const leftPanel = document.getElementById('split-panel-console');
            const rightPanel = document.getElementById('split-panel-code');
            
            if (leftPanel && rightPanel) {
                leftPanel.style.flex = '0 0 ' + leftPercent + '%';
                rightPanel.style.flex = '0 0 ' + rightPercent + '%';
            }
        }
    }

    function syncContentToSplit() {
        window.dispatchEvent(new CustomEvent('split-view-enabled'));
    }

    function init() {
        document.querySelectorAll('.menu-trigger').forEach(function(trigger) {
            trigger.addEventListener('click', function(e) {
                e.stopPropagation();
                if (trigger.id === 'menu-help') {
                    window.dispatchEvent(new CustomEvent('console-command', { detail: { command: 'help' } }));
                    return;
                }
                toggleMenu(trigger.parentElement);
            });
        });

        document.querySelectorAll('.menu-item').forEach(function(item) {
            item.addEventListener('mouseenter', function() {
                if (menuState.openMenu && menuState.openMenu !== item) {
                    closeAllMenus();
                    item.classList.add('open');
                    menuState.openMenu = item;
                }
            });
        });

        document.addEventListener('click', function(e) {
            if (!e.target.closest('.menu-item')) {
                closeAllMenus();
            }
        });

        const btnReconnect = document.getElementById('menu-reconnect');
        if (btnReconnect) {
            btnReconnect.addEventListener('click', function() {
                window.dispatchEvent(new CustomEvent('menu-reconnect'));
                closeAllMenus();
            });
        }

        const btnNewWindow = document.getElementById('menu-new-window');
        if (btnNewWindow) {
            btnNewWindow.addEventListener('click', function() {
                var u = btnNewWindow.getAttribute('data-url');
                if (u) {
                    window.open(u, '_blank', 'noopener,noreferrer');
                } else {
                    window.open(window.location.href, '_blank', 'noopener,noreferrer');
                }
                closeAllMenus();
            });
        }

        const btnClose = document.getElementById('menu-close');
        if (btnClose) {
            btnClose.addEventListener('click', function() {
                window.close();
            });
        }

        document.querySelectorAll('button.menu-option[data-theme]').forEach(function(btn) {
            btn.addEventListener('click', function() {
                applyTheme(btn.getAttribute('data-theme'));
                closeAllMenus();
            });
        });

        function editSelectAll() {
            var el = document.getElementById('console-output');
            if (!el) return;
            var sel = window.getSelection();
            var range = document.createRange();
            range.selectNodeContents(el);
            sel.removeAllRanges();
            sel.addRange(range);
            try {
                if (document.execCommand('copy')) {
                    return;
                }
            } catch (e) {}
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(el.innerText || el.textContent);
                }
            } catch (e2) {}
        }

        function editExpandAll() {
            var containers = [document.getElementById('console-output'), document.getElementById('split-console-output')];
            containers.forEach(function(container) {
                if (!container) return;
                container.querySelectorAll('.log-entry').forEach(function(entry) {
                    entry.classList.add('expanded');
                    var t = entry.querySelector('.log-toggle');
                    if (t) { t.textContent = '▼'; t.title = 'Hide JSON payload'; }
                });
                container.querySelectorAll('.output-header-toggle').forEach(function(headerToggle) {
                    var wrapper = headerToggle.closest('.cmd-output-wrapper');
                    if (wrapper) {
                        var sections = wrapper.querySelector('.output-sections');
                        if (sections) { sections.style.display = ''; headerToggle.textContent = '▼'; }
                    }
                });
                container.querySelectorAll('.section-header .section-toggle').forEach(function(toggle) {
                    var header = toggle.closest('.section-header');
                    var content = header && header.nextElementSibling;
                    if (content && content.classList.contains('section-content')) {
                        content.style.display = 'block';
                        toggle.textContent = '▼';
                        header.classList.add('section-header--active');
                    }
                });
                container.querySelectorAll('.json-tree-toggle').forEach(function(toggle) {
                    var node = toggle.closest('.json-tree-node');
                    if (node) {
                        var children = node.querySelector('.json-tree-children');
                        if (children) {
                            toggle.classList.add('expanded');
                            toggle.textContent = '▼';
                            children.style.display = 'block';
                        }
                    }
                });
                container.querySelectorAll('.form-section-header .section-toggle').forEach(function(toggle) {
                    var header = toggle.closest('.form-section-header');
                    var content = header && header.nextElementSibling;
                    if (content && content.classList.contains('form-section-content')) {
                        toggle.classList.add('expanded');
                        toggle.textContent = '▼';
                        content.style.display = 'grid';
                    }
                });
            });
        }

        function editCollapseAll() {
            var containers = [document.getElementById('console-output'), document.getElementById('split-console-output')];
            containers.forEach(function(container) {
                if (!container) return;
                container.querySelectorAll('.log-entry').forEach(function(entry) {
                    entry.classList.remove('expanded');
                    var t = entry.querySelector('.log-toggle');
                    if (t) { t.textContent = '▶'; t.title = 'Show full JSON payload'; }
                });
                container.querySelectorAll('.output-header-toggle').forEach(function(headerToggle) {
                    var wrapper = headerToggle.closest('.cmd-output-wrapper');
                    if (wrapper) {
                        var sections = wrapper.querySelector('.output-sections');
                        if (sections) { sections.style.display = 'none'; headerToggle.textContent = '▶'; }
                    }
                });
                container.querySelectorAll('.section-header .section-toggle').forEach(function(toggle) {
                    var header = toggle.closest('.section-header');
                    var content = header && header.nextElementSibling;
                    if (content && content.classList.contains('section-content')) {
                        content.style.display = 'none';
                        toggle.textContent = '▶';
                        header.classList.remove('section-header--active');
                    }
                });
                container.querySelectorAll('.json-tree-toggle').forEach(function(toggle) {
                    var node = toggle.closest('.json-tree-node');
                    if (node) {
                        var children = node.querySelector('.json-tree-children');
                        if (children) {
                            toggle.classList.remove('expanded');
                            toggle.textContent = '▶';
                            children.style.display = 'none';
                        }
                    }
                });
                container.querySelectorAll('.form-section-header .section-toggle').forEach(function(toggle) {
                    var header = toggle.closest('.form-section-header');
                    var content = header && header.nextElementSibling;
                    if (content && content.classList.contains('form-section-content')) {
                        toggle.classList.remove('expanded');
                        toggle.textContent = '▶';
                        content.style.display = 'none';
                    }
                });
            });
        }

        var btnEditSelectAll = document.getElementById('menu-edit-select-all');
        if (btnEditSelectAll) {
            btnEditSelectAll.addEventListener('click', function() {
                editSelectAll();
                closeAllMenus();
            });
        }
        var btnEditExpandAll = document.getElementById('menu-edit-expand-all');
        if (btnEditExpandAll) {
            btnEditExpandAll.addEventListener('click', function() {
                editExpandAll();
                closeAllMenus();
            });
        }
        var btnEditCollapseAll = document.getElementById('menu-edit-collapse-all');
        if (btnEditCollapseAll) {
            btnEditCollapseAll.addEventListener('click', function() {
                editCollapseAll();
                closeAllMenus();
            });
        }

        const btnCompactView = document.getElementById('menu-compact-view');
        if (btnCompactView) {
            btnCompactView.addEventListener('click', function() {
                toggleCompactView();
                closeAllMenus();
            });
        }

        const btnAutosave = document.getElementById('menu-autosave');
        if (btnAutosave) {
            btnAutosave.addEventListener('click', function() {
                toggleAutosave();
                closeAllMenus();
            });
        }
        
        document.querySelectorAll('[data-runmode]').forEach(function(opt) {
            opt.addEventListener('click', function() {
                const mode = this.dataset.runmode;
                document.querySelectorAll('[data-runmode]').forEach(function(o) {
                    o.classList.remove('active');
                });
                this.classList.add('active');
                localStorage.setItem('nos-run-mode', mode);
                window.dispatchEvent(new CustomEvent('run-mode-changed', { detail: { mode: mode } }));
                closeAllMenus();
            });
        });

        // Output Mode preference (debug/trace)
        document.querySelectorAll('[data-outputmode]').forEach(function(opt) {
            opt.addEventListener('click', function() {
                const mode = this.dataset.outputmode;
                document.querySelectorAll('[data-outputmode]').forEach(function(o) {
                    o.classList.remove('active');
                });
                this.classList.add('active');
                localStorage.setItem('nos-output-mode', mode);
                window.dispatchEvent(new CustomEvent('output-mode-changed', { detail: { mode: mode } }));
                closeAllMenus();
            });
        });

        var rawTheme = localStorage.getItem('nos-theme');
        var savedTheme = rawTheme;
        if (rawTheme === 'nos-dark') savedTheme = 'nos';
        if (rawTheme === 'nos-light') savedTheme = 'light';
        if (savedTheme && savedTheme !== rawTheme) {
            localStorage.setItem('nos-theme', savedTheme);
        }
        if (savedTheme && themes[savedTheme]) {
            applyTheme(savedTheme);
        } else {
            applyTheme('nos');
        }

        const savedAutosave = localStorage.getItem('nos-autosave');
        if (savedAutosave === 'true') {
            menuState.autosaveEnabled = true;
            const btn = document.getElementById('menu-autosave');
            if (btn) btn.classList.add('active');
        }

        const savedCompactView = localStorage.getItem('nos-compact-view');
        if (savedCompactView === 'true') {
            const compactBtn = document.getElementById('menu-compact-view');
            if (compactBtn) {
                menuState.compactViewEnabled = true;
                document.body.classList.add('compact-view');
                compactBtn.classList.add('active');
            }
        }
        
        const savedRunMode = localStorage.getItem('nos-run-mode') || 'dev';
        document.querySelectorAll('[data-runmode]').forEach(function(opt) {
            opt.classList.toggle('active', opt.dataset.runmode === savedRunMode);
        });

        // Restore Output Mode preference
        const savedOutputMode = localStorage.getItem('nos-output-mode') || 'debug';
        document.querySelectorAll('[data-outputmode]').forEach(function(opt) {
            opt.classList.toggle('active', opt.dataset.outputmode === savedOutputMode);
        });

        document.addEventListener('keydown', function(e) {
            if (e.ctrlKey && e.shiftKey && e.key === 'N') {
                e.preventDefault();
                window.open(window.location.href, '_blank');
            }
            if (e.ctrlKey && e.key === '\\') {
                e.preventDefault();
                toggleSplitView();
            }
        });

        const btnSplitView = document.getElementById('menu-split-view');
        if (btnSplitView) {
            btnSplitView.addEventListener('click', function() {
                toggleSplitView();
                closeAllMenus();
            });
        }

        const savedSplitView = localStorage.getItem('nos-split-view');
        if (savedSplitView === 'true') {
            menuState.splitViewEnabled = true;
            document.body.classList.add('layout-split');
            const btn = document.getElementById('menu-split-view');
            if (btn) btn.classList.add('active');
            initSplitResizer();
            restoreSplitRatio();
            setTimeout(function() {
                syncContentToSplit();
            }, 500);
        }

        window.addEventListener('split-view-enable', function() {
            if (menuState.splitViewEnabled) return;
            menuState.splitViewEnabled = true;
            document.body.classList.add('layout-split');
            const btn = document.getElementById('menu-split-view');
            if (btn) btn.classList.add('active');
            localStorage.setItem('nos-split-view', true);
            initSplitResizer();
            restoreSplitRatio();
            setTimeout(function() { syncContentToSplit(); }, 500);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

/* ==========================================================================
   Explorer Panel - File Tree & Outline
   ========================================================================== */
(function() {
    'use strict';

    const explorerState = {
        isOpen: false,
        fileTree: null,
        workspaceTreeLoaded: false,
        currentFile: null,
        currentOutline: []
    };

    const explorerDom = {
        offcanvas: document.getElementById('explorer-offcanvas'),
        backdrop: document.getElementById('explorer-backdrop'),
        closeBtn: document.getElementById('explorer-close'),
        menuToggle: document.getElementById('menu-explorer'),
        fileTree: document.getElementById('file-tree'),
        workspaceTree: document.getElementById('explorer-workspace-tree'),
        workspaceHint: document.getElementById('explorer-workspace-hint'),
        viewProjectPane: document.getElementById('explorer-view-project'),
        viewWorkspacePane: document.getElementById('explorer-view-workspace'),
        outlineTree: document.getElementById('outline-tree'),
        resizer: document.getElementById('explorer-resizer'),
        filesPanel: document.getElementById('explorer-files-panel'),
        outlinePanel: document.getElementById('explorer-outline-panel'),
        projectHint: document.getElementById('explorer-project-hint')
    };

    function escapeExplorerHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function toggleExplorer() {
        explorerState.isOpen = !explorerState.isOpen;
        
        if (explorerState.isOpen) {
            explorerDom.offcanvas.classList.add('open');
            explorerDom.backdrop.classList.add('open');
            if (explorerDom.menuToggle) {
                explorerDom.menuToggle.classList.add('checked');
            }
            
            if (!explorerState.fileTree) {
                loadFileTree();
            }
            const activeView = document.querySelector('.explorer-view-tab.active');
            if (activeView && activeView.getAttribute('data-explorer-view') === 'workspace' && !explorerState.workspaceTreeLoaded) {
                loadWorkspaceDriveTree();
            }
        } else {
            explorerDom.offcanvas.classList.remove('open');
            explorerDom.backdrop.classList.remove('open');
            if (explorerDom.menuToggle) {
                explorerDom.menuToggle.classList.remove('checked');
            }
        }
    }

    /**
     * Official two-tone Python logo (same asset as plugin console tabs), for .py / .pyi / .pyw in Project tree.
     */
    const EXPLORER_PYTHON_LOGO_SVG =
        '<svg class="tree-python-logo-svg" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">' +
        '<path fill="#3776AB" d="M12 0C5.373 0 5.455.256 5.455 2.857v2.143h6.545v.857H3.818C1.364 5.857 0 7.714 0 11.143c0 3.428 1.714 5.143 3.818 5.143h2.455v-2.857c0-2.143 1.818-4 4.091-4h6.545c2.273 0 4.091-1.714 4.091-4V2.857C21 .256 18.727 0 12 0zm-3.273 1.714a1.286 1.286 0 110 2.572 1.286 1.286 0 010-2.572z"/>' +
        '<path fill="#FFD43B" d="M12 24c6.627 0 6.545-.256 6.545-2.857v-2.143h-6.545v-.857h8.182c2.454 0 3.818-1.857 3.818-5.286 0-3.428-1.714-5.143-3.818-5.143h-2.455v2.857c0 2.143-1.818 4-4.091 4H7.091c-2.273 0-4.091 1.714-4.091 4v2.572C3 23.744 5.273 24 12 24zm3.273-1.714a1.286 1.286 0 110-2.572 1.286 1.286 0 010 2.572z"/>' +
        '</svg>';

    /**
     * Icons for typical Python / Flask / web project files (extension or whole name → emoji + CSS class).
     * Fallback: generic file. (.py / .pyi / .pyw use EXPLORER_PYTHON_LOGO_SVG in renderFileTree.)
     */
    const PROJECT_FILE_ICON_DEFAULT = { sym: '📄', cls: 'file', hint: 'file' };

    const PROJECT_SPECIAL_FILE_ICONS = {
        dockerfile: { sym: '🐳', cls: 'docker', hint: 'Dockerfile' },
        'docker-compose.yml': { sym: '🐳', cls: 'docker', hint: 'Docker Compose' },
        'docker-compose.yaml': { sym: '🐳', cls: 'docker', hint: 'Docker Compose' },
        makefile: { sym: '🔧', cls: 'make', hint: 'Makefile' },
        gnumakefile: { sym: '🔧', cls: 'make', hint: 'Makefile' },
        'requirements.txt': { sym: '📋', cls: 'req', hint: 'requirements.txt' },
        'requirements-dev.txt': { sym: '📋', cls: 'req', hint: 'requirements' },
        'requirements-test.txt': { sym: '📋', cls: 'req', hint: 'requirements' },
        'pyproject.toml': { sym: '⚙', cls: 'toml', hint: 'pyproject.toml' },
        'poetry.lock': { sym: '🔒', cls: 'lock', hint: 'poetry.lock' },
        'package.json': { sym: '📦', cls: 'npm', hint: 'package.json' },
        'package-lock.json': { sym: '🔒', cls: 'lock', hint: 'package-lock.json' },
        'yarn.lock': { sym: '🔒', cls: 'lock', hint: 'yarn.lock' },
        'pnpm-lock.yaml': { sym: '🔒', cls: 'lock', hint: 'pnpm lock' },
        '.env': { sym: '🔐', cls: 'env', hint: '.env' },
        '.env.example': { sym: '🔐', cls: 'env', hint: '.env.example' },
        '.env.local': { sym: '🔐', cls: 'env', hint: '.env.local' },
        'manage.py': { sym: '🐍', cls: 'py', hint: 'manage.py' },
        'wsgi.py': { sym: '🌐', cls: 'wsgi', hint: 'WSGI' },
        'asgi.py': { sym: '🌐', cls: 'asgi', hint: 'ASGI' },
        license: { sym: '📜', cls: 'license', hint: 'License' },
        copying: { sym: '📜', cls: 'license', hint: 'License' },
        'readme.md': { sym: '📖', cls: 'readme', hint: 'README' },
        'readme.rst': { sym: '📖', cls: 'readme', hint: 'README' },
        'readme.txt': { sym: '📖', cls: 'readme', hint: 'README' },
        'tailwind.config.js': { sym: '🎨', cls: 'tailwind', hint: 'Tailwind' },
        'tailwind.config.ts': { sym: '🎨', cls: 'tailwind', hint: 'Tailwind' },
        'vite.config.js': { sym: '⚡', cls: 'vite', hint: 'Vite' },
        'vite.config.ts': { sym: '⚡', cls: 'vite', hint: 'Vite' },
        'webpack.config.js': { sym: '📦', cls: 'webpack', hint: 'Webpack' },
        'webpack.config.ts': { sym: '📦', cls: 'webpack', hint: 'Webpack' },
        'gulpfile.js': { sym: '🫧', cls: 'gulp', hint: 'Gulp' },
        'gulpfile.ts': { sym: '🫧', cls: 'gulp', hint: 'Gulp' },
        'robots.txt': { sym: '🤖', cls: 'robots', hint: 'robots.txt' },
        'alembic.ini': { sym: '🗄', cls: 'alembic', hint: 'Alembic' }
    };

    const PROJECT_EXT_ICONS = {
        py: { sym: '🐍', cls: 'py', hint: '.py' },
        pyi: { sym: '🐍', cls: 'pyi', hint: '.pyi' },
        pyw: { sym: '🐍', cls: 'pyw', hint: '.pyw' },
        pyc: { sym: '⚙', cls: 'pyc', hint: '.pyc' },
        pyo: { sym: '⚙', cls: 'pyc', hint: '.pyo' },
        pyd: { sym: '⚙', cls: 'pyd', hint: '.pyd' },
        ipynb: { sym: '📓', cls: 'ipynb', hint: 'Jupyter' },
        html: { sym: '🌐', cls: 'html', hint: '.html' },
        htm: { sym: '🌐', cls: 'html', hint: '.htm' },
        jinja: { sym: '🧩', cls: 'jinja', hint: 'Jinja' },
        j2: { sym: '🧩', cls: 'jinja', hint: 'Jinja' },
        jinja2: { sym: '🧩', cls: 'jinja', hint: 'Jinja' },
        xml: { sym: '📰', cls: 'xml', hint: '.xml' },
        css: { sym: '🎨', cls: 'css', hint: '.css' },
        scss: { sym: '🎨', cls: 'scss', hint: '.scss' },
        sass: { sym: '🎨', cls: 'sass', hint: '.sass' },
        less: { sym: '🎨', cls: 'less', hint: '.less' },
        js: { sym: '📜', cls: 'js', hint: '.js' },
        mjs: { sym: '📜', cls: 'js', hint: '.mjs' },
        cjs: { sym: '📜', cls: 'js', hint: '.cjs' },
        ts: { sym: '📘', cls: 'ts', hint: '.ts' },
        tsx: { sym: '⚛', cls: 'tsx', hint: '.tsx' },
        jsx: { sym: '⚛', cls: 'jsx', hint: '.jsx' },
        vue: { sym: '💚', cls: 'vue', hint: '.vue' },
        svelte: { sym: '🧡', cls: 'svelte', hint: '.svelte' },
        json: { sym: '📋', cls: 'json', hint: '.json' },
        jsonl: { sym: '📋', cls: 'jsonl', hint: '.jsonl' },
        yaml: { sym: '📋', cls: 'yaml', hint: '.yaml' },
        yml: { sym: '📋', cls: 'yaml', hint: '.yml' },
        toml: { sym: '⚙', cls: 'toml', hint: '.toml' },
        ini: { sym: '⚙', cls: 'ini', hint: '.ini' },
        cfg: { sym: '⚙', cls: 'cfg', hint: '.cfg' },
        conf: { sym: '⚙', cls: 'conf', hint: '.conf' },
        env: { sym: '🔐', cls: 'env', hint: '.env' },
        md: { sym: '📝', cls: 'md', hint: 'Markdown' },
        mdx: { sym: '📝', cls: 'mdx', hint: 'MDX' },
        rst: { sym: '📝', cls: 'rst', hint: 'reST' },
        txt: { sym: '📄', cls: 'txt', hint: '.txt' },
        log: { sym: '📋', cls: 'log', hint: '.log' },
        sql: { sym: '🗄', cls: 'sql', hint: '.sql' },
        sqlite: { sym: '🗄', cls: 'sqlite', hint: '.sqlite' },
        db: { sym: '🗄', cls: 'db', hint: '.db' },
        svg: { sym: '🖼', cls: 'svg', hint: '.svg' },
        png: { sym: '🖼', cls: 'png', hint: '.png' },
        jpg: { sym: '🖼', cls: 'img', hint: '.jpg' },
        jpeg: { sym: '🖼', cls: 'img', hint: '.jpeg' },
        gif: { sym: '🖼', cls: 'img', hint: '.gif' },
        webp: { sym: '🖼', cls: 'img', hint: '.webp' },
        ico: { sym: '🖼', cls: 'ico', hint: '.ico' },
        woff: { sym: '🔤', cls: 'font', hint: 'font' },
        woff2: { sym: '🔤', cls: 'font', hint: 'font' },
        ttf: { sym: '🔤', cls: 'font', hint: 'font' },
        otf: { sym: '🔤', cls: 'font', hint: 'font' },
        eot: { sym: '🔤', cls: 'font', hint: 'font' },
        sh: { sym: '⌨', cls: 'sh', hint: 'shell' },
        bash: { sym: '⌨', cls: 'sh', hint: 'bash' },
        zsh: { sym: '⌨', cls: 'sh', hint: 'zsh' },
        ps1: { sym: '⌨', cls: 'ps1', hint: 'PowerShell' },
        bat: { sym: '⌨', cls: 'bat', hint: '.bat' },
        cmd: { sym: '⌨', cls: 'cmd', hint: '.cmd' },
        http: { sym: '🌍', cls: 'http', hint: '.http' },
        rest: { sym: '🌍', cls: 'http', hint: '.rest' }
    };

    function projectFileIconMeta(fileName) {
        const lower = String(fileName || '').toLowerCase();
        if (PROJECT_SPECIAL_FILE_ICONS[lower]) {
            return PROJECT_SPECIAL_FILE_ICONS[lower];
        }
        const dot = lower.lastIndexOf('.');
        const ext = dot >= 0 ? lower.slice(dot + 1) : '';
        if (ext && PROJECT_EXT_ICONS[ext]) {
            return PROJECT_EXT_ICONS[ext];
        }
        return { ...PROJECT_FILE_ICON_DEFAULT, hint: ext ? '.' + ext : PROJECT_FILE_ICON_DEFAULT.hint };
    }

    async function loadFileTree() {
        explorerDom.fileTree.innerHTML =
            '<div class="tree-loading tree-loading--spinner">Loading project…</div>';
        if (explorerDom.projectHint) {
            explorerDom.projectHint.hidden = true;
            explorerDom.projectHint.textContent = '';
        }

        try {
            const response = await fetch('/api/console/project-tree');
            const data = await response.json().catch(function() { return {}; });
            if (!response.ok) {
                const msg = (data && data.error) || ('HTTP ' + response.status);
                throw new Error(msg);
            }
            explorerState.fileTree = data.tree;
            if (explorerDom.projectHint && data.project_root) {
                explorerDom.projectHint.textContent = 'Root: ' + data.project_root;
                explorerDom.projectHint.hidden = false;
            }
            renderFileTree(data.tree || []);
        } catch (error) {
            console.error('Project tree failed:', error);
            const msg = error && error.message ? error.message : 'Could not load project tree';
            explorerDom.fileTree.innerHTML =
                '<div class="tree-error" role="alert">' + escapeExplorerHtml(msg) + '</div>';
        }
    }

    async function loadPluginsExplorerTree() {
        explorerDom.fileTree.innerHTML =
            '<div class="tree-loading tree-loading--spinner">Loading plugins…</div>';
        if (explorerDom.projectHint) {
            explorerDom.projectHint.hidden = true;
            explorerDom.projectHint.textContent = '';
        }

        try {
            const response = await fetch('/api/console/plugins-explorer-tree');
            const data = await response.json().catch(function() { return {}; });
            if (!response.ok) {
                const msg = (data && data.error) || ('HTTP ' + response.status);
                throw new Error(msg);
            }
            explorerState.fileTree = data.tree;
            if (explorerDom.projectHint && data.project_root) {
                explorerDom.projectHint.textContent = 'Plugins root: ' + data.project_root;
                explorerDom.projectHint.hidden = false;
            }
            renderFileTree(data.tree || []);
        } catch (error) {
            console.error('Plugins explorer tree failed:', error);
            const msg = error && error.message ? error.message : 'Could not load plugins explorer tree';
            explorerDom.fileTree.innerHTML =
                '<div class="tree-error" role="alert">' + escapeExplorerHtml(msg) + '</div>';
        }
    }

    function renderFileTree(tree, container = null, depth = 0) {
        if (!container) {
            explorerDom.fileTree.innerHTML = '';
            container = explorerDom.fileTree;
        }

        if (!tree || tree.length === 0) {
            if (!depth) {
                container.innerHTML = '<div class="tree-muted">No files under project root.</div>';
            }
            return;
        }

        tree.forEach(item => {
            if (item.type === 'folder') {
                const folderEl = document.createElement('div');
                folderEl.className = 'tree-folder';
                folderEl.dataset.path = item.path || '';

                const displayLabel = item.name || '';

                const itemEl = document.createElement('div');
                itemEl.className = 'tree-item';
                if (item.virtual_root) {
                    folderEl.classList.add('expanded');
                }
                itemEl.innerHTML =
                    '<span class="tree-indent"></span>'.repeat(depth) +
                    '<span class="tree-icon folder">' +
                    (folderEl.classList.contains('expanded') ? '📂' : '📁') +
                    '</span>' +
                    '<span class="tree-label">' + escapeExplorerHtml(displayLabel) + '</span>';

                itemEl.addEventListener('click', () => {
                    folderEl.classList.toggle('expanded');
                    const icon = itemEl.querySelector('.tree-icon');
                    if (icon) {
                        icon.textContent = folderEl.classList.contains('expanded') ? '📂' : '📁';
                        icon.classList.toggle('folder-open', folderEl.classList.contains('expanded'));
                    }
                });

                folderEl.appendChild(itemEl);

                const childContainer = document.createElement('div');
                childContainer.className = 'tree-folder-children';
                renderFileTree(item.children || [], childContainer, depth + 1);
                folderEl.appendChild(childContainer);

                container.appendChild(folderEl);
            } else if (item.type === 'file') {
                const fileEl = document.createElement('div');
                fileEl.className = 'tree-item';
                fileEl.dataset.path = item.path || '';
                fileEl.dataset.modulePath = item.module_path || '';
                const fname = item.name || '';
                const isPySource = /\.py(i|w)?$/i.test(fname);
                let iconHtml;
                if (isPySource) {
                    const lower = fname.toLowerCase();
                    const extHint =
                        lower.endsWith('.pyi') ? '.pyi' : lower.endsWith('.pyw') ? '.pyw' : '.py';
                    iconHtml =
                        '<span class="tree-icon tree-python-logo" title="' +
                        escapeExplorerHtml(extHint) +
                        '">' +
                        EXPLORER_PYTHON_LOGO_SVG +
                        '</span>';
                } else {
                    const meta = projectFileIconMeta(fname);
                    const hint = escapeExplorerHtml(meta.hint || '');
                    const sym = meta.sym || PROJECT_FILE_ICON_DEFAULT.sym;
                    const cls = meta.cls || 'file';
                    iconHtml =
                        '<span class="tree-icon tree-icon-project tree-icon-project--' +
                        cls +
                        '" title="' +
                        hint +
                        '">' +
                        sym +
                        '</span>';
                }
                fileEl.innerHTML =
                    '<span class="tree-indent"></span>'.repeat(depth) +
                    iconHtml +
                    '<span class="tree-label">' + escapeExplorerHtml(fname) + '</span>';

                fileEl.addEventListener('click', () => selectFile(fileEl, item));
                fileEl.addEventListener('dblclick', (e) => {
                    e.stopPropagation();
                    if (!item.module_path) return;
                    const isPy = (item.name && item.name.endsWith('.py')) || (item.path && /\.py$/i.test(item.path));
                    if (!isPy) return;
                    const pluginType = item.module_path.includes('.workflows.') ? 'workflow' : 'node';
                    const cmd = `open ${pluginType} ${item.module_path}`;
                    if (typeof window.showTab === 'function') window.showTab('workspace');
                    window.dispatchEvent(new CustomEvent('console-command', { detail: { command: cmd } }));
                });
                container.appendChild(fileEl);
            }
        });
    }

    function setExplorerView(view) {
        /* v2: Drive tree lives in the left dock column «workspace»; legacy Project|Workspace tabs sit in the «plugins» column. Showing workspace without switching the dock leaves the tree in a hidden pane. */
        if (document.body.classList.contains('console-v2') && typeof window.__nosV2ActivateLeftDockTab === 'function') {
            if (view === 'workspace') {
                window.__nosV2ActivateLeftDockTab('workspace');
            } else if (view === 'project') {
                window.__nosV2ActivateLeftDockTab('plugins');
            }
        }
        const tabs = document.querySelectorAll('.explorer-view-tab[data-explorer-view]');
        tabs.forEach(function(t) {
            const on = t.getAttribute('data-explorer-view') === view;
            t.classList.toggle('active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        if (explorerDom.viewProjectPane) {
            explorerDom.viewProjectPane.classList.toggle('active', view === 'project');
            explorerDom.viewProjectPane.hidden = view !== 'project';
        }
        if (explorerDom.viewWorkspacePane) {
            explorerDom.viewWorkspacePane.classList.toggle('active', view === 'workspace');
            explorerDom.viewWorkspacePane.hidden = view !== 'workspace';
        }
        if (view === 'workspace' && !explorerState.workspaceTreeLoaded) {
            loadWorkspaceDriveTree();
        }
    }

    function initExplorerViewTabs() {
        document.querySelectorAll('.explorer-view-tab[data-explorer-view]').forEach(function(tab) {
            tab.addEventListener('click', function() {
                setExplorerView(tab.getAttribute('data-explorer-view') || 'project');
            });
        });
    }

    async function loadWorkspaceDriveTree() {
        if (!explorerDom.workspaceTree) return;
        explorerDom.workspaceTree.innerHTML =
            '<div class="tree-loading tree-loading--spinner">Loading sessions…</div>';
        try {
            const response = await fetch('/api/console/user-sessions-tree');
            if (!response.ok) throw new Error('HTTP ' + response.status);
            const data = await response.json();
            if (explorerDom.workspaceHint) {
                explorerDom.workspaceHint.textContent =
                    (data.sessions_path || '~/.nos/drive/@user') +
                    (data.username ? ' · user: ' + data.username : '');
            }
            renderDriveFileTree(data.tree || []);
            explorerState.workspaceTreeLoaded = true;
        } catch (error) {
            console.error('Sessions tree failed:', error);
            explorerDom.workspaceTree.innerHTML =
                '<div class="tree-error" role="alert">Could not load sessions folder</div>';
        }
    }

    function renderDriveFileTree(tree, container, depth) {
        container = container || explorerDom.workspaceTree;
        depth = depth || 0;
        if (!container) return;
        if (!depth) {
            container.innerHTML = '';
        }
        if (!tree || tree.length === 0) {
            if (!depth) {
                container.innerHTML =
                    '<div class="tree-muted">No files yet. Use <strong>Workspace → Save session</strong> to write <code>.wks</code> / <code>.out</code> here.</div>';
            }
            return;
        }

        tree.forEach(function(item) {
            if (item.type === 'folder') {
                const folderEl = document.createElement('div');
                folderEl.className = 'tree-folder explorer-drive-folder';
                if (depth === 0 || item.virtual_root) {
                    folderEl.classList.add('expanded');
                }

                const itemEl = document.createElement('div');
                itemEl.className = 'tree-item tree-item--drive';
                const open = folderEl.classList.contains('expanded');
                itemEl.innerHTML =
                    '<span class="tree-indent"></span>'.repeat(depth) +
                    '<span class="tree-icon folder">' +
                    (open ? '📂' : '📁') +
                    '</span>' +
                    '<span class="tree-label">' + escapeExplorerHtml(item.name) + '</span>';

                itemEl.addEventListener('click', function() {
                    folderEl.classList.toggle('expanded');
                    const icon = itemEl.querySelector('.tree-icon');
                    if (icon) {
                        icon.textContent = folderEl.classList.contains('expanded') ? '📂' : '📁';
                        icon.classList.toggle('folder-open', folderEl.classList.contains('expanded'));
                    }
                });

                folderEl.appendChild(itemEl);

                if (item.children && item.children.length > 0) {
                    const childContainer = document.createElement('div');
                    childContainer.className = 'tree-folder-children';
                    renderDriveFileTree(item.children, childContainer, depth + 1);
                    folderEl.appendChild(childContainer);
                }

                container.appendChild(folderEl);
            } else if (item.type === 'file') {
                const fileEl = document.createElement('div');
                fileEl.className = 'tree-item tree-item--drive';
                fileEl.dataset.path = item.path || '';
                const name = item.name || '';
                const isWks = /\.wks$/i.test(name);
                const isOut = /\.out$/i.test(name);
                const isJson = /\.json$/i.test(name);
                const iconCls = isWks
                    ? 'tree-icon--drive-nos'
                    : isOut
                        ? 'tree-icon--drive-json'
                        : isJson
                            ? 'tree-icon--drive-json'
                            : 'tree-icon--drive-file';
                fileEl.innerHTML =
                    '<span class="tree-indent"></span>'.repeat(depth) +
                    '<span class="tree-icon ' + iconCls + '" aria-hidden="true"></span>' +
                    '<span class="tree-label">' + escapeExplorerHtml(name) + '</span>';

                fileEl.addEventListener('click', function() {
                    explorerDom.workspaceTree.querySelectorAll('.tree-item--drive.selected').forEach(function(el) {
                        el.classList.remove('selected');
                    });
                    fileEl.classList.add('selected');
                    if (isWks && item.path && typeof window.__nosLoadConsoleSessionFromPath === 'function') {
                        window.__nosLoadConsoleSessionFromPath(item.path).catch(function(err) {
                            console.error(err);
                            window.alert('Could not load workspace session: ' + (err && err.message ? err.message : String(err)));
                        });
                    }
                    if (isOut && item.path && typeof window.__nosLoadConsoleSessionFromPath === 'function') {
                        window.__nosLoadConsoleSessionFromPath(item.path).catch(function(err) {
                            console.error(err);
                            window.alert('Could not load execution output: ' + (err && err.message ? err.message : String(err)));
                        });
                    }
                });
                fileEl.addEventListener('dblclick', function(e) {
                    e.stopPropagation();
                    if (!item.path) return;
                    if (isWks || isOut) {
                        return;
                    }
                    window.dispatchEvent(new CustomEvent('explorer-workspace-path', { detail: { path: item.path } }));
                });

                container.appendChild(fileEl);
            }
        });
    }

    function openPluginExplorerFileByPath(absPath) {
        if (!absPath || typeof window.__workspaceOpenPythonDocument !== 'function') return;
        fetch('/api/console/plugin-explorer-file?path=' + encodeURIComponent(absPath))
            .then(function (response) {
                return response.json().then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function (result) {
                if (!result.ok || result.data == null || result.data.error) {
                    const msg =
                        (result.data && result.data.error) ||
                        'Could not open file';
                    console.error('plugin-explorer-file:', msg);
                    return;
                }
                window.__workspaceOpenPythonDocument({
                    content: result.data.content,
                    file_path: result.data.file_path || absPath,
                    module_path: null
                });
            })
            .catch(function (err) {
                console.error('plugin-explorer-file:', err);
            });
    }

    function selectFile(element, item) {
        explorerDom.fileTree.querySelectorAll('.tree-item.selected').forEach(el => {
            el.classList.remove('selected');
        });
        element.classList.add('selected');
        
        explorerState.currentFile = item;
        
        const fname = item.name || '';
        const pathStr = item.path || '';
        const isPySource = /\.py(i|w)?$/i.test(fname) || /\.py(i|w)?$/i.test(pathStr);

        if (item.module_path) {
            const pluginType = item.module_path.includes('.workflows.') ? 'workflow' : 'node';
            const cmd = `open ${pluginType} ${item.module_path}`;
            window.dispatchEvent(new CustomEvent('console-command', { detail: { command: cmd } }));
        } else if (isPySource && pathStr) {
            openPluginExplorerFileByPath(pathStr);
        }

        if (isPySource && typeof window.showTab === 'function') {
            window.showTab('workspace');
        }
        
        loadOutline(item.path);
    }

    async function loadOutline(filePath) {
        if (!filePath || typeof filePath !== 'string') {
            explorerDom.outlineTree.innerHTML =
                '<div class="outline-empty">Open a Python file to see its outline</div>';
            return;
        }
        if (!filePath.toLowerCase().endsWith('.py')) {
            explorerDom.outlineTree.innerHTML =
                '<div class="outline-empty">Outline is only available for .py files</div>';
            return;
        }

        explorerDom.outlineTree.innerHTML =
            '<div class="tree-loading tree-loading--spinner">Parsing…</div>';

        try {
            const response = await fetch(`/api/plugins/outline?path=${encodeURIComponent(filePath)}`);
            if (!response.ok) throw new Error('Failed to load outline');
            
            const data = await response.json();
            explorerState.currentOutline = data.outline;
            renderOutline(data.outline);
        } catch (error) {
            console.error('Failed to load outline:', error);
            explorerDom.outlineTree.innerHTML = '<div class="outline-empty">Could not parse file</div>';
        }
    }

    function renderOutline(outline) {
        if (!outline || outline.length === 0) {
            explorerDom.outlineTree.innerHTML = '<div class="outline-empty">No symbols found</div>';
            return;
        }

        explorerDom.outlineTree.innerHTML = '';
        
        outline.forEach(item => {
            const el = document.createElement('div');
            el.className = 'outline-item';
            el.dataset.line = item.line;
            
            let icon = 'V';
            let iconClass = 'variable';
            
            if (item.type === 'class') {
                icon = 'C';
                iconClass = 'class';
            } else if (item.type === 'method') {
                icon = 'M';
                iconClass = 'method';
            } else if (item.type === 'function') {
                icon = 'F';
                iconClass = 'function';
            }
            
            const indent = '<span class="tree-indent"></span>'.repeat(item.depth || 0);
            
            el.innerHTML = `
                ${indent}
                <span class="outline-icon ${iconClass}">${icon}</span>
                <span class="outline-label">${item.name}</span>
                <span class="outline-line">:${item.line}</span>
            `;
            
            el.addEventListener('click', () => {
                window.dispatchEvent(new CustomEvent('editor-goto-line', { detail: { line: item.line } }));
                
                explorerDom.outlineTree.querySelectorAll('.outline-item.active').forEach(i => {
                    i.classList.remove('active');
                });
                el.classList.add('active');
            });
            
            explorerDom.outlineTree.appendChild(el);
        });
    }

    function updateOutlineFromCode(code) {
        if (!code) {
            explorerDom.outlineTree.innerHTML = '<div class="outline-empty">Open a file to see its outline</div>';
            return;
        }

        const outline = parseCodeOutline(code);
        explorerState.currentOutline = outline;
        renderOutline(outline);
    }

    function parseCodeOutline(code) {
        const outline = [];
        const lines = code.split('\n');
        let currentClass = null;

        lines.forEach((line, index) => {
            const lineNum = index + 1;
            
            const classMatch = line.match(/^class\s+(\w+)/);
            if (classMatch) {
                currentClass = classMatch[1];
                outline.push({
                    type: 'class',
                    name: classMatch[1],
                    line: lineNum,
                    depth: 0
                });
                return;
            }
            
            const funcMatch = line.match(/^(\s*)def\s+(\w+)\s*\(/);
            if (funcMatch) {
                const indent = funcMatch[1].length;
                const name = funcMatch[2];
                const isMethod = indent > 0 && currentClass;
                
                outline.push({
                    type: isMethod ? 'method' : 'function',
                    name: name,
                    line: lineNum,
                    depth: isMethod ? 1 : 0,
                    parent: isMethod ? currentClass : null
                });
            }
        });

        return outline;
    }

    function initExplorerResizer() {
        const resizer = explorerDom.resizer;
        const topPanel = explorerDom.filesPanel;
        const bottomPanel = explorerDom.outlinePanel;
        const container = document.querySelector('.explorer-content');
        
        if (!resizer || !topPanel || !bottomPanel || !container) return;
        
        let isDragging = false;
        
        resizer.addEventListener('mousedown', (e) => {
            isDragging = true;
            resizer.classList.add('dragging');
            document.body.style.cursor = 'ns-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
        
        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            
            const containerRect = container.getBoundingClientRect();
            const offsetY = e.clientY - containerRect.top;
            const containerHeight = containerRect.height;
            
            let topPercent = (offsetY / containerHeight) * 100;
            topPercent = Math.max(20, Math.min(80, topPercent));
            const bottomPercent = 100 - topPercent;
            
            topPanel.style.flex = `0 0 ${topPercent}%`;
            bottomPanel.style.flex = `0 0 ${bottomPercent}%`;
            
            localStorage.setItem('nos-explorer-ratio', topPercent);
        });
        
        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                resizer.classList.remove('dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
        
        const savedRatio = localStorage.getItem('nos-explorer-ratio');
        if (savedRatio) {
            const ratio = parseFloat(savedRatio);
            topPanel.style.flex = `0 0 ${ratio}%`;
            bottomPanel.style.flex = `0 0 ${100 - ratio}%`;
        }
    }

    function initPanelCollapse() {
        document.querySelectorAll('.explorer-panel-header').forEach(header => {
            header.addEventListener('click', () => {
                const panel = header.closest('.explorer-panel');
                panel.classList.toggle('collapsed');
            });
        });
    }

    function init() {
        if (explorerDom.viewProjectPane) {
            explorerDom.viewProjectPane.hidden = false;
            explorerDom.viewProjectPane.classList.add('active');
        }
        if (explorerDom.viewWorkspacePane) {
            explorerDom.viewWorkspacePane.hidden = true;
            explorerDom.viewWorkspacePane.classList.remove('active');
        }
        if (explorerDom.menuToggle) {
            explorerDom.menuToggle.addEventListener('click', () => {
                toggleExplorer();
            });
        }
        
        if (explorerDom.closeBtn) {
            explorerDom.closeBtn.addEventListener('click', toggleExplorer);
        }
        
        if (explorerDom.backdrop) {
            explorerDom.backdrop.addEventListener('click', toggleExplorer);
        }
        
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'e') {
                e.preventDefault();
                toggleExplorer();
            }
        });
        
        window.addEventListener('code-editor-loaded', (e) => {
            if (e.detail && e.detail.content) {
                updateOutlineFromCode(e.detail.content);
            }
        });
        
        window.addEventListener('code-editor-change', () => {
            if (window.__codeEditor) {
                updateOutlineFromCode(window.__codeEditor.value);
            }
        });
        
        initExplorerResizer();
        initPanelCollapse();
        initExplorerViewTabs();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.explorerPanel = {
        toggle: toggleExplorer,
        loadFileTree: loadFileTree,
        loadPluginsExplorerTree: loadPluginsExplorerTree,
        loadWorkspaceDriveTree: loadWorkspaceDriveTree,
        updateOutline: updateOutlineFromCode,
        loadOutlineForPath: loadOutline,
        setExplorerView: setExplorerView,
        /** Keeps explorerState.isOpen in sync when v2 dock forces the panel open without toggleExplorer. */
        setExplorerOpenState: function(open) {
            explorerState.isOpen = !!open;
        },
        invalidateSessionsTreeCache: function() {
            explorerState.workspaceTreeLoaded = false;
            if (explorerDom.workspaceTree && typeof loadWorkspaceDriveTree === 'function') {
                loadWorkspaceDriveTree();
            }
        }
    };
})();

/* ==========================================================================
   Tab System
   ========================================================================== */
(function() {
    'use strict';
    
    function showTab(name) {
        document.querySelectorAll('.panel-tab').forEach(function(p) { 
            p.classList.remove('active'); 
        });
        document.querySelectorAll('.panel-tabs button[data-tab]').forEach(function(b) { 
            b.classList.remove('active'); 
        });
        var tab = document.getElementById('tab-' + name);
        if (tab) tab.classList.add('active');
        document.querySelectorAll('.panel-tabs button[data-tab="' + name + '"]').forEach(function(btn) {
            btn.classList.add('active');
        });
    }
    
    document.querySelectorAll('.panel-tabs button[data-tab]').forEach(function(btn) {
        btn.addEventListener('click', function() { 
            showTab(btn.getAttribute('data-tab')); 
        });
    });
    
    window.showTab = showTab;
})();

/* Terminal group: sub-tabs (stream vs Output panel) */
(function() {
    'use strict';

    function showConsoleSubTab(name) {
        var root = document.getElementById('tab-console');
        if (!root) return;
        root.querySelectorAll('.console-sub-pane').forEach(function(p) {
            var on = p.id === 'console-subtab-' + name;
            p.classList.toggle('active', on);
        });
        root.querySelectorAll('.console-sub-tabs button[data-console-subtab]').forEach(function(b) {
            var on = b.getAttribute('data-console-subtab') === name;
            b.classList.toggle('active', on);
            if (b.getAttribute('role') === 'tab') b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('#tab-console .console-sub-tabs button[data-console-subtab]').forEach(function(btn) {
            btn.addEventListener('click', function() {
                showConsoleSubTab(btn.getAttribute('data-console-subtab'));
            });
        });
    });

    window.showConsoleSubTab = showConsoleSubTab;
})();

/* ==========================================================================
   Console menu: section visibility + layout (vertical / horizontal)
   ========================================================================== */
(function() {
    'use strict';
    var sectionMap = { terminal: 'console', chat: 'chat-model', history: 'history', workspace: 'workspace' };
    var sectionDefaults = { terminal: true, chat: true, history: true, workspace: true };
    var stored = localStorage.getItem('nos-console-sections');
    var visibleSections;
    if (stored) {
        try {
            visibleSections = JSON.parse(stored);
            if (visibleSections && visibleSections.workspace === undefined && visibleSections.code !== undefined) {
                visibleSections.workspace = visibleSections.code;
            }
            if (visibleSections && visibleSections.code !== undefined) {
                delete visibleSections.code;
            }
        } catch (e) {
            visibleSections = null;
        }
    }
    if (!visibleSections) visibleSections = Object.assign({}, sectionDefaults);
    Object.keys(sectionDefaults).forEach(function(k) {
        if (visibleSections[k] === undefined) visibleSections[k] = sectionDefaults[k];
    });
    /* Drop legacy keys so countVisibleSections / saved JSON stay consistent */
    Object.keys(visibleSections).forEach(function(k) {
        if (sectionDefaults[k] === undefined) delete visibleSections[k];
    });
    var layoutHorizontal = localStorage.getItem('nos-console-layout') === 'horizontal';

    function countVisibleSections() {
        var n = 0;
        Object.keys(visibleSections).forEach(function(k) { if (visibleSections[k]) n++; });
        return n;
    }

    function applySectionVisibility() {
        Object.keys(sectionMap).forEach(function(section) {
            var tabId = sectionMap[section];
            var tab = document.getElementById('tab-' + tabId);
            var visible = !!visibleSections[section];
            if (tab) tab.classList.toggle('section-hidden', !visible);
            if (tabId === 'workspace') {
                var wsGroup = document.getElementById('panel-tabs-workspace-group');
                if (wsGroup) wsGroup.classList.toggle('section-hidden', !visible);
            } else {
                document.querySelectorAll('.panel-tabs button[data-tab="' + tabId + '"]').forEach(function(btn) {
                    btn.classList.toggle('section-hidden', !visible);
                });
            }
        });
        var activeTab = document.querySelector('.panel-tabs button[data-tab].active');
        if (activeTab && activeTab.classList.contains('section-hidden')) {
            var firstVisible = document.querySelector('.panel-tabs button[data-tab]:not(.section-hidden)');
            if (firstVisible && window.showTab) window.showTab(firstVisible.getAttribute('data-tab'));
        }
        if (countVisibleSections() === 1) {
            layoutHorizontal = false;
            localStorage.setItem('nos-console-layout', 'horizontal');
            applyLayout();
            var menuLayoutV = document.getElementById('menu-layout-vertical');
            var menuLayoutH = document.getElementById('menu-layout-horizontal');
            if (menuLayoutV) menuLayoutV.classList.remove('active');
            if (menuLayoutH) menuLayoutH.classList.add('active');
        }
    }

    function applyLayout() {
        document.body.classList.toggle('console-layout-horizontal', layoutHorizontal);
    }

    document.addEventListener('DOMContentLoaded', function() {
        applySectionVisibility();
        applyLayout();

        document.querySelectorAll('.menu-section-toggle').forEach(function(btn) {
            var section = btn.getAttribute('data-section');
            if (section !== null) btn.classList.toggle('active', !!visibleSections[section]);
            btn.addEventListener('click', function() {
                if (!section) return;
                visibleSections[section] = !visibleSections[section];
                btn.classList.toggle('active', !!visibleSections[section]);
                localStorage.setItem('nos-console-sections', JSON.stringify(visibleSections));
                applySectionVisibility();
            });
        });

        var menuLayoutV = document.getElementById('menu-layout-vertical');
        var menuLayoutH = document.getElementById('menu-layout-horizontal');
        if (menuLayoutV) {
            menuLayoutV.addEventListener('click', function() {
                layoutHorizontal = true;
                localStorage.setItem('nos-console-layout', 'vertical');
                document.body.classList.add('console-layout-horizontal');
                menuLayoutV.classList.add('active');
                if (menuLayoutH) menuLayoutH.classList.remove('active');
                if (window.closeAllMenus) window.closeAllMenus();
            });
        }
        if (menuLayoutH) {
            menuLayoutH.addEventListener('click', function() {
                layoutHorizontal = false;
                localStorage.setItem('nos-console-layout', 'horizontal');
                document.body.classList.remove('console-layout-horizontal');
                menuLayoutH.classList.add('active');
                if (menuLayoutV) menuLayoutV.classList.remove('active');
                if (window.closeAllMenus) window.closeAllMenus();
            });
        }
        if (layoutHorizontal) { if (menuLayoutV) menuLayoutV.classList.add('active'); if (menuLayoutH) menuLayoutH.classList.remove('active'); } else { if (menuLayoutH) menuLayoutH.classList.add('active'); if (menuLayoutV) menuLayoutV.classList.remove('active'); }
    });

    /* Chat: attach file + add URL (placeholder handlers) */
    var chatAttach = document.getElementById('chat-attach');
    var chatAddUrl = document.getElementById('chat-add-url');
    var chatFileInput = document.getElementById('chat-file-input');
    if (chatAttach && chatFileInput) {
        chatAttach.addEventListener('click', function() { chatFileInput.click(); });
    }
    if (chatAddUrl) {
        chatAddUrl.addEventListener('click', function() {
            var url = window.prompt('Add URL:', 'https://');
            if (url) {
                var input = document.getElementById('chat-input');
                if (input) input.value = (input.value ? input.value + '\n' : '') + url;
            }
        });
    }
})();

/* Console Application Core: see plugin-console-core.js */

/* ==========================================================================
   Code Editor Application
   ========================================================================== */
(function() {
    'use strict';

    const codeState = {
        editor: null,
        editorDirty: false,
        lastSavedValue: '',
        userEditEnabled: false,
        currentFile: null,
        runMode: localStorage.getItem('nos-run-mode') || 'dev',
        outputMode: localStorage.getItem('nos-output-mode') || 'debug',
        saveStatus: 'idle'  // idle | dirty | success | error
    };

    const codeDom = {
        btnEditToggle: document.getElementById('btn-edit-toggle'),
        btnSaveFile: document.getElementById('btn-save-file'),
        btnRunCode: document.getElementById('btn-run-code'),
        btnAiAssist: document.getElementById('btn-ai-assist'),
        cursorPos: document.getElementById('code-cursor-pos'),
        editorContainer: document.getElementById('code-editor'),
        splitBtnEdit: document.getElementById('split-btn-edit'),
        splitBtnSave: document.getElementById('split-btn-save'),
        splitBtnRun: document.getElementById('split-btn-run'),
        splitBtnAi: document.getElementById('split-btn-ai'),
        splitEditorContainer: document.getElementById('split-code-editor')
    };

    const ICONS = {
        EDIT: '✎',
        LOCK: '🔒',
        SAVE: '💾',
        SAVED: '✓',
        SAVE_WARNING: '⚠',
        SAVE_ERROR: '✗'
    };

    const defaultTemplate = `# =============================================================================
# Hythera Plugin Editor
# =============================================================================
#
# This editor allows you to create and modify Node and Workflow plugins.
#
# GETTING STARTED:
# ----------------
#
# To CREATE a new plugin, use the console command:
#
#     create node <node_id> --class ClassName --path <module.path>
#     create workflow <wf_id> --class ClassName --path <module.path>
#
# --class and --path are REQUIRED. Example:
#     create node my_processor --class MyProcessorNode --path nodes.custom.my_processor
#
# To OPEN an existing plugin for editing:
#
#     open node <module_path>
#     open workflow <module_path>
#
# Example:
#     open node nos.plugins.nodes.old.developer.my_node
#
# After creating or opening a plugin, its code will appear here for editing.
# Use the SAVE button to save changes, then REGISTER the plugin to activate it.
#
# For more commands, type 'help' in the console.
# =============================================================================
`;

    function updateSaveButtonIcon() {
        const btns = [codeDom.btnSaveFile, codeDom.splitBtnSave].filter(Boolean);
        btns.forEach(function(btn) {
            btn.classList.remove('saved', 'save-error', 'save-dirty');
            if (codeState.saveStatus === 'error') {
                btn.textContent = ICONS.SAVE_ERROR;
                btn.title = 'Save failed';
                btn.classList.add('save-error');
            } else if (codeState.editorDirty || codeState.saveStatus === 'dirty') {
                btn.textContent = ICONS.SAVE_WARNING;
                btn.title = 'Unsaved changes';
                btn.classList.add('save-dirty');
            } else {
                btn.textContent = ICONS.SAVED;
                btn.title = 'Saved';
                btn.classList.add('saved');
            }
        });
    }

    function setEditorSavedState(success) {
        codeState.editorDirty = false;
        if (codeState.editor && codeState.editor.value != null) {
            codeState.lastSavedValue = String(codeState.editor.value);
        }
        codeState.saveStatus = success !== false ? 'idle' : 'error';
        updateSaveButtonIcon();
    }

    function updateEditToggleButton() {
        if (!codeDom.btnEditToggle) return;
        const editable = codeState.userEditEnabled;
        codeDom.btnEditToggle.title = editable ? 'Disable editing' : 'Enable editing';
        codeDom.btnEditToggle.textContent = editable ? ICONS.LOCK : ICONS.EDIT;
        codeDom.btnEditToggle.classList.toggle('active', editable);
    }

    function applyEditorEditability() {
        if (!codeState.editor) return;
        if (!codeDom.editorContainer) return;
        var editable = codeState.userEditEnabled && !isPluginReadOnly();
        codeState.editor.readOnly = !editable;
        codeDom.editorContainer.setAttribute('data-readonly', !editable);
        updateEditToggleButton();
        
        if (window.__splitCodeEditor) {
            window.__splitCodeEditor.readOnly = !editable;
        }
        if (codeDom.splitEditorContainer) {
            codeDom.splitEditorContainer.setAttribute('data-readonly', !editable);
        }
        if (codeDom.splitBtnEdit) {
            codeDom.splitBtnEdit.classList.toggle('active', codeState.userEditEnabled);
            codeDom.splitBtnEdit.textContent = codeState.userEditEnabled ? ICONS.LOCK : ICONS.EDIT;
            codeDom.splitBtnEdit.title = codeState.userEditEnabled ? 'Disable editing' : 'Enable editing';
        }
    }

    function applyEditSaveVisibility() {
        var readOnly = isPluginReadOnly();
        var editBtns = [codeDom.btnEditToggle, codeDom.splitBtnEdit].filter(Boolean);
        var saveBtns = [codeDom.btnSaveFile, codeDom.splitBtnSave].filter(Boolean);
        editBtns.forEach(function(btn) {
            btn.classList.toggle('toolbar-readonly', readOnly);
            btn.disabled = readOnly;
        });
        saveBtns.forEach(function(btn) {
            btn.style.display = readOnly ? 'none' : '';
        });
        applyEditorEditability();
        if (!readOnly) updateSaveButtonIcon();
    }

    function isPluginReadOnly() {
        var status = (codeState.currentFile && codeState.currentFile.registration_status) || '';
        return status === 'OK' || status === 'Pub';
    }

    function handleEditToggle() {
        if (isPluginReadOnly()) {
            var msg = 'Plugin is registered (OK) or published (Pub). To edit: unreg the plugin first, then open and run in direct mode.';
            if (window.HytheraConsole && window.HytheraConsole.addSystemMessage) {
                window.HytheraConsole.addSystemMessage(msg, 'warning');
            } else {
                console.warn(msg);
            }
            return;
        }
        codeState.userEditEnabled = !codeState.userEditEnabled;
        applyEditorEditability();
    }

    function handleSaveFile() {
        if (!codeState.editor) {
            console.warn('Editor not ready');
            return;
        }
        var content = codeState.editor.value || '';
        if (!content.trim()) {
            console.warn('No content to save');
            return;
        }
        var fileInfo = codeState.currentFile;
        if (!fileInfo || !fileInfo.module_path || !fileInfo.node_id || !fileInfo.class_name) {
            codeState.saveStatus = 'error';
            updateSaveButtonIcon();
            if (window.HytheraConsole && window.HytheraConsole.addSystemMessage) {
                window.HytheraConsole.addSystemMessage('Cannot save: open a plugin first (open node <module_path>).', 'error');
            }
            return;
        }
        if (isPluginReadOnly()) {
            codeState.saveStatus = 'error';
            updateSaveButtonIcon();
            if (window.HytheraConsole && window.HytheraConsole.addSystemMessage) {
                window.HytheraConsole.addSystemMessage('Cannot save: plugin is OK/Pub. Unreg first to edit.', 'error');
            }
            return;
        }
        var socket = (window.HytheraConsole && window.HytheraConsole.state && window.HytheraConsole.state.socket);
        if (!socket || !socket.connected) {
            codeState.saveStatus = 'error';
            updateSaveButtonIcon();
            if (window.HytheraConsole && window.HytheraConsole.addSystemMessage) {
                window.HytheraConsole.addSystemMessage('Not connected. Cannot save.', 'error');
            }
            return;
        }
        codeState.saveStatus = 'dirty';
        updateSaveButtonIcon();
        if (!document.body.classList.contains('layout-split')) {
            var consoleTabBtn = document.querySelector('.panel-tabs button[data-tab="console"]');
            if (consoleTabBtn) consoleTabBtn.click();
        }
        window.dispatchEvent(new CustomEvent('console-command', {
            detail: {
                command: 'save',
                save_payload: {
                    content: content,
                    module_path: fileInfo.module_path,
                    node_id: fileInfo.node_id,
                    class_name: fileInfo.class_name,
                    plugin_type: fileInfo.plugin_type || 'node'
                }
            }
        }));
    }

    function buildSavePayload() {
        if (!codeState.editor) return { error: 'Editor not ready' };
        var content = (codeState.editor && codeState.editor.value) || '';
        if (!content.trim()) return { error: 'No content to save' };
        var fileInfo = codeState.currentFile;
        var pluginType = fileInfo && (fileInfo.plugin_type || 'node');
        var pluginId = fileInfo && (fileInfo.node_id || fileInfo.workflow_id);
        if (!fileInfo || !fileInfo.module_path || !pluginId || !fileInfo.class_name) {
            return { error: 'Cannot save: open a plugin first (open node <module_path> or open workflow <module_path>).' };
        }
        if (isPluginReadOnly()) {
            return { error: 'Cannot save: plugin is OK/Pub. Unreg first to edit.' };
        }
        var payload = {
            content: content,
            module_path: fileInfo.module_path,
            class_name: fileInfo.class_name,
            plugin_type: pluginType
        };
        if (pluginType === 'workflow') {
            payload.workflow_id = pluginId;
        } else {
            payload.node_id = pluginId;
        }
        return { payload: payload };
    }

    function prepareSaveForSend() {
        codeState.saveStatus = 'dirty';
        updateSaveButtonIcon();
    }

    if (window.HytheraConsole) {
        window.HytheraConsole.getSavePayload = buildSavePayload;
        window.HytheraConsole.prepareSaveForSend = prepareSaveForSend;
    }

    function handleRunCode() {
        if (!codeState.editor) {
            console.warn('Editor not ready');
            return;
        }
        
        const runMode = codeState.runMode;
        const outputMode = codeState.outputMode;
        const fileInfo = codeState.currentFile;
        
        if (!fileInfo) {
            console.warn('No file loaded. Open a plugin first.');
            appendToConsole('error', 'No file loaded. Use "open node <module_path>" or "open workflow <module_path>" first.');
            return;
        }
        
        // Build output mode flag (--debug or --trace)
        const outputModeFlag = outputMode === 'trace' ? '--trace' : '--debug';
        const isWorkflow = fileInfo.module_path && fileInfo.module_path.includes('.workflows.');
        let cmd = '';

        if (isWorkflow) {
            if (runMode === 'dev') {
                if (!fileInfo.module_path) {
                    appendToConsole('error', 'Cannot run workflow in dev: missing module_path.');
                    return;
                }
                const cls = fileInfo.class_name || classNameForRun(fileInfo.module_path, true);
                cmd = `run workflow dev ${fileInfo.module_path} ${cls} --sync ${outputModeFlag}`;
            } else {
                if (!fileInfo.workflow_id) {
                    appendToConsole('error', 'Cannot run workflow in prod: missing workflow_id. Register the workflow first.');
                    return;
                }
                cmd = `run workflow prod ${fileInfo.workflow_id} --sync ${outputModeFlag}`;
            }
        } else {
            if (runMode === 'dev') {
                if (!fileInfo.module_path) {
                    appendToConsole('error', 'Cannot run in dev mode: missing module_path.');
                    return;
                }
                const cls = fileInfo.class_name || classNameForRun(fileInfo.module_path, false);
                cmd = `run node dev ${fileInfo.module_path} ${cls} --sync ${outputModeFlag}`;
            } else if (runMode === 'prod') {
                if (!fileInfo.node_id) {
                    appendToConsole('error', 'Cannot run in prod mode: missing node_id. Register the plugin first.');
                    return;
                }
                cmd = `run node prod ${fileInfo.node_id} --sync ${outputModeFlag}`;
            }
        }
        
        console.log('Run command:', cmd);
        
        if (!document.body.classList.contains('layout-split')) {
            const consoleTabBtn = document.querySelector('.panel-tabs button[data-tab="console"]');
            if (consoleTabBtn) {
                consoleTabBtn.click();
            }
        }
        
        window.dispatchEvent(new CustomEvent('console-command', { 
            detail: { command: cmd } 
        }));
    }
    
    function appendToConsole(type, message) {
        const output = document.getElementById('console-output');
        if (!output) return;
        
        const entry = document.createElement('div');
        entry.className = `log-entry level-${type}`;
        entry.innerHTML = `<span class="log-message">${message}</span>`;
        output.appendChild(entry);
        output.scrollTop = output.scrollHeight;
    }
    
    function extractClassName(modulePath) {
        if (!modulePath) return null;
        const parts = modulePath.split('.');
        const moduleName = parts[parts.length - 1];
        const className = moduleName
            .split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join('');
        if (className.endsWith('Node') || className.endsWith('Workflow')) {
            return className;
        }
        return className + 'Node';
    }

    /** Derive class name from module path for run command (Node or Workflow suffix). */
    function classNameForRun(modulePath, isWorkflow) {
        if (!modulePath) return '';
        const parts = modulePath.split('.');
        const moduleName = parts[parts.length - 1];
        const base = moduleName.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('');
        if (base.endsWith('Node') || base.endsWith('Workflow')) return base;
        return base + (isWorkflow ? 'Workflow' : 'Node');
    }
    
    function setRunMode(mode) {
        codeState.runMode = mode;
        localStorage.setItem('nos-run-mode', mode);
        
        document.querySelectorAll('[data-runmode]').forEach(function(opt) {
            opt.classList.toggle('active', opt.dataset.runmode === mode);
        });
        
        console.log('Run mode set to:', mode);
    }

    function handleAiAssist() {
        console.log('AI Code Assistant - Coming soon!');
    }

    function initCodeEditor() {
        if (!codeDom.editorContainer) return;
        if (window.__codeEditor) {
            codeState.editor = window.__codeEditor;
            initEditorState();
        } else {
            window.addEventListener('codemirror-ready', function onReady() {
                window.removeEventListener('codemirror-ready', onReady);
                if (!codeDom.editorContainer) return;
                codeState.editor = window.__codeEditor;
                initEditorState();
            });
        }
    }

    function initEditorState() {
        if (!codeState.editor) return;
        if (!codeDom.editorContainer) return;
        
        codeState.editor.value = defaultTemplate;
        setEditorSavedState();
        applyEditorEditability();
        
        if (window.__splitCodeEditor) {
            window.__splitCodeEditor.value = defaultTemplate;
        }
    }

    function init() {
        if (codeDom.btnEditToggle) {
            codeDom.btnEditToggle.addEventListener('click', handleEditToggle);
        }
        if (codeDom.btnSaveFile) {
            codeDom.btnSaveFile.addEventListener('click', handleSaveFile);
        }
        
        if (codeDom.btnRunCode) {
            codeDom.btnRunCode.addEventListener('click', handleRunCode);
        }
        
        if (codeDom.btnAiAssist) {
            codeDom.btnAiAssist.addEventListener('click', handleAiAssist);
        }

        if (codeDom.splitBtnEdit) {
            codeDom.splitBtnEdit.addEventListener('click', function() {
                handleEditToggle();
                this.classList.toggle('active', codeState.userEditEnabled);
                this.textContent = codeState.userEditEnabled ? ICONS.LOCK : ICONS.EDIT;
            });
        }
        if (codeDom.splitBtnSave) {
            codeDom.splitBtnSave.addEventListener('click', handleSaveFile);
        }
        
        if (codeDom.splitBtnRun) {
            codeDom.splitBtnRun.addEventListener('click', handleRunCode);
        }
        
        if (codeDom.splitBtnAi) {
            codeDom.splitBtnAi.addEventListener('click', handleAiAssist);
        }
        
        window.addEventListener('code-loaded-from-console', function(e) {
            if (!e.detail) {
                codeState.currentFile = null;
                codeState.saveStatus = 'idle';
                codeState.editorDirty = false;
                applyEditSaveVisibility();
                applyEditorEditability();
                updateSaveButtonIcon();
                return;
            }
            codeState.currentFile = {
                module_path: e.detail.module_path || null,
                class_name: extractClassName(e.detail.module_path) || null,
                node_id: e.detail.id || null,
                file_path: e.detail.file_path || null,
                plugin_type: e.detail.action === 'open_workflow' ? 'workflow' : 'node',
                registration_status: e.detail.registration_status || null
            };
            codeState.saveStatus = 'idle';
            codeState.editorDirty = false;
            applyEditSaveVisibility();
            applyEditorEditability();
            updateSaveButtonIcon();
            console.log('File loaded:', codeState.currentFile);
        });
        
        document.addEventListener('keydown', function(e) {
            if (e.key === 'F5') {
                e.preventDefault();
                handleRunCode();
            }
        });
        
        window.addEventListener('run-mode-changed', function(e) {
            if (e.detail && e.detail.mode) {
                codeState.runMode = e.detail.mode;
                console.log('Run mode changed to:', codeState.runMode);
            }
        });

        window.addEventListener('output-mode-changed', function(e) {
            if (e.detail && e.detail.mode) {
                codeState.outputMode = e.detail.mode;
                console.log('Output mode changed to:', codeState.outputMode);
            }
        });

        window.addEventListener('code-editor-change', function() {
            codeState.editorDirty = true;
            codeState.saveStatus = 'dirty';
            updateSaveButtonIcon();
        });
        
        window.addEventListener('split-code-editor-change', function() {
            codeState.editorDirty = true;
            codeState.saveStatus = 'dirty';
            updateSaveButtonIcon();
        });

        window.addEventListener('code-save-success', function() {
            setEditorSavedState(true);
        });
        window.addEventListener('code-save-error', function() {
            setEditorSavedState(false);
        });

        initCodeEditor();
    }
    

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
