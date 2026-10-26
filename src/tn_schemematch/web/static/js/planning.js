/* The profile page's look-ahead sections: money, applications, unlock, calendar, family.

   Every number and verdict here comes from the server, which got it from the rule
   engine. These functions only draw — the same division as the rest of the frontend. */

import { api, el } from './api.js';
import { guideView } from './cards.js';

const STATUS_TEXT = {
  planned: 'planning to apply', applied: 'applied', pending: 'waiting', approved: 'approved',
  rejected: 'rejected', received: 'received', withdrawn: 'withdrawn',
};
const STATUS_CLASS = {
  planned: 'det', applied: 'ai', pending: 'open', approved: 'ok', rejected: 'no',
  received: 'ok', withdrawn: 'det',
};

const today = () => new Date().toISOString().slice(0, 10);

/* ------------------------------------------------------------------- money */

/** "At least ₹18,000 a year · ₹25,000 once · health cover ₹5,00,000" */
export function moneyLine(money) {
  if (!money) return null;
  const parts = [];
  if (money.yearly_text) parts.push(el('span', {}, 'at least ', el('b', {}, money.yearly_text), ' a year'));
  if (money.one_time_text) parts.push(el('span', {}, el('b', {}, money.one_time_text), ' one-time'));
  if (money.in_kind_text) parts.push(el('span', {}, 'support worth ', el('b', {}, money.in_kind_text)));
  if (money.best_cover) parts.push(el('span', {}, 'health or life cover up to ',
    el('b', {}, `₹${Number(money.best_cover).toLocaleString('en-IN')}`)));
  if (!parts.length) return null;
  return el('div', { class: 'money' },
    el('span', { class: 'eyebrow' }, 'Worth'),
    ...parts.flatMap((part, i) => (i ? [el('span', { class: 'muted' }, ' · '), part] : [part])),
    el('div', { class: 'tiny muted' },
      'Lowest amounts the sources state. Schemes without a published figure are not counted.'));
}

/** Groups where only some schemes can be taken. */
export function onlyOneOf(groups) {
  if (!groups?.length) return null;
  return el('div', { class: 'notice only-one' },
    ...groups.map((group) => el('div', {},
      el('b', {}, 'You can take only one of these: '),
      [...group.keep, ...group.drop].map((s) => s.name).join(', '), '. ',
      el('span', {}, 'Counted: ', group.keep.map((s) => `${s.name}${s.value_text ? ` (${s.value_text})` : ''}`).join(', '), '.'),
      el('div', { class: 'tiny muted' }, group.reasons.join(' ')))));
}

/* ------------------------------------------------------------- applications */

function rejectionView(rejection) {
  return el('div', { class: `rejection${rejection.disagrees ? ' disagrees' : ''}` },
    el('div', {}, el('b', {}, rejection.label), ' — ', rejection.summary),
    rejection.clauses.length ? el('ul', { class: 'tiny clauses' }, ...rejection.clauses.map((c) => el('li', {},
      el('span', { class: `badge ${c.met === 'eligible' ? 'ok' : c.met === 'ineligible' ? 'no' : 'open'}` },
        c.met === 'eligible' ? 'met' : c.met === 'ineligible' ? 'not met' : 'unknown'),
      ' ', c.rule, c.you_said ? ` — you said ${c.you_said}` : ''))) : null,
    rejection.next.length ? el('ol', { class: 'steps tiny' }, ...rejection.next.map((step) => el('li', {}, step))) : null,
    ...rejection.guides.filter((g) => g.guide).map((g) => el('div', { class: 'tiny' }, el('b', {}, g.label), guideView(g.guide))));
}

function complaintBox(pid, application) {
  const box = el('div', { class: 'complaint' });
  const load = async (lang) => {
    box.replaceChildren(el('span', { class: 'spinner' }));
    const letter = await api.complaint(pid, application.id, lang);
    const text = el('textarea', { rows: 14, class: 'letter', 'aria-label': 'Complaint letter' });
    text.value = letter.text;
    const where = [...letter.send_to.map((s) => s.name), ...letter.channels.map((c) =>
      [c.name, c.phone ? `phone ${c.phone}` : null, c.online].filter(Boolean).join(', '))];
    box.replaceChildren(
      el('div', { class: 'row' },
        ...['en', 'ta', 'ml'].map((code) => el('button', {
          class: `btn small${code === lang ? ' primary' : ''}`, type: 'button', onclick: () => load(code),
        }, { en: 'English', ta: 'தமிழ்', ml: 'മലയാളം' }[code]))),
      letter.grounded_in_rules ? null : el('p', { class: 'tiny notice' },
        'The rules do not show you as eligible, so this letter asks for the reason rather than claiming you qualify.'),
      text,
      el('div', { class: 'row' },
        el('button', { class: 'btn small', type: 'button', onclick: async () => {
          try { await navigator.clipboard.writeText(text.value); } catch { text.select(); }
        } }, 'Copy'),
        el('a', { class: 'btn small', target: '_blank', rel: 'noopener',
          href: `https://wa.me/?text=${encodeURIComponent(text.value)}` }, 'Share on WhatsApp'),
        el('button', { class: 'btn small', type: 'button', onclick: () => window.print() }, 'Print')),
      where.length ? el('div', { class: 'tiny muted' }, 'Send to: ', where.join(' · '),
        ' — check the contact on the department\'s own page first.') : null);
  };
  load('en');
  return box;
}

function statusEditor(pid, application, reasons, onChange) {
  const status = el('select', { 'aria-label': 'New status' },
    ...Object.entries(STATUS_TEXT).map(([value, text]) => el('option', { value }, text)));
  status.value = application.status;
  const day = el('input', { type: 'date', value: today(), 'aria-label': 'When' });
  const reason = el('select', { 'aria-label': 'Reason' },
    ...reasons.map((r) => el('option', { value: r.id }, r.label)));
  const reasonWrap = el('span', {}, reason);
  const note = el('input', { type: 'text', placeholder: 'note (optional)', maxlength: 200 });
  const sync = () => { reasonWrap.hidden = status.value !== 'rejected'; };
  status.addEventListener('change', sync);
  sync();
  const message = el('span', { class: 'tiny' });
  return el('div', { class: 'row status-editor' }, status, day, reasonWrap, note,
    el('button', { class: 'btn small', type: 'button', onclick: async () => {
      try {
        await api.setApplicationStatus(pid, application.id, {
          status: status.value, on_date: day.value || undefined,
          reason: status.value === 'rejected' ? reason.value : undefined, note: note.value,
        });
        onChange();
      } catch (error) { message.textContent = error.message; message.className = 'tiny err'; }
    } }, 'Update'), message);
}

export function applicationsView(pid, applications, reasons, onChange) {
  const root = el('div', { class: 'applications' });
  if (!applications.length) {
    root.append(el('p', { class: 'tiny muted' },
      'Nothing tracked yet. Use “I applied” or “Plan to apply” beside a scheme above.'));
    return root;
  }
  applications.forEach((application) => {
    const history = application.events.map((e) =>
      `${STATUS_TEXT[e.status]}${e.on_date ? ` ${new Date(e.on_date).toLocaleDateString('en-IN')}` : ''}`).join(' → ');
    const complaintSlot = el('div');
    root.append(el('div', { class: 'application' },
      el('div', { class: 'row', style: 'justify-content:space-between' },
        el('div', {}, el('b', {}, application.scheme.name),
          application.scheme.value_text ? el('span', { class: 'tiny muted' }, ` · ${application.scheme.value_text}`) : null),
        el('span', { class: `badge ${STATUS_CLASS[application.status]}` }, STATUS_TEXT[application.status])),
      el('div', { class: 'tiny muted' }, history,
        application.reference ? ` · ref ${application.reference}` : '',
        application.office ? ` · ${application.office}` : ''),
      application.follow_up ? el('div', { class: 'tiny notice' }, application.follow_up.text) : null,
      application.rejection ? rejectionView(application.rejection) : null,
      el('details', { class: 'tiny' }, el('summary', {}, 'Update status'),
        statusEditor(pid, application, reasons, onChange)),
      el('div', { class: 'row' },
        application.can_complain ? el('button', { class: 'btn small', type: 'button', onclick: () => {
          complaintSlot.replaceChildren(complaintBox(pid, application));
        } }, 'Draft a complaint') : null,
        el('button', { class: 'btn ghost danger tiny', type: 'button', onclick: async () => {
          if (!window.confirm('Stop tracking this application?')) return;
          await api.deleteApplication(pid, application.id);
          onChange();
        } }, 'Remove')),
      complaintSlot));
  });
  return root;
}

/** Track an eligible scheme: say you applied today, or that you plan to. */
export function trackButtons(pid, scheme, onChange) {
  const start = (status) => async (event) => {
    event.target.disabled = true;
    await api.openApplication(pid, { scheme_id: scheme.id, status,
      on_date: status === 'applied' ? today() : undefined });
    onChange();
  };
  return el('span', { class: 'track' },
    el('button', { class: 'btn small', type: 'button', onclick: start('applied') }, 'I applied'),
    el('button', { class: 'btn small', type: 'button', onclick: start('planned') }, 'Plan to apply'));
}

/* ------------------------------------------------------------------ unlock */

export function unlockView(result) {
  const root = el('div');
  if (!result.actions.length && !result.questions.length) {
    root.append(el('p', { class: 'tiny muted' }, 'Nothing more to unlock from what we know.'));
    return root;
  }
  if (result.actions.length) {
    root.append(el('div', { class: 'eyebrow' }, 'Things you can do'));
    result.actions.forEach((action) => root.append(el('div', { class: 'unlock' },
      el('b', {}, action.text),
      el('div', { class: 'tiny' }, 'Opens: ', action.schemes.map((s) => s.name).join(', '),
        action.yearly_text || action.one_time_text
          ? el('span', { class: 'muted' }, ` — ${[action.yearly_text && `${action.yearly_text} a year`, action.one_time_text && `${action.one_time_text} once`].filter(Boolean).join(', ')}`)
          : null),
      action.online ? el('a', { class: 'tiny', href: action.online, target: '_blank', rel: 'noopener' }, action.online) : null,
      action.guide ? guideView(action.guide) : null)));
  }
  if (result.questions.length) {
    root.append(el('div', { class: 'eyebrow', style: 'margin-top:12px' }, 'Answer these to find out more'));
    root.append(el('ul', { class: 'tiny questions' }, ...result.questions.map((q) => el('li', {},
      el('b', {}, q.question), ` — decides ${q.n_schemes} scheme${q.n_schemes === 1 ? '' : 's'}`,
      q.yearly_text ? ` worth ${q.yearly_text} a year` : ''))));
  }
  return root;
}

/* ---------------------------------------------------------------- calendar */

export function calendarView(items) {
  if (!items.length) {
    return el('p', { class: 'tiny muted' }, 'Nothing coming up. Track an application, or add an age, to see dates here.');
  }
  return el('ul', { class: 'calendar' }, ...items.map((item) => el('li', { class: `cal-${item.kind}${item.overdue ? ' overdue' : ''}` },
    el('span', { class: 'when mono tiny' }, item.date ? new Date(item.date).toLocaleDateString('en-IN')
      : `in ${item.in_years} yr`),
    el('span', {}, item.text),
    item.kind === 'age' ? el('span', { class: 'tiny muted' }, ' (if nothing else changes)') : null,
    item.source ? el('a', { class: 'tiny', href: item.source, target: '_blank', rel: 'noopener' }, ' source') : null)));
}

/* ------------------------------------------------------------------ family */

export function familyView(family, currentPid, onSelect) {
  const total = family.total;
  return el('div', {},
    el('div', { class: 'money' }, el('span', { class: 'eyebrow' }, 'Family together'),
      total.yearly_text ? el('span', {}, ' at least ', el('b', {}, total.yearly_text), ' a year') : el('span', { class: 'muted' }, ' no yearly amount confirmed yet'),
      total.one_time_text ? el('span', {}, ' · ', el('b', {}, total.one_time_text), ' one-time') : null),
    el('div', { class: 'family' }, ...family.members.map((member) => el('button', {
      type: 'button', class: `member${member.id === currentPid ? ' on' : ''}`, onclick: () => onSelect(member.id),
    },
      el('b', {}, member.name), member.relation ? el('span', { class: 'tiny muted' }, ` · ${member.relation}`) : null,
      el('div', { class: 'tiny' }, `${member.n_eligible} scheme${member.n_eligible === 1 ? '' : 's'}`,
        member.yearly_text ? ` · ${member.yearly_text} a year` : ''),
      member.shared_with_family.length ? el('div', { class: 'tiny muted' }, `Shared with the family: ${member.shared_with_family.join(', ')}`) : null,
      member.n_documents_to_collect ? el('div', { class: 'tiny' }, `${member.n_documents_to_collect} document${member.n_documents_to_collect === 1 ? '' : 's'} to collect`) : null,
      member.next ? el('div', { class: 'tiny muted' }, `In ${member.next.in_years} yr: `,
        [...member.next.gains.map((s) => `+ ${s.name}`), ...member.next.loses.map((s) => `− ${s.name}`)].join(', ')) : null))));
}
