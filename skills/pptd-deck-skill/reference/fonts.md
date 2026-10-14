# Native local fonts

Choose one installed multilingual family for the body. Declare the same fontFamily
in PPTD and map the actual regular/bold/italic font files in fonts.json. TTC files
need a face index. Missing glyphs are errors. Synthetic styles are allowed only
when explicitly enabled and are disclosed as approximate. Native export records
system family names without embedding. Math uses Office Math with Cambria Math;
Pillow QA may use another mapped math font and has approximate spacing.

Windows files normally live in C:/Windows/Fonts; use Microsoft YaHei or another
installed CJK family for Chinese. Linux uses /usr/share/fonts and macOS uses
/System/Library/Fonts. Read windows.md for PowerShell and TTC details. Project
paths use forward slashes; local font mapping paths are OS paths. After changing
any font file or mapping, rerun prepare/review/export. Do not bundle proprietary
font binaries or download a vendor runtime to enable embedding.
