/* Interface words in Tamil and English. Tamil is the default.

   Only the page's own labels live here. Questions, answer options and the spoken result
   come from the server (kb/spec/questions.yaml and spoken.py), so they are the same
   wherever they are shown or heard. Elements carry data-i18n="key" and are filled by
   applyLanguage(); scripts call t('key'). The choice is remembered in localStorage, and
   the page works the same when storage is blocked. */

const KEY = 'udhavi.lang';

export const STRINGS = {
  ta: {
    brand: 'உதவி',
    tagline: 'அரசுத் திட்டங்களைக் கண்டுபிடிக்க',
    nav_assistant: 'பேசுங்கள்',
    nav_profile: 'என் விவரங்கள்',
    nav_schemes: 'எல்லாத் திட்டங்கள்',
    nav_helper: 'உதவுபவர்',
    lang_switch: 'English',
    mic: 'பேச அழுத்துங்கள்',
    mic_stop: 'நிறுத்த அழுத்துங்கள்',
    listening: 'கேட்கிறேன்…',
    heard: 'நீங்கள் சொன்னது',
    type_instead: 'எழுதிச் சொல்ல',
    type_here: 'இங்கே எழுதுங்கள்…',
    send: 'அனுப்பு',
    ok: 'சரி',
    number_here: 'எண்',
    result_btn: 'எனக்கு என்ன கிடைக்கும்?',
    hear_again: 'மீண்டும் கேட்க',
    read_aloud: 'சத்தமாகப் படி',
    stop_reading: 'படிப்பதை நிறுத்து',
    autoread: 'பதில்களைத் தானாகப் படி',
    thinking: 'யோசிக்கிறேன்…',
    start_over: 'புதிதாகத் தொடங்கு',
    talk_freely: 'சுதந்திரமாகப் பேச',
    simple_questions: 'எளிய கேள்விகள்',
    talking_for: 'யாருக்காக',
    someone_new: 'புதியவர்',
    save: 'விவரங்களைச் சேமி',
    saved_as: '{name} என்ற பெயரில் சேமிக்கப்பட்டது.',
    not_saved: 'இன்னும் சேமிக்கவில்லை.',
    saved_note: 'நீங்கள் சொல்வது எல்லாம் {name} பெயரில் சேமிக்கப்படுகிறது.',
    save_title: 'உங்கள் விவரங்களைச் சேமிக்க',
    save_note: 'அடுத்த முறை அதே கேள்விகளைக் கேட்க வேண்டாம். இந்தக் கணினியில் மட்டுமே இருக்கும்; எப்போது வேண்டுமானாலும் அழிக்கலாம்.',
    your_name: 'உங்கள் பெயர்',
    cancel: 'வேண்டாம்',
    upload: 'ஆவணத்தின் படம்',
    what_you_told: 'நீங்கள் சொன்னவை',
    found_title: 'உங்களுக்குக் கிடைக்கக்கூடியவை',
    found_n: '{n} திட்டங்கள்',
    none_found: 'இப்போது எந்தத் திட்டமும் உறுதியாகவில்லை.',
    bring_title: 'கொண்டு செல்ல வேண்டியவை',
    near_title: 'ஒரே ஒரு நிபந்தனையில் தவறியவை',
    later_title: 'பின்னால் கிடைக்கக்கூடியவை',
    helper_login_title: 'உதவுபவர் உள்நுழைவு',
    helper_login_note: 'இ-சேவை மையம், அங்கன்வாடி அல்லது தன்னார்வலர்: பலருக்கு உதவ PIN எண்ணை உள்ளிடுங்கள்.',
    pin: 'PIN',
    login: 'உள்நுழை',
    logout: 'வெளியேறு',
    wrong_pin: 'PIN தவறு.',
    too_many_tries: 'பல முறை தவறு. பத்து நிமிடம் கழித்து முயலுங்கள்.',
    helper_title: 'யாருக்கு என்ன தேவை',
    refresh: 'புதுப்பி',
    add_person: 'புதிய நபரைச் சேர்',
    relation: 'உறவு',
    family: 'குடும்பம்',
    new_family: 'புதிய குடும்பம்',
    add_and_talk: 'சேர்த்துப் பேசத் தொடங்கு',
    people: 'நபர்கள்',
    families: 'குடும்பங்கள்',
    schemes: 'திட்டங்கள்',
    schemes_found: 'கண்டறிந்த திட்டங்கள்',
    papers_missing: 'ஆவணங்கள் தேவை',
    follow_up: 'பின்தொடர வேண்டியவை',
    applied: 'விண்ணப்பித்தவை',
    conflicts: 'ஆவணத்தில் முரண்பாடு',
    status: 'நிலை',
    status_planned: 'போகத் திட்டம்',
    status_applied: 'விண்ணப்பித்தாகிவிட்டது',
    status_sanctioned: 'அனுமதி கிடைத்தது',
    status_rejected: 'நிராகரிக்கப்பட்டது',
    reference: 'விண்ணப்ப எண்',
    detailed_check: 'விரிவான சோதனை',
    no_answers_yet: 'இன்னும் பதில்கள் இல்லை.',
    nobody_yet: 'இன்னும் யாரும் சேமிக்கப்படவில்லை.',
    saved_people: 'சேமித்தவர்கள்',
    same_family: 'தேர்ந்தெடுத்தவரின் குடும்பம்',
    stored_here: 'விவரங்களும் ஆவணங்களும் இந்தக் கணினியில் மட்டுமே இருக்கும். ஒருவரை அழித்தால் அவருடைய எல்லா விவரங்களும் படங்களும் அழியும்.',
    delete: 'அழி',
    documents: 'ஆவணங்கள்',
    keep_photo: 'படித்த பிறகும் படத்தை வைத்திரு',
    upload_go: 'பதிவேற்று',
    photo_deleted: 'படித்த பிறகு படம் அழிக்கப்பட்டது',
    later_at: '{age} வயதில் ({years} வருடத்தில்)',
    official_name: 'அரசுப் பெயர்',
    verified: 'சரிபார்க்கப்பட்டது',
    draft: 'அலுவலகத்தில் உறுதி செய்யவும்',
    where: 'எங்கே',
    who: 'யாருக்கு',
    pack: 'விண்ணப்பத் தாள்',
    share: 'வாட்ஸ்அப்பில் பகிர',
    print: 'அச்சிடு',
    apply_online: 'இணையத்தில் விண்ணப்பிக்க',
    eligible_n: 'கிடைக்கும்',
    open_n: 'இன்னும் தெரியவில்லை',
    privacy_title: 'பேசுவதற்கு முன்',
    privacy_text: 'நீங்கள் பேசுவதை எழுத்தாக மாற்ற, உங்கள் குரல் கூகுளுக்கு அனுப்பப்படும். சரியா?',
    privacy_yes: 'சரி, பேசுகிறேன்',
    privacy_no: 'வேண்டாம், எழுதுகிறேன்',
    no_tamil_voice: 'இந்தக் கைபேசியில் தமிழ்க் குரல் இல்லை. கைபேசி அமைப்புகளில் "எழுத்திலிருந்து பேச்சு" பகுதியில் தமிழைச் சேர்க்கலாம்.',
    no_mic: 'இந்த உலாவியில் பேசி பதில் சொல்ல முடியாது. எழுதிச் சொல்லுங்கள், அல்லது Chrome-இல் திறக்கவும்.',
    mic_denied: 'மைக்ரோஃபோன் அனுமதி இல்லை. எழுதிச் சொல்லுங்கள்.',
    heard_nothing: 'எதுவும் கேட்கவில்லை. மீண்டும் முயலுங்கள்.',
    reason_no_model: 'கேள்விகள் மூலம் உதவுகிறேன்.',
    reason_daily_budget: 'இன்றைய AI வரம்பு முடிந்தது. கேள்விகள் மூலம் தொடர்கிறேன்.',
    reason_no_credit: 'AI கணக்கில் பணம் தீர்ந்துவிட்டது. கேள்விகள் மூலம் தொடர்கிறேன்.',
    reason_key_rejected: 'AI சாவி ஏற்கப்படவில்லை. கேள்விகள் மூலம் தொடர்கிறேன்.',
    reason_agent_failed: 'இணைப்பில் சிக்கல். கேள்விகள் மூலம் தொடர்கிறேன்.',
    reason_chosen: '',
    footer: 'விதிகள் அரசு வெளியீடுகளிலிருந்து எடுக்கப்பட்டவை. பெரும்பாலானவை இன்னும் ஒருவரால் சரிபார்க்கப்படவில்லை — விண்ணப்பிக்கும் முன் இ-சேவை மையத்தில் உறுதி செய்யுங்கள்.',
    error: 'ஏதோ தவறு நடந்தது. மீண்டும் முயலுங்கள்.',
  },
  en: {
    brand: 'Udhavi',
    tagline: 'find the government schemes you can get',
    nav_assistant: 'Talk',
    nav_profile: 'My details',
    nav_schemes: 'All schemes',
    nav_helper: 'Helper',
    lang_switch: 'தமிழ்',
    mic: 'Tap to speak',
    mic_stop: 'Tap to stop',
    listening: 'Listening…',
    heard: 'You said',
    type_instead: 'Type instead',
    type_here: 'Type here…',
    send: 'Send',
    ok: 'OK',
    number_here: 'Number',
    result_btn: 'What can I get?',
    hear_again: 'Hear again',
    read_aloud: 'Read aloud',
    stop_reading: 'Stop reading',
    autoread: 'Read replies aloud',
    thinking: 'Thinking…',
    start_over: 'Start over',
    talk_freely: 'Talk freely',
    simple_questions: 'Simple questions',
    talking_for: 'Talking for',
    someone_new: 'Someone new',
    save: 'Save my details',
    saved_as: 'Saved as {name}.',
    not_saved: 'Not saved yet.',
    saved_note: 'Everything you say is saved to {name}.',
    save_title: 'Save your details',
    save_note: 'So you are never asked the same thing twice. It stays on this computer only, and you can delete it any time.',
    your_name: 'Your name',
    cancel: 'Cancel',
    upload: 'Photo of a document',
    what_you_told: 'What you told me',
    found_title: 'What you may be able to get',
    found_n: '{n} schemes',
    none_found: 'No scheme is confirmed yet.',
    bring_title: 'What to bring',
    near_title: 'Missed by just one condition',
    later_title: 'Coming up for you',
    helper_login_title: 'Helper login',
    helper_login_note: 'For e-Sevai operators, anganwadi workers and volunteers helping many families: enter the PIN.',
    pin: 'PIN',
    login: 'Log in',
    logout: 'Log out',
    wrong_pin: 'That PIN is not right.',
    too_many_tries: 'Too many wrong tries. Wait ten minutes.',
    helper_title: 'Who needs what',
    refresh: 'Refresh',
    add_person: 'Add a person',
    relation: 'Relation',
    family: 'Family',
    new_family: 'A new family',
    add_and_talk: 'Add and start talking',
    people: 'people',
    families: 'families',
    schemes: 'schemes',
    schemes_found: 'schemes found',
    papers_missing: 'papers missing',
    follow_up: 'to follow up',
    applied: 'applied',
    conflicts: 'document disagrees',
    status: 'Status',
    status_planned: 'Planning to go',
    status_applied: 'Applied',
    status_sanctioned: 'Sanctioned',
    status_rejected: 'Rejected',
    reference: 'Application number',
    detailed_check: 'Detailed check',
    no_answers_yet: 'No answers yet.',
    nobody_yet: 'Nobody is saved yet.',
    saved_people: 'Saved people',
    same_family: 'same family as the selected person',
    stored_here: 'Details and documents stay only on this computer. Deleting a person deletes every fact and photo saved for them.',
    delete: 'Delete',
    documents: 'Documents',
    keep_photo: 'Keep the photo after reading',
    upload_go: 'Upload',
    photo_deleted: 'Photo deleted after reading',
    later_at: 'at {age} (in {years} years)',
    official_name: 'Official name',
    verified: 'Checked',
    draft: 'Confirm at the office',
    where: 'Where',
    who: 'For',
    pack: 'Application sheet',
    share: 'Share on WhatsApp',
    print: 'Print',
    apply_online: 'Apply online',
    eligible_n: 'can get',
    open_n: 'not known yet',
    privacy_title: 'Before you speak',
    privacy_text: 'To turn your voice into text, your browser sends the audio to Google. Is that OK?',
    privacy_yes: 'OK, let me speak',
    privacy_no: "No, I'll type",
    no_tamil_voice: 'This device has no Tamil voice. You can add Tamil in your phone\'s text-to-speech settings.',
    no_mic: 'Speaking is not available in this browser. Type instead, or open this page in Chrome.',
    mic_denied: 'The microphone is not allowed. Type instead.',
    heard_nothing: 'I did not hear anything. Please try again.',
    reason_no_model: 'I will help with simple questions.',
    reason_daily_budget: "Today's AI limit is used up. I'll carry on with simple questions.",
    reason_no_credit: 'The AI account is out of credit. I\'ll carry on with simple questions.',
    reason_key_rejected: 'The AI key was not accepted. I\'ll carry on with simple questions.',
    reason_agent_failed: 'There was a connection problem. I\'ll carry on with simple questions.',
    reason_chosen: '',
    footer: 'Rules are taken from government publications. Most are not yet checked by a person — confirm at an e-Sevai centre before you apply.',
    error: 'Something went wrong. Please try again.',
  },
};

export const SECTOR_ICONS = {
  health: '🏥', insurance: '🛡️', pension: '👵', elderly: '👵', social_security: '🤝',
  income_support: '💰', women: '👩', maternity: '🤱', child_welfare: '🧒', education: '🎓',
  scholarship: '🎓', skilling: '🛠️', housing: '🏠', agriculture: '🌾', rural: '🌾',
  fisheries: '🐟', livelihood: '🧺', credit: '🏦', savings: '🏦', disability: '♿',
  marriage_assistance: '💍', food_security: '🍚', in_kind: '🎁', energy: '🔥',
  unorganised_workers: '👷', refugees: '🏕️', urban: '🏙️', social_justice: '⚖️', subsidy: '💰',
};

export function sectorIcon(sectors) {
  for (const sector of sectors || []) if (SECTOR_ICONS[sector]) return SECTOR_ICONS[sector];
  return '📄';
}

export function getLanguage() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === 'ta' || saved === 'en') return saved;
  } catch { /* storage blocked */ }
  return 'ta';
}

let current = getLanguage();

export function lang() { return current; }

export function t(key, values = {}) {
  const text = STRINGS[current][key] ?? STRINGS.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => (values[name] ?? ''));
}

/** Fill every [data-i18n] element, [data-i18n-placeholder] and [data-i18n-title]. */
export function applyLanguage(root = document) {
  document.documentElement.lang = current;
  root.querySelectorAll('[data-i18n]').forEach((node) => { node.textContent = t(node.dataset.i18n); });
  root.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  root.querySelectorAll('[data-i18n-title]').forEach((node) => {
    node.title = t(node.dataset.i18nTitle);
    node.setAttribute('aria-label', t(node.dataset.i18nTitle));
  });
}

export function setLanguage(next) {
  current = next === 'en' ? 'en' : 'ta';
  try { localStorage.setItem(KEY, current); } catch { /* storage blocked */ }
  applyLanguage();
  document.dispatchEvent(new CustomEvent('languagechange', { detail: current }));
}

/** Wire the top-bar switch. Every page calls this once. */
export function initLanguage() {
  applyLanguage();
  const button = document.getElementById('lang-switch');
  if (button) button.addEventListener('click', () => setLanguage(current === 'ta' ? 'en' : 'ta'));
}
