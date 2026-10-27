import { initializeApp } from 'https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js';
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged } from 'https://www.gstatic.com/firebasejs/11.10.0/firebase-auth.js';

const config = await fetch('/config').then(r => r.json());
const el = id => document.getElementById(id);
let auth;
if (config.apiKey && config.authDomain && config.projectId) {
  auth = getAuth(initializeApp(config));
  onAuthStateChanged(auth, user => {
  el('login').hidden = !!user;
  el('logout').hidden = !user;
  el('tabs').disabled = el('spaces').disabled = !user;
  el('identity').textContent = user ? 'Signed in' : 'Signed out';
  });
} else {
  el('login').disabled = true;
  el('identity').textContent = 'Firebase sign-in is not configured.';
}
el('login').onclick = async () => { try { await signInWithPopup(auth, new GoogleAuthProvider()); } catch { el('status').textContent = 'Sign-in failed.'; } };
el('logout').onclick = () => signOut(auth);
async function refresh() {
  const data = await fetch('/results').then(r => r.json());
  el('tabs-count').textContent = data.counts.TABS;
  el('spaces-count').textContent = data.counts.SPACES;
  for (const team of ['tabs', 'spaces']) {
    const leader = data.counts[team.toUpperCase()] > data.counts[team === 'tabs' ? 'SPACES' : 'TABS'];
    el(`${team}-panel`).classList.toggle('teal', leader);
    el(`${team}-panel`).classList.toggle('lighten-4', leader);
  }
  el('recent').replaceChildren(...data.recent.map(v => {
    const li = document.createElement('li');
    li.className = 'collection-item avatar';
    const icon = document.createElement('span');
    icon.className = 'circle teal lighten-1';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = v.team === 'TABS' ? '》' : '⎵';
    const label = document.createElement('span');
    label.textContent = `A vote for ${v.team}`;
    const time = document.createElement('p');
    time.textContent = `was cast at ${v.cast_at}`;
    li.append(icon, label, time);
    return li;
  }));
}
async function vote(team) {
  try {
    const token = await auth.currentUser.getIdToken();
    const response = await fetch('/votes', {method:'POST', headers:{'Content-Type':'application/json', Authorization:`Bearer ${token}`}, body:JSON.stringify({team})});
    const data = await response.json();
    el('status').textContent = response.ok ? 'Vote recorded.' : data.detail;
    if (response.ok) await refresh();
  } catch { el('status').textContent = 'Unable to submit vote.'; }
}
el('tabs').onclick = () => vote('TABS');
el('spaces').onclick = () => vote('SPACES');
refresh().catch(() => { el('status').textContent = 'Unable to load results.'; });
