/* AIROS selfcheck - runtime probe for the app shell (runs in headless Chrome too( */
/* Loads the REAL config.js + app.js, verifies AIROS exists, then re-attaches the */
/* index-style handlers with STUBBED fns (no network( and clicks all 4 buttons. */
const R = document.getElementById('R');
const lines = [];

function rec(label, ok, extra) {
  lines.push((ok ? 'PASS' : 'FAIL') + ' ' + label + (extra ? ' - ' + extra : ''));
}

function sleep(ms) {
  return new Promise(function (resolve) { setTimeout(resolve, ms); });
}

(async function () {
  await sleep(50);
  const A = window.AIROS;
  rec('AIROS defined', !!A, A ? Object.keys( A ).join( '|' ) : 'undefined');
  rec('AIROS.login', typeof A !== 'undefined' && typeof A.login === 'function');
  rec('AIROS.setLocale', typeof A !== 'undefined' && typeof A.setLocale === 'function');
  rec('AIROS.toggleTheme', typeof A !== 'undefined' && typeof A.toggleTheme === 'function');
  rec('AIROS_CONFIG', !!window.AIROS_CONFIG);
  const calls = [];
  if (A) {
    A.login = function () { calls.push('login'); return Promise.resolve(); };
    A.setLocale = function (l) { calls.push('setLocale:' + l); };
    A.toggleTheme = function () { calls.push('theme'); };
  }
  function guard(fn) {
    return function () {
      try { fn(); } catch (e) { R.dataset.err = String((e && e.message) || e); }
    };
  }
  function wire(id, fn) {
    const el = id ? document.getElementById(id) : null;
    if (el) el.addEventListener('click', guard(fn));
    else rec('wire' + (id || ''), false, 'missing element');
  }
  wire('login', function () { A.login(); });
  wire('signup', function () { A.login('signup'); });
  wire('theme', function () { A.toggleTheme(); });
  document.querySelectorAll('[data-locale]').forEach(function (b) {
    b.addEventListener('click', guard(function () { A.setLocale(b.getAttribute('data-locale')); }));
  });
  if ( document.querySelectorAll( '[data-locale]' ).length < 2 ) rec( 'lang buttons', false, 'expected 2, found ' + document.querySelectorAll( '[data-locale]' ).length );
  document.getElementById('login').click();
  document.getElementById('signup').click();
  document.getElementById('theme').click();
  document.querySelector('[data-locale="en"]').click();
  document.querySelector('[data-locale="fr"]').click();
  await sleep(25);
  rec('clicks made (5 expected', calls.length === 5, calls.join(','));
  rec('no sync throw', !R.dataset.err, R.dataset.err || '(none)');
  R.textContent = lines.join('\n');
})();