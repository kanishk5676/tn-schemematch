/* Shared renderers: scheme cards, verdict chips and the document checklist.

   The interview results, the assistant's inline components and the profile page all show
   the same three things, so they draw them the same way. */

import { el } from './api.js';
import { traceDisclosure } from './trace.js';

const VERDICTS = {
  eligible: { klass: 'ok', en: 'eligible', ta: 'தகுதி உண்டு' },
  ineligible: { klass: 'no', en: 'not eligible', ta: 'தகுதி இல்லை' },
  undetermined: { klass: 'open', en: 'not confirmed', ta: 'உறுதியாகவில்லை' },
};

export function verdictChip(verdict, label) {
  const v = VERDICTS[verdict] || VERDICTS.undetermined;
  return el('span', { class: `badge ${v.klass}`, title: `rule engine: ${v.en} · ${v.ta}` },
    label ? `${label} · ${v.en}` : v.en);
}

/** A scheme as a card. `miss` renders a near-miss; `actions` are extra buttons. */
export function schemeCard(scheme, { miss = false, actions = [], verdict = null } = {}) {
  const card = el('div', { class: `scheme${miss ? ' miss' : ''}${verdict && verdict !== 'eligible' ? ` v-${verdict}` : ''}` });
  const top = el('div', { class: 'scheme-top' },
    el('h3', {}, scheme.name),
    scheme.name_ta ? el('p', { class: 'ta' }, scheme.name_ta) : null,
    scheme.benefit_prose ? el('p', { class: 'benefit' }, scheme.benefit_prose.split('\n')[0]) : null);

  const meta = el('div', { class: 'scheme-meta' },
    verdict ? verdictChip(verdict) : null,
    el('span', { class: 'pill' },
      scheme.level === 'central' ? 'Central' : (scheme.jurisdiction_name || scheme.jurisdiction || 'State')),
    ...(scheme.sectors || []).slice(0, 3).map((s) => el('span', { class: 'pill' }, s.replace(/_/g, ' '))),
    el('span', { class: 'badge open', title: 'no human has checked this rule against the Government Order' }, 'draft'));
  top.append(meta);

  if (miss && scheme.missing) {
    top.append(el('p', { class: 'missing-line' },
      'You would qualify if ', el('b', {}, scheme.missing.human.toLowerCase()),
      scheme.missing.observed_text && scheme.missing.observed_text !== '—'
        ? ` — you said ${scheme.missing.observed_text}.` : '.'));
  } else {
    const row = el('div', { class: 'scheme-actions' });
    if (scheme.apply_url) {
      row.append(el('a', { class: 'btn', href: scheme.apply_url, target: '_blank', rel: 'noopener' }, 'Apply →'));
    }
    actions.forEach((action) => row.append(action));
    if (row.childNodes.length) top.append(row);
    top.append(el('div', { id: `explain-${scheme.id}` }));
  }

  card.append(top);
  if (scheme.trace) card.append(traceDisclosure(scheme.trace));
  return card;
}

const STATUS = {
  have: { mark: '✓', klass: 'have', text: 'on file' },
  missing: { mark: '○', klass: 'missing', text: 'to collect' },
  action: { mark: '→', klass: 'action', text: 'at the office' },
};

/** The documents checklist: one ranked list to collect, then each scheme in detail.
    `onUpload(docType)` adds an upload button beside each document still missing. */
export function checklistView(checklist, { onUpload = null } = {}) {
  const root = el('div', { class: 'checklist' });
  if (!checklist?.schemes?.length) {
    root.append(el('p', { class: 'muted tiny' },
      'No confirmed schemes yet, so there is nothing to prepare. Answer a few more questions first.'));
    return root;
  }

  const ready = checklist.n_ready;
  root.append(el('div', { class: 'checklist-head' },
    el('b', {}, `${ready} of ${checklist.schemes.length} scheme${checklist.schemes.length === 1 ? '' : 's'} ready to apply`),
    el('span', { class: 'muted tiny' }, ' · documents are matched by type, not checked for validity')));

  if (checklist.to_collect.length) {
    root.append(el('div', { class: 'eyebrow', style: 'margin-top:12px' }, 'Collect these, most useful first'));
    const list = el('ol', { class: 'collect' });
    checklist.to_collect.forEach((entry) => {
      const uploadable = entry.types.filter((t) => t.kind === 'document');
      list.append(el('li', {},
        el('div', { class: 'collect-main' },
          el('b', {}, entry.label),
          entry.label_ta ? el('span', { class: 'ta' }, entry.label_ta) : null),
        el('span', { class: 'pill' }, `needed for ${entry.n_schemes} scheme${entry.n_schemes === 1 ? '' : 's'}`),
        onUpload && uploadable.length
          ? el('button', { class: 'btn small', onclick: () => onUpload(uploadable[0].id) }, 'Upload')
          : null));
    });
    root.append(list);
  }

  checklist.schemes.forEach((scheme) => {
    root.append(el('details', { class: 'cl-scheme' },
      el('summary', {},
        el('span', {}, scheme.name),
        scheme.ready ? el('span', { class: 'badge ok' }, 'ready')
          : el('span', { class: 'badge open' }, `${scheme.n_missing} missing`)),
      el('ul', { class: 'cl-items' }, ...scheme.items.map((item) => {
        const s = STATUS[item.status];
        return el('li', { class: s.klass },
          el('span', { class: 'mark' }, s.mark),
          el('span', {}, item.requirement),
          el('span', { class: 'muted tiny' }, s.text));
      })),
      scheme.apply_url
        ? el('a', { class: 'tiny', href: scheme.apply_url, target: '_blank', rel: 'noopener' }, 'Where to apply →')
        : null));
  });
  return root;
}

export const SOURCE_LABEL = {
  query: 'said', chat: 'said', form: 'answered', aliases: 'answered', model: 'answered',
  document: 'document', confirmed: 'confirmed', derived: 'computed', saved: 'saved',
};

export function sourceBadge(source) {
  const label = SOURCE_LABEL[source] || source;
  const klass = source === 'document' ? 'ok' : source === 'derived' ? 'det' : 'ai';
  return el('span', { class: `badge ${klass}`, title: `source: ${source}` }, label);
}
