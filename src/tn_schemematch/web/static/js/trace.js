/* The rule trace, as a tree you can open.

   This is the showcase view, so it renders both registers at once: a sentence a citizen
   can read, and underneath it the exact clause the engine evaluated plus the value it
   observed. The indentation reproduces `Trace.explain`, so what the page shows and what
   `schemematch explain` prints are the same shape — that correspondence is the point, and
   it is worth saying out loud during a demo. */

import { el } from './api.js';

const MARK = { eligible: '✓', ineligible: '✗', undetermined: '?' };

function renderNode(node) {
  const item = el('li');
  const box = el('div', { class: `node ${node.verdict}` });
  const line = el('div', { class: 'line' });
  line.append(el('span', { class: 'vd' }, MARK[node.verdict] || '·'));

  if (node.kind === 'predicate' || node.kind === 'const' || node.kind === 'unknown') {
    line.append(el('span', { class: 'human' }, node.human || node.label || ''));
    box.append(line);
    if (node.machine) {
      const machine = el('span', { class: 'machine' }, node.machine);
      if (node.observed !== null && node.observed !== undefined) {
        machine.append(el('span', { class: 'muted' }, '  ·  observed: '));
        machine.append(el('span', { class: 'observed' }, String(node.observed_text ?? node.observed)));
      }
      box.append(machine);
    }
    // The KB's notes are genuinely good; showing them is what makes the encoding legible.
    if (node.note) box.append(el('span', { class: 'note' }, node.note));
  } else {
    line.append(el('span', { class: 'combi' }, node.label));
    const parts = [];
    if (node.n_children) parts.push(`${node.n_children} clause${node.n_children === 1 ? '' : 's'}`);
    if (node.n_satisfied) parts.push(`${node.n_satisfied} satisfied`);
    if (node.n_failed) parts.push(`${node.n_failed} failed`);
    if (node.n_open) parts.push(`${node.n_open} open`);
    line.append(el('span', { class: 'count' }, parts.join(' · ')));
    box.append(line);
  }

  if (node.children?.length) {
    const list = el('ul');
    node.children.forEach((child) => list.append(renderNode(child)));
    box.append(list);
  }
  item.append(box);
  return item;
}

export function renderTrace(root) {
  const list = el('ul');
  list.append(renderNode(root));
  return el('div', { class: 'tree' }, list);
}

/** A <details> disclosure wrapping the tree, so cards stay scannable until asked. */
export function traceDisclosure(root, label = 'Why? (rule trace)') {
  return el('details', { class: 'trace' },
    el('summary', {}, label),
    renderTrace(root));
}
