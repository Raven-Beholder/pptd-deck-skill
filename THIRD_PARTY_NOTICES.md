# License and dependencies

Project license: MIT. The full license and upstream copyright notice follow below.

## Development reference

Development referenced [open-pptd](https://github.com/Shingwha/open-pptd).

## External dependencies

These packages are installed separately and keep their own licenses:

- PyYAML 6.0.3 — MIT: https://github.com/yaml/pyyaml
- Pillow 12.0.0 — HPND and component notices: https://github.com/python-pillow/Pillow

Python and Node are external runtimes. System fonts are read from the host and
are not included in release packages. Presentation materials retain their own rights.

## Optional project fonts

The editor and generation CLI can download Source Han Sans/Serif SC and TC,
Source Sans 3 and Source Serif 4 from Adobe; Inter from the Inter project;
JetBrains Mono from JetBrains; Lato, Carlito, Caladea and STIX Two Math from
Google Fonts; Montserrat from its official project; and IBM Plex Sans/Serif/Mono
from IBM. These fonts
retain SIL Open Font License 1.1. They are not bundled with this repository or
the source-only review archives. Explicit downloads use immutable official
resources with recorded hashes. Their full copyright and license notices are
saved with the project and retained in portable copies and embedded PPTX.
Font bytes and family names are not modified. See
`skills/pptd-deck-skill/reference/fonts.md` and the editor's `font-catalog.json`.

The independent font reader and EOT writer refer to the Microsoft OpenType
OS/2/name specifications and the Microsoft EOT format submission:
https://learn.microsoft.com/en-us/typography/opentype/spec/os2
https://www.w3.org/submissions/EOT/

## MIT license

MIT License

Copyright (c) 2026 Binaryify Zhuang

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
