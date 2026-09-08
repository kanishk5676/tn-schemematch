/* The live scoreboard: three numerals and one cell per active scheme. */

import { $, el } from './api.js';

let cells = null;

function ensureCells(total) {
  const grid = $('grid');
  if (cells && cells.length === total) return;
  grid.replaceChildren();
  cells = [];
  for (let i = 0; i < total; i += 1) {
    const cell = el('div', { class: 'cell undetermined' });
    cells.push(cell);
    grid.append(cell);
  }
}

export function paintBoard(board, settled) {
  if (!board) return;
  $('n-ok').textContent = board.counts.eligible;
  $('n-no').textContent = board.counts.ineligible;
  $('n-open').textContent = board.counts.undetermined;

  ensureCells(board.total);
  // Stable ordering: eligible first, then ineligible, then open. Cells are positional
  // rather than per-scheme, so the block visibly grows in each colour as answers land.
  let i = 0;
  const paint = (n, klass) => { for (let k = 0; k < n; k += 1, i += 1) cells[i].className = `cell ${klass}`; };
  paint(board.counts.eligible, 'eligible');
  paint(board.counts.ineligible, 'ineligible');
  paint(board.counts.undetermined, 'undetermined');

  const note = $('settled');
  if (settled === undefined || settled === null) return;
  if (settled > 0) {
    note.className = 'settled';
    note.textContent = `settled ${settled} scheme${settled === 1 ? '' : 's'}`;
  } else {
    note.className = 'settled zero';
    note.textContent = 'that answer settled nothing yet';
  }
}

export function paintProfile(rows) {
  const card = $('profile-card');
  const chips = $('profile-chips');
  if (!rows?.length) { card.hidden = true; return; }
  card.hidden = false;
  chips.replaceChildren(...rows.map((row) => el('span',
    { class: `chip${row.derived ? ' derived' : ''}`, title: row.derived ? 'computed from your other answers' : row.attr },
    row.attr.replace(/_/g, ' '), ' ', el('b', {}, row.display))));
}
