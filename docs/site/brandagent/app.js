'use strict';
// Only presentation controls. No analytics, API calls, form submission or storage.
const languageButton = document.querySelector('#language');
languageButton.addEventListener('click', () => {
  const lang = document.documentElement.lang === 'en' ? 'zh' : 'en';
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-en][data-zh]').forEach(element => {
    element.textContent = element.dataset[lang].replace(/\\n/g, '\n');
  });
  languageButton.textContent = lang === 'zh' ? 'English ↗' : '中文 ↗';
  languageButton.setAttribute('aria-label', lang === 'zh' ? 'Switch to English' : '切换为中文');
  document.title = lang === 'zh' ? 'BrandAgent — 你的积累，始终像你' : 'BrandAgent — Your expertise. Still your voice.';
});
const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(tab) {
  tabs.forEach(item => {
    const selected = item === tab;
    item.setAttribute('aria-selected', String(selected));
    item.tabIndex = selected ? 0 : -1;
    document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
  });
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    selectTab(tabs[next]);
    tabs[next].focus();
  });
});
