/* The profile page's look-ahead sections: money, applications, unlock, calendar, family.

   Every number and verdict here comes from the server, which got it from the rule
   engine. These functions only draw — the same division as the rest of the frontend. */

import { api, el } from './api.js';
import { guideView } from './cards.js';
import { t } from './i18n.js';

// The tracker's four states (vault.APPLICATION_STATUSES), worded as on the application sheet.
const STATUSES = ['planned', 'applied', 'sanctioned', 'rejected'];
const STATUS_CLASS = { planned: 'det', applied: 'ai', sanctioned: 'ok', rejected: 'no' };
const statusText = (status) => t(`status_${status}`);

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
    const letter = await api.complaint(pid, application.scheme_id, lang);
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
  const status = el('select', { 'aria-label': t('update_status') },
    ...STATUSES.map((value) => el('option', { value }, statusText(value))));
  status.value = application.status;
  const reference = el('input', { type: 'text', maxlength: 60, value: application.reference || '',
    placeholder: t('application_number'), 'aria-label': t('application_number') });
  const reason = el('select', { 'aria-label': t('why_rejected') },
    ...reasons.map((r) => el('option', { value: r.id }, r.label)));
  if (application.reason) reason.value = application.reason;
  const reasonWrap = el('span', {}, reason);
  const sync = () => { reasonWrap.hidden = status.value !== 'rejected'; };
  status.addEventListener('change', sync);
  sync();
  const message = el('span', { class: 'tiny' });
  return el('div', { class: 'row status-editor' }, status, reference, reasonWrap,
    el('button', { class: 'btn small', type: 'button', onclick: async () => {
      try {
        await api.track(pid, {
          scheme_id: application.scheme_id, status: status.value, reference: reference.value,
          applied_on: application.applied_on || (status.value === 'applied' ? today() : null),
          reason: status.value === 'rejected' ? reason.value : null,
        });
        onChange();
      } catch (error) { message.textContent = error.message; message.className = 'tiny err'; }
    } }, t('save_short')), message);
}

export function applicationsView(pid, applications, reasons, onChange) {
  const root = el('div', { class: 'applications' });
  if (!applications.length) {
    root.append(el('p', { class: 'tiny muted' },
      t('nothing_tracked')));
    return root;
  }
  applications.forEach((application) => {
    const history = application.history.map((h) => statusText(h.status)).join(' → ');
    const complaintSlot = el('div');
    root.append(el('div', { class: 'application' },
      el('div', { class: 'row', style: 'justify-content:space-between' },
        el('div', {}, el('b', {}, application.scheme.name),
          application.scheme.value_text ? el('span', { class: 'tiny muted' }, ` · ${application.scheme.value_text}`) : null),
        el('span', { class: `badge ${STATUS_CLASS[application.status]}` }, statusText(application.status))),
      el('div', { class: 'tiny muted' }, history,
        application.applied_on ? ` · ${new Date(application.applied_on).toLocaleDateString('en-IN')}` : '',
        application.reference ? ` · ${application.reference}` : ''),
      application.follow_up ? el('div', { class: 'tiny notice' }, application.follow_up.text) : null,
      application.rejection ? rejectionView(application.rejection) : null,
      el('details', { class: 'tiny' }, el('summary', {}, t('update_status')),
        statusEditor(pid, application, reasons, onChange)),
      application.can_complain ? el('div', { class: 'row' },
        el('button', { class: 'btn small', type: 'button', onclick: () => {
          complaintSlot.replaceChildren(complaintBox(pid, application));
        } }, t('draft_complaint'))) : null,
      complaintSlot));
  });
  return root;
}

/** Track an eligible scheme: say you applied today, or that you plan to. */
export function trackButtons(pid, scheme, onChange) {
  const start = (status) => async (event) => {
    event.target.disabled = true;
    await api.track(pid, { scheme_id: scheme.id, status,
      applied_on: status === 'applied' ? today() : null });
    onChange();
  };
  return el('span', { class: 'track' },
    el('button', { class: 'btn small', type: 'button', onclick: start('applied') }, t('i_applied')),
    el('button', { class: 'btn small', type: 'button', onclick: start('planned') }, t('plan_to_apply')));
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
