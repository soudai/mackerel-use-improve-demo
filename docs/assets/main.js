(() => {
  const status = document.getElementById('copy-status');
  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const input = document.createElement('textarea');
    input.value = text;
    input.setAttribute('readonly', '');
    input.style.position = 'fixed';
    input.style.left = '-10000px';
    document.body.append(input);
    input.select();
    const copied = document.execCommand('copy');
    input.remove();
    if (!copied) throw new Error('Copy unavailable');
  }
  document.querySelectorAll('.copy-button').forEach(button => {
    button.addEventListener('click', async () => {
      const text = button.parentElement.querySelector('code').textContent;
      try {
        await copyText(text);
        button.textContent = 'コピー済み';
        button.classList.add('copied');
        status.textContent = 'クリップボードにコピーしました。';
        window.setTimeout(() => {button.textContent = 'コピー'; button.classList.remove('copied');}, 1800);
      } catch {
        status.textContent = 'コピーできませんでした。コードを選択してコピーしてください。';
        button.textContent = '手動でコピー';
      }
    });
  });
  const links = Array.from(document.querySelectorAll('.sidebar nav a'));
  const sections = links.map(link => document.querySelector(link.getAttribute('href'))).filter(Boolean);
  function updateNavigation() {
    let current = '#overview';
    for (const section of sections) {
      if (section.getBoundingClientRect().top <= 110) current = '#' + section.id;
    }
    links.forEach(link => {
      const active = link.getAttribute('href') === current;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }
  let queued = false;
  window.addEventListener('scroll', () => {
    if (!queued) {
      queued = true;
      window.requestAnimationFrame(() => {updateNavigation(); queued = false;});
    }
  }, {passive: true});
  updateNavigation();
})();
