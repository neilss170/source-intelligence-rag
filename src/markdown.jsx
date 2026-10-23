// Renders the Markdown subset models write (headings, bold, italics, inline
// code, lists, tables, rules) as React elements. Never uses raw HTML, so
// document text quoted in an answer can't inject markup.

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\s][^*\n]*\*|\[\d+\])/g;

function inline(text, keyPrefix) {
  return text
    .split(INLINE)
    .filter((part) => part !== "")
    .map((part, index) => {
      const key = `${keyPrefix}-${index}`;
      if (/^`[^`]+`$/.test(part)) return <code key={key}>{part.slice(1, -1)}</code>;
      if (/^(\*\*|__).+\1$/.test(part)) return <strong key={key}>{part.slice(2, -2)}</strong>;
      if (/^\*[^*].*\*$/.test(part)) return <em key={key}>{part.slice(1, -1)}</em>;
      const cite = /^\[(\d+)\]$/.exec(part);
      if (cite) return <sup className="cite-mark" key={key}>{cite[1]}</sup>;
      // An unclosed marker, usually mid-stream: drop it rather than show it.
      return part.replace(/\*\*|__/g, "");
    });
}

function withBreaks(lines, keyPrefix) {
  return lines.flatMap((line, index) => [
    ...(index > 0 ? [<br key={`${keyPrefix}-br${index}`} />] : []),
    ...inline(line, `${keyPrefix}-${index}`),
  ]);
}

const BULLET = /^\s*[-*•]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;
const HEADING = /^\s*#{1,6}\s+/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_DIVIDER = /^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*:?-*:?\s*\|?\s*$/;

function cells(row) {
  return row.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
}

export function Markdown({ text }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let index = 0;

  const take = (test) => {
    const taken = [];
    while (index < lines.length && test(lines[index])) taken.push(lines[index++]);
    return taken;
  };

  while (index < lines.length) {
    const line = lines[index];
    const key = `b${blocks.length}`;

    if (!line.trim()) {
      index++;
    } else if (RULE.test(line)) {
      index++;
    } else if (HEADING.test(line)) {
      index++;
      blocks.push(<h3 key={key}>{inline(line.replace(HEADING, "").replace(/\s#+\s*$/, ""), key)}</h3>);
    } else if (TABLE_ROW.test(line)) {
      const rows = take((row) => TABLE_ROW.test(row));
      const hasHeader = rows.length > 1 && TABLE_DIVIDER.test(rows[1]);
      const head = hasHeader ? cells(rows[0]) : null;
      const body = rows.slice(hasHeader ? 2 : 0).filter((row) => !TABLE_DIVIDER.test(row));
      blocks.push(
        <div className="md-table" key={key}>
          <table>
            {head && (
              <thead>
                <tr>{head.map((cell, i) => <th key={i}>{inline(cell, `${key}h${i}`)}</th>)}</tr>
              </thead>
            )}
            <tbody>
              {body.map((row, r) => (
                <tr key={r}>
                  {cells(row).map((cell, i) => <td key={i}>{inline(cell, `${key}r${r}c${i}`)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    } else if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = NUMBERED.test(line);
      const marker = ordered ? NUMBERED : BULLET;
      const items = [];
      while (index < lines.length) {
        const current = lines[index];
        if (marker.test(current)) {
          items.push([current.replace(marker, "")]);
          index++;
        } else if (items.length && /^\s{2,}\S/.test(current) && !BULLET.test(current) && !NUMBERED.test(current)) {
          items[items.length - 1].push(current.trim());
          index++;
        } else {
          break;
        }
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(
        <List key={key}>
          {items.map((item, i) => <li key={i}>{withBreaks(item, `${key}i${i}`)}</li>)}
        </List>
      );
    } else {
      const paragraph = take(
        (row) =>
          row.trim() &&
          !HEADING.test(row) &&
          !RULE.test(row) &&
          !TABLE_ROW.test(row) &&
          !BULLET.test(row) &&
          !NUMBERED.test(row)
      );
      blocks.push(<p key={key}>{withBreaks(paragraph.map((row) => row.replace(/^\s*>\s?/, "")), key)}</p>);
    }
  }

  return blocks;
}
