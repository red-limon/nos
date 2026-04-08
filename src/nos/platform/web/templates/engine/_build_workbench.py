from pathlib import Path

HERE = Path(__file__).resolve().parent
frag = (HERE / "_console_v2_body_fragment.html").read_text(encoding="utf-8").splitlines()
# Lines in file are 1-based; index 138 = line 139
inner = frag[138:431]  # line 139-431 inclusive (0-based 138 to 430)
inner[0] = "        <div class=\"console-body-main\">"
inner.insert(1, "        <div class=\"console-v2-workbench\">")
# last line was '        </div>' closing workbench — need extra close for body-main after tab-history
end_comment = "        <!-- end .console-body-main -->"
tab_hist = frag[433:443]  # tab-history block (lines 434-443)
out = "\n".join(inner) + "\n" + "\n".join(tab_hist) + "\n        </div>\n" + end_comment + "\n"
(HERE / "_console_v2_workbench.html").write_text(out, encoding="utf-8")
print("written", HERE / "_console_v2_workbench.html", "lines", len(out.splitlines()))
