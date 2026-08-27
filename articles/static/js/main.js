const i18n_dict = {
    'he': { 'site_title': 'דף הבית', 'nav_books': 'ספרים', 'nav_qa': 'שאלות ותשובות', 'nav_articles': 'מאמרים', 'nav_parasha': 'פרשת שבוע', 'nav_contact': 'צור קשר', 'footer_rights': 'כל הזכויות שמורות<br>למשה לייבוביץ', 'search_placeholder': 'חיפוש באתר', 'search_btn': 'חיפוש', 'home_latest_articles': 'מאמרים אחרונים', 'home_published': 'פורסם בתאריך:', 'home_read_more': 'קרא עוד', 'home_no_articles': 'אין מאמרים להצגה כרגע.', 'home_calc_title': 'מחשבוני חז"ל', 'home_calc_desc': 'כלי עזר מהיר ואלגנטי להמרת מידות אורך, נפח, ומשקל מטבעות למידות ההלכתיות לפי השיעור המדוייק.', 'home_calc_length': 'מחשבון מידות אורך', 'home_calc_volume': 'מחשבון מידות נפח', 'home_calc_weight': 'מחשבון משקל ומטבעות', 'search_results_for': 'תוצאות חיפוש עבור:', 'search_found': 'נמצאו', 'search_articles': 'תוצאות התואמות לחיפוש שלך', 'search_clear': 'נקה חיפוש וחזור', 'search_no_results_title': 'לא נמצאו מאמרים', 'search_no_results_desc': 'נסה מילת חיפוש אחרת.', 'acc_title': 'נגישות', 'acc_info': 'מידע והגדרות', 'acc_reset': 'איפוס כל הגדרות הנגישות', 'acc_text_size': 'גודל טקסט', 'acc_zoom_in': 'הגדל טקסט', 'acc_zoom_out': 'הקטן טקסט', 'acc_reset_text': 'איפוס גודל טקסט', 'acc_colors': 'צבעים', 'acc_contrast': 'ניגודיות גבוהה', 'acc_invert': 'היפוך צבעים', 'acc_display': 'תצוגה', 'acc_font': 'פונט קריא (גופן בסיסי)', 'acc_highlight': 'הדגשה', 'acc_hl_links': 'הדגשת קישורים', 'acc_hl_headers': 'הדגשת כותרות' },
    'en': { 'site_title': 'Home Page', 'nav_books': 'Books', 'nav_qa': 'Q&A', 'nav_articles': 'Articles', 'nav_parasha': 'Weekly Torah', 'nav_contact': 'Contact Us', 'footer_rights': 'All rights reserved<br>to Moshe Leibowitz', 'search_placeholder': 'Search the site...', 'search_btn': 'Search', 'home_latest_articles': 'Latest Articles', 'home_published': 'Published on:', 'home_read_more': 'Read More', 'home_no_articles': 'No articles to display currently.', 'home_calc_title': 'Chazal Calculators', 'home_calc_desc': 'A fast and elegant tool for converting length, volume, and weight to their exact Halachic measurements.', 'home_calc_length': 'Length Calculator', 'home_calc_volume': 'Volume Calculator', 'home_calc_weight': 'Weight & Coins Calculator', 'search_results_for': 'Search results for:', 'search_found': 'Found', 'search_articles': 'matching results', 'search_clear': 'Clear search & return', 'search_no_results_title': 'No articles found', 'search_no_results_desc': 'Try a different search term.', 'acc_title': 'Accessibility', 'acc_info': 'Info & Settings', 'acc_reset': 'Reset all settings', 'acc_text_size': 'Text Size', 'acc_zoom_in': 'Zoom In', 'acc_zoom_out': 'Zoom Out', 'acc_reset_text': 'Reset Text Size', 'acc_colors': 'Colors', 'acc_contrast': 'High Contrast', 'acc_invert': 'Invert Colors', 'acc_display': 'Display', 'acc_font': 'Readable Font', 'acc_highlight': 'Highlight', 'acc_hl_links': 'Highlight Links', 'acc_hl_headers': 'Highlight Headers' }
};

function applyLanguage(lang) {
    localStorage.setItem('site_lang', lang); document.documentElement.lang = lang;
    const isRtl = (lang === 'he'); document.documentElement.dir = isRtl ? 'rtl' : 'ltr';
    const bsLink = document.getElementById('bootstrap-css');
    if (isRtl) { bsLink.href = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.rtl.min.css'; } 
    else { bsLink.href = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'; }
    const flagImg = document.getElementById('lang-flag-img'); const langText = document.getElementById('lang-text');
    if (isRtl) { flagImg.src = 'https://upload.wikimedia.org/wikipedia/commons/a/a4/Flag_of_the_United_States.svg'; flagImg.alt = 'English'; langText.innerText = 'אנגלית'; } 
    else { flagImg.src = 'https://upload.wikimedia.org/wikipedia/commons/d/d4/Flag_of_Israel.svg'; flagImg.alt = 'Hebrew'; langText.innerText = 'Hebrew'; }
    document.querySelectorAll('[data-i18n]').forEach(el => { const key = el.getAttribute('data-i18n'); if (i18n_dict[lang][key]) { el.innerHTML = i18n_dict[lang][key]; } });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { const key = el.getAttribute('data-i18n-placeholder'); if (i18n_dict[lang][key]) { el.placeholder = i18n_dict[lang][key]; } });
}

function toggleLanguage() { const currentLang = localStorage.getItem('site_lang') || 'he'; const newLang = currentLang === 'he' ? 'en' : 'he'; applyLanguage(newLang); }

function toggleDarkMode() {
    const body = document.body;
    if (body.classList.contains('dark-mode')) { body.classList.remove('dark-mode'); localStorage.setItem('site_theme', 'light'); } 
    else { body.classList.add('dark-mode'); localStorage.setItem('site_theme', 'dark'); }
}

function toggleAccessibilityMenu() { const menu = document.getElementById('acc-main-menu'); const toggle = document.getElementById('acc-floating-toggle'); if (menu.style.display === 'none') { menu.style.display = 'block'; toggle.style.display = 'none'; } else { menu.style.display = 'none'; toggle.style.display = 'block'; } }
function toggleAccSubMenu(id) { const submenu = document.getElementById(id); submenu.style.display = submenu.style.display === 'block' ? 'none' : 'block'; }

let currentZoom = 1.0; 
function changeFontSize(step) { currentZoom += step; if (currentZoom < 0.8) currentZoom = 0.8; if (currentZoom > 2.2) currentZoom = 2.2; document.documentElement.style.fontSize = (currentZoom * 100) + '%'; }
function resetFontSize() { currentZoom = 1.0; document.documentElement.style.fontSize = '100%'; }
function toggleA11yClass(className) { document.body.classList.toggle(className); }
function resetA11y() { resetFontSize(); document.body.className = ''; }

async function sendGlobalNavMessage() {
    const inputField = document.getElementById('globalNavInput'); const chatBox = document.getElementById('globalNavChatBox'); const userText = inputField.value.trim();
    if (userText === '') return;
    chatBox.innerHTML += `<div class="nav-chat-bubble nav-chat-user">${userText}</div>`; inputField.value = ''; chatBox.scrollTop = chatBox.scrollHeight;
    const typingId = 'nav-typing-' + Date.now(); const aiTitle = '<strong style="font-size: 1.15em; color: #2575fc;">עוזר הניווט הדיגיטלי:</strong><br><br>';
    chatBox.innerHTML += `<div class="nav-chat-bubble nav-chat-bot" id="${typingId}">${aiTitle} <div class="nav-loading-status"><div class="nav-spinner" style="border-top-color: #2575fc;"></div><span id="nav-status-text-${typingId}">מאתר את העמוד הרלוונטי...</span></div></div>`;
    chatBox.scrollTop = chatBox.scrollHeight;
    try {
        const response = await fetch('/api/ai-chat/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: userText, mode: 'nav' }) });
        if (!response.ok) { document.getElementById(typingId).innerHTML = `${aiTitle}מצטער, הייתה בעיה זמנית בעיבוד השאלה.`; return; }
        const data = await response.json(); const textToType = data.answer; document.getElementById(typingId).innerHTML = `${aiTitle}`; let charIndex = 0;
        const typeInterval = setInterval(() => { if (charIndex < textToType.length) { charIndex += 4; let currentHTML = textToType.substring(0, charIndex).replace(/\n/g, '<br>'); document.getElementById(typingId).innerHTML = `${aiTitle}${currentHTML}`; chatBox.scrollTop = chatBox.scrollHeight; } else { clearInterval(typeInterval); } }, 10); 
    } catch (error) { document.getElementById(typingId).innerHTML = `${aiTitle}מצטער, אירעה שגיאת רשת זמנית.`; }
    chatBox.scrollTop = chatBox.scrollHeight;
}

async function sendQAMessage() {
    const inputField = document.getElementById('globalQAInput'); const chatBox = document.getElementById('globalQAChatBox'); const userText = inputField.value.trim();
    if (userText === '') return;
    chatBox.innerHTML += `<div class="nav-chat-bubble qa-chat-user">${userText}</div>`; inputField.value = ''; chatBox.scrollTop = chatBox.scrollHeight;
    const typingId = 'qa-typing-' + Date.now(); const aiTitle = '<strong style="font-size: 1.15em; color: #1e202c;">שאל את ה-AI מבוסס על התכנים שבאתר <span style="font-weight: normal; font-size: 0.85em;">(אין לסמוך על תשובות ה- AI למעשה)</span>:</strong><br><br>';
    chatBox.innerHTML += `<div class="nav-chat-bubble qa-chat-bot" id="${typingId}">${aiTitle} <div class="nav-loading-status" style="color: #d4af37;"><div class="nav-spinner" style="border-top-color: #d4af37;"></div><span id="qa-status-text-${typingId}">🧠 מנתח את ההקשר ההלכתי של הטקסט...</span></div></div>`;
    chatBox.scrollTop = chatBox.scrollHeight;
    const loadingMessages = ["🧠 מנתח את ההקשר ההלכתי של הטקסט...", "📚 סורק מקורות ופסקי הלכה...", "✍️ מנסח תשובה ברורה ומדויקת..."]; let messageIndex = 0;
    const loadingInterval = setInterval(() => { messageIndex = (messageIndex + 1) % loadingMessages.length; const statusElement = document.getElementById(`qa-status-text-${typingId}`); if (statusElement) { statusElement.innerText = loadingMessages[messageIndex]; } }, 2000);
    try {
        const response = await fetch('/api/ai-chat/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: userText, mode: 'qa' }) });
        clearInterval(loadingInterval);
        if (!response.ok) { document.getElementById(typingId).innerHTML = `${aiTitle}מצטער, הייתה בעיה זמנית בעיבוד השאלה.`; return; }
        const data = await response.json(); const textToType = data.answer; document.getElementById(typingId).innerHTML = `${aiTitle}`; let charIndex = 0;
        const typeInterval = setInterval(() => { if (charIndex < textToType.length) { charIndex += 4; let currentHTML = textToType.substring(0, charIndex).replace(/\n/g, '<br>'); document.getElementById(typingId).innerHTML = `${aiTitle}${currentHTML}`; chatBox.scrollTop = chatBox.scrollHeight; } else { clearInterval(typeInterval); } }, 10); 
    } catch (error) { clearInterval(loadingInterval); document.getElementById(typingId).innerHTML = `${aiTitle}מצטער, אירעה שגיאת רשת זמנית.`; }
    chatBox.scrollTop = chatBox.scrollHeight;
}

const globalNavInput = document.getElementById('globalNavInput');
if (globalNavInput) {
    globalNavInput.addEventListener('keypress', function(e) { if (e.key === 'Enter') sendGlobalNavMessage(); });
}

const globalQAInput = document.getElementById('globalQAInput');
if (globalQAInput) {
    globalQAInput.addEventListener('keypress', function(e) { if (e.key === 'Enter') sendQAMessage(); });
}

document.addEventListener('DOMContentLoaded', () => {
    const savedLang = localStorage.getItem('site_lang') || 'he';
    if(savedLang !== 'he') { applyLanguage(savedLang); }
    const savedTheme = localStorage.getItem('site_theme');
    if (savedTheme === 'dark') { document.body.classList.add('dark-mode'); }
    const scrollTopBtn = document.getElementById('scrollTopBtn');
    if (scrollTopBtn) {
        window.addEventListener('scroll', function() { if (window.pageYOffset > 300) { scrollTopBtn.classList.add('show'); } else { scrollTopBtn.classList.remove('show'); } });
        scrollTopBtn.addEventListener('click', function() { window.scrollTo({ top: 0, behavior: 'smooth' }); });
    }
    const observerOptions = { root: null, rootMargin: '0px', threshold: 0.1 };
    const observer = new IntersectionObserver((entries, observer) => { entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add('is-visible'); observer.unobserve(entry.target); } }); }, observerOptions);
    document.querySelectorAll('.reveal-up').forEach((el) => { observer.observe(el); });
});

window.addEventListener('scroll', function() {
    const winScroll = document.body.scrollTop || document.documentElement.scrollTop; const height = document.documentElement.scrollHeight - document.documentElement.clientHeight; let scrolled = 0;
    if (height > 0) { scrolled = (winScroll / height) * 100; }
    const progressBar = document.getElementById("reading-progress-bar"); if (progressBar) { progressBar.style.width = scrolled + "%"; }
});