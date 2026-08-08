# 2026-08-01 周报模板执行契约

- Reference: `F:\\project\\Village_Planning_Agent\\docs\\weekly-reports\\2026-08-01.docx`
- SHA-256: `2bfc8cc5573c057448ce6c10c26bfaf9e87e454e338dc732a0ce4955a2d24e9d`
- Reference has 1 section, portrait US Letter page (8.50 x 11.00 in), margins L/R 1.25 in and T/B 1.00 in, and one inline image.
- Rendering was attempted with the packaged renderer but LibreOffice/soffice was unavailable in this environment. The embedded map image was inspected directly and is a single 6.3 x 7.945 in PNG.

## Visual system

- Normal: 宋体, 12 pt, 4 pt paragraph-after, 20 pt line spacing.
- Title: Heading 1 paragraph, centered; direct run override 黑体 18 pt.
- Section heading: Heading 2 paragraph; direct run override 黑体 13 pt, inherited blue heading color.
- Body: Normal paragraphs, no direct paragraph formatting; selected labels are bold run prefixes.
- Image caption: Normal paragraph centered; image paragraph centered; template image slot is optional and may be removed when the new report has no suitable figure.
- No tables, headers, footers, lists, fields, comments, or content controls.

## Content flow and slots

1. Centered title `周报（YYYY-MM-DD ~ YYYY-MM-DD）`.
2. `一、实现了什么`: five concise outcome paragraphs with bold labels.
3. `二、实现思路`: four concise design-rationale paragraphs with bold labels.
4. `三、实现成果`: optional centered figure/caption, followed by one or two result paragraphs.
5. `四、未来优化`: four numbered paragraphs with bold labels.

For the 2026-08-08 report, reuse the same typography and page geometry, remove the stale 2026-08-01 map image, and fill the four sections with facts supported by Git history and committed audit records. The retained 2026-08-01 DOCX is preserve-only and must remain byte-for-byte unchanged.
