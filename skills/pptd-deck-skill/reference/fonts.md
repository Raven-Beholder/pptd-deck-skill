# Native project fonts

Use Source Han Sans SC for Chinese body text, Source Han Serif SC for serif text,
Inter or Source Sans 3 for Latin text, JetBrains Mono for code, and STIX Two Math
for formulas. The catalog has 16 families. These official resources use
OFL-1.1, allowing bundling and redistribution with their copyright and license
notices. Preserve the original names and font bytes. Do not sell font files by
themselves or remove notices. Fonts retain OFL-1.1; the document does not become
OFL-licensed. See the official licenses:

| Catalog IDs | Families | Official license source |
| --- | --- | --- |
| `source-han-sans`, `source-han-sans-tc` | Source Han Sans SC / TC | [Adobe](https://github.com/adobe-fonts/source-han-sans/blob/release/LICENSE.txt) |
| `source-han-serif`, `source-han-serif-tc` | Source Han Serif SC / TC | [Adobe](https://github.com/adobe-fonts/source-han-serif/blob/release/LICENSE.txt) |
| `inter` | Inter | [Inter](https://github.com/rsms/inter/blob/master/LICENSE.txt) |
| `jetbrains-mono` | JetBrains Mono | [JetBrains](https://github.com/JetBrains/JetBrainsMono/blob/master/OFL.txt) |
| `source-sans-3` | Source Sans 3 | [Adobe](https://github.com/adobe-fonts/source-sans/blob/release/LICENSE.md) |
| `source-serif-4` | Source Serif 4 | [Adobe](https://github.com/adobe-fonts/source-serif/blob/release/LICENSE.md) |
| `lato` | Lato | [Google Fonts](https://github.com/google/fonts/blob/main/ofl/lato/OFL.txt) |
| `carlito` | Carlito | [Google Fonts](https://github.com/google/fonts/blob/main/ofl/carlito/OFL.txt) |
| `caladea` | Caladea | [Google Fonts](https://github.com/google/fonts/blob/main/ofl/caladea/OFL.txt) |
| `montserrat` | Montserrat | [Montserrat](https://github.com/JulietaUla/Montserrat/blob/master/OFL.txt) |
| `ibm-plex-sans`, `ibm-plex-serif`, `ibm-plex-mono` | IBM Plex Sans / Serif / Mono | [IBM](https://github.com/IBM/plex/blob/master/LICENSE.txt) |
| `stix-two-math` | STIX Two Math | [Google Fonts](https://github.com/google/fonts/blob/main/ofl/stixtwomath/OFL.txt) |

The editor's Project Management and generation CLI offer these families. They download immutable
official resources listed in `font-catalog.json`, checks their SHA-256 hashes,
and stores complete fonts and license notices in the current project. No fonts
are bundled with the repository release, installed into the OS, or fetched by
the browser from a CDN. Once added, the project works offline.

The native extension uses relative static TTF/OTF paths, not remote CSS:

```yaml
customFonts:
  - family: Source Han Sans SC
    src: fonts/SourceHanSansSC-Regular.otf
    weight: 400
    style: normal
    license: fonts/source-han-sans-OFL.txt
  - family: Source Han Sans SC
    src: fonts/SourceHanSansSC-Bold.otf
    weight: 700
    style: normal
    license: fonts/source-han-sans-OFL.txt
```

Use the real family name from the font's name table. Supply regular, bold,
italic and boldItalic faces used by the deck. Native weights are 400 or 700;
`style` is normal or italic. Metadata is checked against the file. Text with no
explicit family uses the first regular project text face; without project fonts,
the previous defaults are retained. Explicit `fontFamily` values still win.
Each font is limited to 32 MiB and the complete portable project to 100 MiB.
TTC, WOFF and variable fonts are currently unsupported. The importer checks
OS/2 embedding rights and rejects restricted, preview-only or bitmap-only
fonts for this editable workflow. Permission bits alone do not replace the
font's actual distribution license.

The editor loads these fonts before preview and carries them in SVG exports.
Project copies and ZIPs include declared fonts and license files. PNG records
the rendered appearance. PPTX export with `--embed-fonts` stores full EOT font
parts, family/style references, full license notices and editable embedding settings. Missing used
families/styles stop export. Font data, permissions and relationships are
validated before publication. Office/WPS/Keynote rendering is a separate check;
not every application supports embedded fonts equally.

## Native layout QA

For portable generation, select a catalog body family and optional additional
families. CJK fonts include real regular/bold faces; Latin text families include
regular/bold/italic/boldItalic. Choose a family that covers the deck's languages.

```sh
python "$SKILL_DIR/scripts/pipeline.py" init --project "$PROJECT" --topic "数据库入门" --pages 12 --font-family source-han-sans --extra-font jetbrains-mono
python "$SKILL_DIR/scripts/local-export/native_font_catalog.py" list
python "$SKILL_DIR/scripts/local-export/native_font_catalog.py" add "$PROJECT" --family source-serif-4 --family inter
```

Run these with the selected isolated environment described in SKILL.md.
The Node launcher exposes the same catalog through `fonts list` and
`fonts add PROJECT --family ID`. For an existing project without `fonts.json`,
add `--write-config` to write relative QA mappings. Existing mappings are never
overwritten. Merge new mappings deliberately, then rerun prepare/review/export.

`init --font-family` includes STIX Two Math by default, or accepts an explicit
`--math-family` catalog ID. Its `customFonts` entry uses `role: math`; the file
must have an OpenType MATH table. This selects the same family for editor
formulas and Office Math, and allows its regular face to embed math alphabets.
Pillow QA approximates math spacing and discloses synthetic math styles.

An installed multilingual family is also supported. Declare the same fontFamily
in PPTD and map real regular/bold/italic files in `fonts.json`. TTC files need a
face index. Missing glyphs are errors. Synthetic styles require an explicit
`syntheticStyles: true` and are disclosed as approximate. Without `--embed-fonts`,
native export records family names only. Without a project math face, Office
uses Cambria Math; Pillow can use another mapped math font.

Windows files normally live in C:/Windows/Fonts; use Microsoft YaHei or another
installed CJK family for Chinese. Linux uses /usr/share/fonts and macOS uses
/System/Library/Fonts. Read windows.md for PowerShell and TTC details. Project
paths use forward slashes; local font mapping paths are OS paths. After changing
any font file or mapping, rerun prepare/review/export. Do not bundle proprietary
font binaries or download a vendor runtime to enable embedding.
