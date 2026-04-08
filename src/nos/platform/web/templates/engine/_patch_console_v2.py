# One-off: patch engine_console_v2.html with workbench layout. Run from repo root or any cwd.
from pathlib import Path

HERE = Path(__file__).resolve().parent
path = HERE / "engine_console_v2.html"
frag_path = HERE / "_console_v2_workbench.html"

s = path.read_text(encoding="utf-8")
workbench = frag_path.read_text(encoding="utf-8")

old_ex = """    <!-- Explorer Offcanvas -->
    <div class=\"explorer-backdrop\" id=\"explorer-backdrop\"></div>
    <aside class=\"explorer-offcanvas\" id=\"explorer-offcanvas\">
        <div class=\"explorer-header\">
            <span class=\"explorer-title\">Explorer</span>
            <button class=\"explorer-close\" id=\"explorer-close\" title=\"Close\">&times;</button>
        </div>
        <div class=\"explorer-content\">
            <!-- Top: Project (repo tree) | @ Workspace (~/.nos/drive/@user — .nos sessions) -->
            <div class=\"explorer-panel\" id=\"explorer-files-panel\" style=\"flex: 1;\">
                <div class=\"explorer-sidebar-head\">
                    <nav class=\"explorer-view-tabs\" role=\"tablist\" aria-label=\"Explorer source\">
                        <button type=\"button\" role=\"tab\" class=\"explorer-view-tab active\" data-explorer-view=\"project\" id=\"explorer-tab-project\" aria-selected=\"true\" title=\"Plugin packages (project layout)\">Project</button>
                        <button type=\"button\" role=\"tab\" class=\"explorer-view-tab\" data-explorer-view=\"workspace\" id=\"explorer-tab-workspace\" aria-selected=\"false\" title=\"Saved sessions under ~/.nos/drive/@user — double-click .nos to restore\">@ Workspace</button>
                    </nav>
                </div>
                <div class=\"explorer-panel-content explorer-panel-content--tabs\">
                    <div class=\"explorer-view-pane active\" id=\"explorer-view-project\" role=\"tabpanel\" aria-labelledby=\"explorer-tab-project\">
                        <p class=\"explorer-project-hint\" id=\"explorer-project-hint\" hidden></p>
                        <div class=\"file-tree file-tree--project\" id=\"file-tree\">
                            <div class=\"tree-muted\">Open Explorer to load the project tree.</div>
                        </div>
                    </div>
                    <div class=\"explorer-view-pane\" id=\"explorer-view-workspace\" role=\"tabpanel\" aria-labelledby=\"explorer-tab-workspace\">
                        <p class=\"explorer-workspace-hint\" id=\"explorer-workspace-hint\"></p>
                        <div class=\"file-tree file-tree--drive explorer-drive-tree\" id=\"explorer-workspace-tree\">
                            <div class=\"tree-muted\">Open this tab to list <code>.nos</code> sessions. Double-click a file to restore Terminal + Workspace.</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Resizer -->
            <div class=\"explorer-resizer\" id=\"explorer-resizer\"></div>
            
            <!-- Outline Panel -->
            <div class=\"explorer-panel\" id=\"explorer-outline-panel\" style=\"flex: 1;\">
                <div class=\"explorer-panel-header\" data-panel=\"outline\">
                    <span class=\"collapse-icon\">▼</span>
                    <span>Outline</span>
                </div>
                <div class=\"explorer-panel-content\">
                    <div class=\"outline-tree\" id=\"outline-tree\">
                        <div class=\"outline-empty\">Open a file to see its outline</div>
                    </div>
                </div>
            </div>
        </div>
    </aside>

    """

if old_ex not in s:
    raise SystemExit("old explorer block not found")

s = s.replace(old_ex, '    <div class="explorer-backdrop" id="explorer-backdrop"></div>\n\n    ')

start = s.index('        <div class="console-body-main">')
end = s.index('        <!-- end .console-body-main -->') + len('        <!-- end .console-body-main -->')
s = s[:start] + workbench + s[end:]

path.write_text(s, encoding="utf-8")
print("patched", path)
