// Arena-specific JavaScript
let htmlEditor, cssEditor, jsEditor;
let currentTab = 'html';
let diffCheckInterval = null;
let sliderPercent = 50;
let sliderInitialized = false;
let sliderMode = 'opacity';
let liveDiffTimer = null;
let diffInProgress = false;
let diffPending = false;
let matchIsRunning = false;
let lastLiveSaveAt = 0;
let previewBroadcastTimer = null;
let lastSavedCodeHash = null;
let lastSavedScore = null;
let lastRightClickReportAt = 0;

const LIVE_DIFF_DELAY = 180;
const LIVE_SAVE_INTERVAL = 1000;

// Get DOM elements safely
function getElement(id) {
    return document.getElementById(id);
}

// Get configuration from hidden inputs
const arenaConfig = window.ARENA_CONFIG || {};
const ROOM_ID = parseInt(getElement('room-id')?.value || arenaConfig.roomId || '0');
const ROOM_CODE = getElement('room-code')?.value || arenaConfig.roomCode || '';
const CHALLENGE_ID = parseInt(getElement('challenge-id')?.value || arenaConfig.challengeId || '0');
const CURRENT_USERNAME = getElement('current-username')?.value || arenaConfig.currentUsername || '';
const USER_ROLE = getElement('user-role')?.value || arenaConfig.userRole || '';
const CHALLENGE_TYPE = getElement('challenge-type')?.value || arenaConfig.challengeType || 'image';
const HTML_LOCKED = getElement('html-locked')?.value === 'true' || arenaConfig.htmlLocked === true;
const TIME_LIMIT = parseInt(getElement('challenge-time-limit')?.value || arenaConfig.timeLimit || '120');
const TARGET_IMAGE_URL = getElement('target-image-url')?.value || arenaConfig.targetImageUrl || '';
const TARGET_HTML_RAW = getElement('target-html-data')?.value || arenaConfig.targetHtml || '';
const TARGET_CSS_RAW = getElement('target-css-data')?.value || arenaConfig.targetCss || '';
const STARTER_HTML_RAW = getElement('starter-html-data')?.value || arenaConfig.starterHtml || '';
const STARTER_CSS_RAW = getElement('starter-css-data')?.value || arenaConfig.starterCss || '';
const PLAYER_ROLES = ['player1', 'player2'];
const IS_PLAYER_ROLE = PLAYER_ROLES.includes(USER_ROLE);
const IS_OBSERVER_ROLE = USER_ROLE === 'admin' || USER_ROLE === 'spectator';
const CAN_PUBLISH_MEDIA = IS_PLAYER_ROLE || USER_ROLE === 'admin';
const INITIAL_SCORES = arenaConfig.initialScores || {};
const SCORE_CACHE_KEY = `arena_${ROOM_ID}_${CURRENT_USERNAME}_score_cache`;
const PLAYER_INSPECT_WARNING = 'Players MUST NOT RIGHT CLICK OR THEY ARE DISQUALIFIED. Inspect and source shortcuts are prohibited during arena matches.';
const COLOR_PROPERTY_RE = /(^|[-\s])(color|background|background-color|border|border-color|box-shadow|text-shadow|outline|fill|stroke)$/i;
const EDITOR_SHORTCUT_GROUPS = [
    ['Boilerplate and snippets', [
        ['! or html:5 + Enter/Tab', 'Insert a full HTML5 page'],
        ['div.card, #app, a.btn + Enter/Tab', 'Create tags with class/id abbreviations'],
        ['ul>li*3 or div.card>h2 + Enter/Tab', 'Create simple nested structures'],
        ['btn, form, img, nav, card, grid, hero, table, video', 'Insert common HTML snippets'],
        ['m10, p16, w100p, flex, grid2, pos:a, d:f', 'Insert quick CSS snippets']
    ]],
    ['Editing', [
        ['Ctrl+Space', 'Autocomplete'],
        ['Ctrl+/', 'Toggle comment'],
        ['Alt+Up / Alt+Down', 'Move line'],
        ['Shift+Alt+Up / Down', 'Duplicate line'],
        ['Ctrl+Shift+K', 'Delete line'],
        ['Ctrl+D', 'Select next match'],
        ['Shift+Alt+F', 'Format indentation']
    ]],
    ['Arena', [
        ['Ctrl+1 / Ctrl+2 / Ctrl+3', 'Switch HTML, CSS, JS tabs'],
        ['Ctrl+S', 'Save locally and refresh preview'],
        ['Ctrl+Enter', 'Submit and check score'],
        ['Alt+C in CSS', 'Open color picker']
    ]]
];

// Parse target HTML/CSS (handle JSON escaping)
let TARGET_HTML = TARGET_HTML_RAW;
let TARGET_CSS = TARGET_CSS_RAW;
let STARTER_HTML = STARTER_HTML_RAW;
let STARTER_CSS = STARTER_CSS_RAW;
try {
    if (TARGET_HTML_RAW && TARGET_HTML_RAW.startsWith('"')) {
        TARGET_HTML = JSON.parse(TARGET_HTML_RAW);
    }
    if (TARGET_CSS_RAW && TARGET_CSS_RAW.startsWith('"')) {
        TARGET_CSS = JSON.parse(TARGET_CSS_RAW);
    }
    if (STARTER_HTML_RAW && STARTER_HTML_RAW.startsWith('"')) {
        STARTER_HTML = JSON.parse(STARTER_HTML_RAW);
    }
    if (STARTER_CSS_RAW && STARTER_CSS_RAW.startsWith('"')) {
        STARTER_CSS = JSON.parse(STARTER_CSS_RAW);
    }
} catch(e) {}

function getActiveEditor() {
    if (currentTab === 'css') return cssEditor;
    if (currentTab === 'js') return jsEditor;
    return htmlEditor;
}

function getEditorHint(editor) {
    if (!window.CodeMirror?.hint) return null;
    const modeName = editor?.getOption('mode');
    if (modeName === 'css') return CodeMirror.hint.css;
    if (modeName === 'javascript') return CodeMirror.hint.javascript;
    if (modeName === 'htmlmixed') return CodeMirror.hint.html;
    return null;
}

function showEditorHint(editor) {
    if (!editor || editor.getOption('readOnly') || !editor.showHint) return;
    const hint = getEditorHint(editor);
    editor.showHint({
        hint: hint || undefined,
        completeSingle: false,
        alignWithWord: true,
        closeOnUnfocus: true
    });
}

function currentWordRange(editor) {
    const cursor = editor.getCursor();
    const line = editor.getLine(cursor.line) || '';
    let start = cursor.ch;
    while (start > 0 && /[A-Za-z0-9_!#.\-:*>+$[\]{}=@]/.test(line.charAt(start - 1))) start -= 1;
    return {
        from: { line: cursor.line, ch: start },
        to: cursor,
        word: line.slice(start, cursor.ch)
    };
}

function htmlBoilerplate() {
    return [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '  <title>UI Battle</title>',
        '</head>',
        '<body>',
        '  ',
        '</body>',
        '</html>'
    ].join('\n');
}

function snippetWithCursor(text, cursorToken = '__CURSOR__') {
    return { text, cursorToken };
}

function expandSimpleHtmlAbbreviation(editor) {
    if (!editor || editor.getOption('mode') !== 'htmlmixed' || editor.getOption('readOnly')) return false;
    const range = currentWordRange(editor);
    const abbr = range.word.trim();
    if (!abbr) return false;

    const snippets = {
        '!': htmlBoilerplate(),
        'html:5': htmlBoilerplate(),
        'link:css': '<link rel="stylesheet" href="style.css">',
        'script:src': '<script src="script.js"></script>',
        'img': '<img src="" alt="">',
        'picture': '<picture>\n  <source srcset="" media="(min-width: 768px)">\n  <img src="" alt="">\n</picture>',
        'video': '<video controls>\n  <source src="" type="video/mp4">\n</video>',
        'audio': '<audio controls>\n  <source src="" type="audio/mpeg">\n</audio>',
        'a': '<a href=""></a>',
        'btn': '<button type="button"></button>',
        'button': '<button type="button"></button>',
        'input': '<input type="text" name="" placeholder="">',
        'input:email': '<input type="email" name="email" placeholder="Email">',
        'input:password': '<input type="password" name="password" placeholder="Password">',
        'input:checkbox': '<input type="checkbox" name="" id="">',
        'label': '<label for=""></label>',
        'form': '<form action="" method="post">\n  \n</form>',
        'select': '<select name="">\n  <option value=""></option>\n</select>',
        'textarea': '<textarea name="" rows="4"></textarea>',
        'nav': '<nav class="nav">\n  <a href="#">Home</a>\n  <a href="#">About</a>\n  <a href="#">Contact</a>\n</nav>',
        'header': '<header>\n  \n</header>',
        'footer': '<footer>\n  \n</footer>',
        'main': '<main>\n  \n</main>',
        'aside': '<aside>\n  \n</aside>',
        'section': '<section>\n  <h2></h2>\n  <p></p>\n</section>',
        'card': '<article class="card">\n  <h2></h2>\n  <p></p>\n</article>',
        'cards': '<section class="cards">\n  <article class="card"></article>\n  <article class="card"></article>\n  <article class="card"></article>\n</section>',
        'grid': '<div class="grid">\n  <div></div>\n  <div></div>\n  <div></div>\n</div>',
        'hero': '<section class="hero">\n  <h1></h1>\n  <p></p>\n  <button type="button"></button>\n</section>',
        'modal': '<div class="modal" role="dialog" aria-modal="true">\n  <div class="modal-content">\n    \n  </div>\n</div>',
        'list': '<ul>\n  <li></li>\n  <li></li>\n  <li></li>\n</ul>',
        'ul>li*3': '<ul>\n  <li></li>\n  <li></li>\n  <li></li>\n</ul>',
        'ol>li*3': '<ol>\n  <li></li>\n  <li></li>\n  <li></li>\n</ol>',
        'table': '<table>\n  <thead>\n    <tr><th></th><th></th></tr>\n  </thead>\n  <tbody>\n    <tr><td></td><td></td></tr>\n  </tbody>\n</table>',
        'lorem': 'Lorem ipsum dolor sit amet, consectetur adipiscing elit.'
    };

    let output = snippets[abbr];
    if (!output) {
        const nested = abbr.match(/^([a-z][\w-]*)?(#[A-Za-z][\w-]*)?((?:\.[A-Za-z][\w-]*)*)>([a-z][\w-]*)(?:\*(\d{1,2}))?$/i);
        if (nested) {
            const parent = nested[1] || 'div';
            const id = nested[2] ? ` id="${nested[2].slice(1)}"` : '';
            const classes = nested[3] ? ` class="${nested[3].split('.').filter(Boolean).join(' ')}"` : '';
            const child = nested[4];
            const count = Math.max(1, Math.min(12, Number(nested[5]) || 1));
            const children = Array.from({ length: count }, () => `  <${child}></${child}>`).join('\n');
            output = `<${parent}${id}${classes}>\n${children}\n</${parent}>`;
        }
    }
    if (!output) {
        const match = abbr.match(/^([a-z][a-z0-9-]*)?(#[A-Za-z][\w-]*)?((?:\.[A-Za-z][\w-]*)+)?(?:\*(\d{1,2}))?$/i);
        if (!match || (!match[1] && !match[2] && !match[3])) return false;
        const tag = match[1] || 'div';
        const id = match[2] ? ` id="${match[2].slice(1)}"` : '';
        const classes = match[3] ? ` class="${match[3].split('.').filter(Boolean).join(' ')}"` : '';
        const count = Math.max(1, Math.min(12, Number(match[4]) || 1));
        output = Array.from({ length: count }, () => `<${tag}${id}${classes}></${tag}>`).join('\n');
    }

    editor.replaceRange(output, range.from, range.to);
    if (output.includes('  \n')) {
        const before = output.slice(0, output.indexOf('  \n'));
        const lines = before.split('\n');
        editor.setCursor({ line: range.from.line + lines.length - 1, ch: lines[lines.length - 1].length + 2 });
    } else if (output.includes('></')) {
        const before = output.slice(0, output.indexOf('></') + 1);
        const lines = before.split('\n');
        editor.setCursor({ line: range.from.line + lines.length - 1, ch: lines[lines.length - 1].length });
    }
    return true;
}

function expandSimpleCssAbbreviation(editor) {
    if (!editor || editor.getOption('mode') !== 'css' || editor.getOption('readOnly')) return false;
    const range = currentWordRange(editor);
    const abbr = range.word.trim();
    if (!abbr) return false;

    const snippets = {
        'm0': 'margin: 0;',
        'ma': 'margin: auto;',
        'm10': 'margin: 10px;',
        'mt10': 'margin-top: 10px;',
        'mr10': 'margin-right: 10px;',
        'mb10': 'margin-bottom: 10px;',
        'ml10': 'margin-left: 10px;',
        'p0': 'padding: 0;',
        'p10': 'padding: 10px;',
        'p16': 'padding: 16px;',
        'pt10': 'padding-top: 10px;',
        'pr10': 'padding-right: 10px;',
        'pb10': 'padding-bottom: 10px;',
        'pl10': 'padding-left: 10px;',
        'w100': 'width: 100%;',
        'w100p': 'width: 100%;',
        'w50p': 'width: 50%;',
        'mw1200': 'max-width: 1200px;',
        'h100': 'height: 100%;',
        'mih100vh': 'min-height: 100vh;',
        'br8': 'border-radius: 8px;',
        'b1': 'border: 1px solid #e5e7eb;',
        'c': 'color: #111827;',
        'bg': 'background: #ffffff;',
        'bgc': 'background-color: #ffffff;',
        'd:f': 'display: flex;',
        'd:g': 'display: grid;',
        'd:b': 'display: block;',
        'd:n': 'display: none;',
        'flex': 'display: flex;\nalign-items: center;\ngap: 12px;',
        'fxdc': 'display: flex;\nflex-direction: column;',
        'fxw': 'flex-wrap: wrap;',
        'jcc': 'justify-content: center;',
        'jcsb': 'justify-content: space-between;',
        'aic': 'align-items: center;',
        'grid': 'display: grid;\ngap: 16px;',
        'grid2': 'display: grid;\ngrid-template-columns: repeat(2, minmax(0, 1fr));\ngap: 16px;',
        'grid3': 'display: grid;\ngrid-template-columns: repeat(3, minmax(0, 1fr));\ngap: 16px;',
        'abs': 'position: absolute;\ntop: 0;\nleft: 0;',
        'rel': 'position: relative;',
        'pos:a': 'position: absolute;',
        'pos:r': 'position: relative;',
        'pos:f': 'position: fixed;',
        't0': 'top: 0;',
        'r0': 'right: 0;',
        'b0': 'bottom: 0;',
        'l0': 'left: 0;',
        'shadow': 'box-shadow: 0 12px 30px rgba(15, 23, 42, 0.18);',
        'trans': 'transition: all 160ms ease;',
        'fs16': 'font-size: 16px;',
        'fw700': 'font-weight: 700;',
        'lh1.5': 'line-height: 1.5;',
        'ta:c': 'text-align: center;',
        'ov:h': 'overflow: hidden;',
        'cur:p': 'cursor: pointer;',
        'media': '@media (max-width: 768px) {\n  \n}',
        'keyframes': '@keyframes name {\n  from { opacity: 0; }\n  to { opacity: 1; }\n}',
        'root': ':root {\n  --color: #22d3ee;\n}'
    };
    const output = snippets[abbr];
    if (!output) return false;
    editor.replaceRange(output, range.from, range.to);
    return true;
}

function expandEditorAbbreviation(editor) {
    return expandSimpleHtmlAbbreviation(editor) || expandSimpleCssAbbreviation(editor);
}

function maybeShowEditorHint(editor, change) {
    if (!editor || editor.getOption('readOnly') || !editor.showHint || editor.state.completionActive) return;
    if (!change.origin || !change.origin.startsWith('+input')) return;
    const typed = change.text?.join('') || '';
    if ((typed === ':' || typed === '#') && cursorLooksLikeCssColorValue(editor)) {
        setTimeout(() => openCssColorPicker(editor), 80);
        return;
    }
    if (!/^[\w.#:<-]$/.test(typed)) return;
    showEditorHint(editor);
}

function moveCurrentLine(editor, direction) {
    const cursor = editor.getCursor();
    const lineNo = cursor.line;
    const swapLineNo = lineNo + direction;
    if (swapLineNo < 0 || swapLineNo >= editor.lineCount()) return;

    editor.operation(() => {
        const line = editor.getLine(lineNo);
        const swapLine = editor.getLine(swapLineNo);
        editor.replaceRange(swapLine, { line: lineNo, ch: 0 }, { line: lineNo, ch: line.length });
        editor.replaceRange(line, { line: swapLineNo, ch: 0 }, { line: swapLineNo, ch: swapLine.length });
        editor.setCursor({ line: swapLineNo, ch: cursor.ch });
    });
}

function duplicateCurrentLine(editor) {
    const cursor = editor.getCursor();
    const line = editor.getLine(cursor.line);
    editor.replaceRange(`${line}\n`, { line: cursor.line, ch: 0 });
    editor.setCursor({ line: cursor.line + 1, ch: cursor.ch });
}

function deleteCurrentLine(editor) {
    const cursor = editor.getCursor();
    const lastLine = editor.lineCount() - 1;
    const from = { line: cursor.line, ch: 0 };
    const to = cursor.line === lastLine
        ? { line: cursor.line, ch: editor.getLine(cursor.line).length }
        : { line: cursor.line + 1, ch: 0 };
    editor.replaceRange('', from, to);
    editor.setCursor({ line: Math.min(cursor.line, editor.lineCount() - 1), ch: 0 });
}

function formatEditorSelection(editor) {
    editor.operation(() => {
        if (editor.somethingSelected()) {
            const from = editor.getCursor('from');
            const to = editor.getCursor('to');
            for (let line = from.line; line <= to.line; line += 1) editor.indentLine(line, 'smart');
            return;
        }
        for (let line = 0; line < editor.lineCount(); line += 1) editor.indentLine(line, 'smart');
    });
}

function selectNextOccurrence(editor) {
    const selected = editor.getSelection() || editor.findWordAt(editor.getCursor());
    const query = typeof selected === 'string' ? selected : editor.getRange(selected.anchor, selected.head);
    if (!query) return;
    const cursor = editor.getSearchCursor ? editor.getSearchCursor(query, editor.getCursor('to')) : null;
    if (cursor && cursor.findNext()) {
        editor.addSelection(cursor.from(), cursor.to());
    }
}

function cursorLooksLikeCssColorValue(editor) {
    if (!editor || editor.getOption('mode') !== 'css') return false;
    const cursor = editor.getCursor();
    const lineBefore = (editor.getLine(cursor.line) || '').slice(0, cursor.ch);
    const property = lineBefore.split('{').pop().split(';').pop().split(':')[0]?.trim();
    return Boolean(property && COLOR_PROPERTY_RE.test(property));
}

function insertCssColor(editor, value) {
    if (!editor || !value) return;
    const cursor = editor.getCursor();
    const token = editor.getTokenAt(cursor);
    const line = editor.getLine(cursor.line) || '';
    const from = token && /^(#[0-9a-fA-F]{0,8}|rgba?\([^)]*|hsla?\([^)]*)$/.test(token.string || '')
        ? { line: cursor.line, ch: token.start }
        : cursor;
    const to = token && from !== cursor ? { line: cursor.line, ch: token.end } : cursor;
    const suffix = line.slice(to.ch).trimStart().startsWith(';') ? '' : ';';
    editor.replaceRange(`${value}${suffix}`, from, to);
    editor.focus();
}

function openCssColorPicker(editor) {
    if (!editor || editor.getOption('readOnly')) return;
    const input = document.createElement('input');
    input.type = 'color';
    input.value = '#22d3ee';
    input.className = 'arena-css-color-picker';
    document.body.appendChild(input);
    const coords = editor.cursorCoords(null, 'page');
    input.style.left = `${coords.left}px`;
    input.style.top = `${coords.bottom + 6}px`;
    input.addEventListener('input', () => insertCssColor(editor, input.value));
    input.addEventListener('change', () => {
        insertCssColor(editor, input.value);
        input.remove();
    });
    input.addEventListener('blur', () => setTimeout(() => input.remove(), 120));
    input.click();
}

function handleEditorEnter(editor) {
    if (expandEditorAbbreviation(editor)) return;
    editor.execCommand('newlineAndIndent');
}

function getEditorExtraKeys() {
    return {
        'Ctrl-Space': showEditorHint,
        'Cmd-Space': showEditorHint,
        'Ctrl-/': (editor) => editor.toggleComment ? editor.toggleComment({ indent: true }) : null,
        'Cmd-/': (editor) => editor.toggleComment ? editor.toggleComment({ indent: true }) : null,
        'Alt-Up': (editor) => moveCurrentLine(editor, -1),
        'Alt-Down': (editor) => moveCurrentLine(editor, 1),
        'Shift-Alt-Up': duplicateCurrentLine,
        'Shift-Alt-Down': duplicateCurrentLine,
        'Ctrl-Shift-K': deleteCurrentLine,
        'Cmd-Shift-K': deleteCurrentLine,
        'Ctrl-D': selectNextOccurrence,
        'Cmd-D': selectNextOccurrence,
        'Shift-Alt-F': formatEditorSelection,
        'Ctrl-S': (editor) => {
            saveArenaToLocal();
            updatePreview();
            showToast('Code saved locally', 'success');
            editor.focus();
        },
        'Cmd-S': (editor) => {
            saveArenaToLocal();
            updatePreview();
            showToast('Code saved locally', 'success');
            editor.focus();
        },
        'Ctrl-Enter': () => runDiffCheck({ silent: false, live: false, save: true }),
        'Cmd-Enter': () => runDiffCheck({ silent: false, live: false, save: true }),
        'Ctrl-1': () => switchTab('html'),
        'Ctrl-2': () => switchTab('css'),
        'Ctrl-3': () => switchTab('js'),
        'Cmd-1': () => switchTab('html'),
        'Cmd-2': () => switchTab('css'),
        'Cmd-3': () => switchTab('js'),
        'Ctrl-E': (editor) => expandEditorAbbreviation(editor) || showEditorHint(editor),
        'Cmd-E': (editor) => expandEditorAbbreviation(editor) || showEditorHint(editor),
        'Alt-C': openCssColorPicker,
        'Enter': handleEditorEnter,
        'Tab': (editor) => {
            if (!editor.somethingSelected() && expandEditorAbbreviation(editor)) return;
            editor.somethingSelected() ? editor.execCommand('indentMore') : editor.replaceSelection('  ', 'end');
        },
        'Shift-Tab': (editor) => editor.execCommand('indentLess')
    };
}

function getEditorOptions(mode) {
    return {
        mode,
        theme: 'dracula',
        lineNumbers: true,
        tabSize: 2,
        indentUnit: 2,
        indentWithTabs: false,
        lineWrapping: false,
        autoCloseBrackets: true,
        autoCloseTags: mode === 'htmlmixed',
        matchBrackets: true,
        styleActiveLine: true,
        viewportMargin: Infinity,
        extraKeys: getEditorExtraKeys()
    };
}

// Initialize CodeMirror editors
function initEditors() {
    const htmlEditorElem = getElement('html-editor');
    const cssEditorElem = getElement('css-editor');
    const jsEditorElem = getElement('js-editor');
    
    if (!htmlEditorElem) return;
    
    htmlEditor = CodeMirror(htmlEditorElem, getEditorOptions('htmlmixed'));
    
    cssEditor = CodeMirror(cssEditorElem, getEditorOptions('css'));
    
    jsEditor = CodeMirror(jsEditorElem, getEditorOptions('javascript'));
    
    // Set initial content based on challenge type
    if (CHALLENGE_TYPE === 'html') {
        htmlEditor.setValue(STARTER_HTML || TARGET_HTML || '');
        if (HTML_LOCKED) {
            htmlEditor.setOption('readOnly', true);
            const htmlTab = document.querySelector('[data-tab="html"]');
            if (htmlTab) htmlTab.innerHTML = 'ðŸ”’ HTML';
        }
        cssEditor.setValue(STARTER_CSS || '');
        jsEditor.setValue('');
        // Switch to CSS tab by default
        switchTab('css');
    } else {
        htmlEditor.setValue('');
        cssEditor.setValue('');
        jsEditor.setValue('');
        switchTab('html');
    }
    
    // Restore from localStorage
    const savedHtml = getFromLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_html`);
    const savedCss = getFromLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_css`);
    const savedJs = getFromLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_js`);
    
    if (savedHtml && (!HTML_LOCKED || CHALLENGE_TYPE !== 'html')) htmlEditor.setValue(savedHtml);
    if (savedCss) cssEditor.setValue(savedCss);
    if (savedJs) jsEditor.setValue(savedJs);

    const cachedScore = readScoreCache();
    const currentHash = stableCodeHash();
    if (cachedScore.hash === currentHash && Number.isFinite(Number(cachedScore.accuracy))) {
        lastSavedCodeHash = cachedScore.hash;
        lastSavedScore = Number(cachedScore.accuracy);
        updateMyProgressBar(lastSavedScore);
        updateAccuracyBadge(lastSavedScore);
    }
    
    // Add change listeners
    htmlEditor.on('change', debounce(() => {
        updatePreview();
        saveArenaToLocal();
        lastSavedCodeHash = null;
        scheduleLiveDiffCheck(80);
        scheduleCodePreviewBroadcast();
    }, 120));
    
    cssEditor.on('change', debounce(() => {
        updatePreview();
        saveArenaToLocal();
        lastSavedCodeHash = null;
        scheduleLiveDiffCheck(80);
        scheduleCodePreviewBroadcast();
    }, 120));
    
    jsEditor.on('change', debounce(() => {
        updatePreview();
        saveArenaToLocal();
        lastSavedCodeHash = null;
        scheduleLiveDiffCheck(80);
        scheduleCodePreviewBroadcast();
    }, 120));
    
    // Cursor position display
    htmlEditor.on('cursorActivity', updateCursorPosition);
    cssEditor.on('cursorActivity', updateCursorPosition);
    jsEditor.on('cursorActivity', updateCursorPosition);
    [htmlEditor, cssEditor, jsEditor].forEach((editor) => {
        editor.on('inputRead', maybeShowEditorHint);
    });
    
    // Initially lock editors until challenge starts
    const isSpectator = USER_ROLE === 'spectator';
    const roomStatus = getElement('room-status')?.textContent?.trim().toUpperCase();
    const isWaiting = roomStatus === 'WAITING';
    const isEnded = roomStatus === 'ENDED';
    
    if (isSpectator || USER_ROLE === 'admin' || isWaiting || isEnded) {
        htmlEditor.setOption('readOnly', true);
        cssEditor.setOption('readOnly', true);
        jsEditor.setOption('readOnly', true);
    }

    if (isEnded) {
        const overlay = getElement('editor-overlay');
        if (overlay) {
            overlay.classList.remove('hidden');
            const overlayText = overlay.querySelector('.overlay-content span');
            if (overlayText) overlayText.textContent = 'Match ended. Coding is closed.';
        }
        ['submit-btn', 'reset-code-btn'].forEach((id) => {
            const btn = getElement(id);
            if (btn) btn.disabled = true;
        });
    }

    window.htmlEditor = htmlEditor;
    window.cssEditor = cssEditor;
    window.jsEditor = jsEditor;
}

function updateCursorPosition() {
    let editor, pos, mode;
    if (currentTab === 'html') {
        editor = htmlEditor;
        mode = 'HTML';
    } else if (currentTab === 'css') {
        editor = cssEditor;
        mode = 'CSS';
    } else {
        editor = jsEditor;
        mode = 'JS';
    }
    
    if (editor) {
        pos = editor.getCursor();
        const statusBar = getElement('cursor-position');
        if (statusBar) {
            statusBar.textContent = `Ln ${pos.line + 1}, Col ${pos.ch + 1}`;
        }
        const modeSpan = getElement('editor-mode');
        if (modeSpan) modeSpan.textContent = mode;
    }
}

function getPlayerInspectGuardScript() {
    if (!IS_PLAYER_ROLE) return '';
    return `<script>
        (() => {
            const warning = ${JSON.stringify(PLAYER_INSPECT_WARNING)};
            const report = (source) => {
                try {
                    window.parent?.postMessage({ type: 'arena-right-click-attempt', source }, '*');
                } catch (error) {}
            };
            const block = (event, source = 'embedded frame') => {
                event.preventDefault();
                event.stopPropagation();
                report(source);
                return false;
            };
            document.addEventListener('contextmenu', (event) => block(event, document.title || 'embedded frame'), true);
            document.addEventListener('keydown', (event) => {
                const key = String(event.key || '').toLowerCase();
                const blocked =
                    key === 'f12' ||
                    ((event.ctrlKey || event.metaKey) && event.shiftKey && ['i', 'j', 'c'].includes(key)) ||
                    ((event.ctrlKey || event.metaKey) && ['u', 's'].includes(key));
                if (blocked) block(event, 'embedded frame shortcut');
            }, true);
            document.documentElement.setAttribute('data-player-inspect-warning', warning);
        })();
    <\/script>`;
}

function updatePreview() {
    if (!htmlEditor || !cssEditor || !jsEditor) return;

    const html = htmlEditor.getValue();
    const css = cssEditor.getValue();
    const js = jsEditor.getValue();
    const guardScript = getPlayerInspectGuardScript();
    
    const doc = `<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>${css}</style>
    </head>
    <body>
        ${html}
        ${guardScript}
        <script>${js}<\/script>
    </body>
    </html>`;
    
    const outputFrame = getElement('output-frame');
    if (outputFrame) {
        outputFrame.srcdoc = doc;
        outputFrame.addEventListener('load', () => scheduleLiveDiffCheck(90), { once: true });
    }
}

function getScorableCode() {
    if (!htmlEditor || !cssEditor || !jsEditor) return '';
    if (CHALLENGE_TYPE === 'html' && HTML_LOCKED) {
        return `${cssEditor.getValue()}\n${jsEditor.getValue()}`.trim();
    }
    return `${htmlEditor.getValue()}\n${cssEditor.getValue()}\n${jsEditor.getValue()}`.trim();
}

function hasPlayerAttempted() {
    return getScorableCode().length > 0;
}

function setArenaMatchRunning(isRunning) {
    matchIsRunning = isRunning;
    if (isRunning && IS_PLAYER_ROLE) {
        scheduleLiveDiffCheck(120);
    } else if (liveDiffTimer) {
        clearTimeout(liveDiffTimer);
        liveDiffTimer = null;
    }
}

function canRunLiveDiff() {
    return matchIsRunning && IS_PLAYER_ROLE && Boolean(htmlEditor && cssEditor && jsEditor);
}

function scheduleLiveDiffCheck(delay = LIVE_DIFF_DELAY) {
    if (!canRunLiveDiff()) return;
    if (liveDiffTimer) clearTimeout(liveDiffTimer);
    liveDiffTimer = setTimeout(() => {
        liveDiffTimer = null;
        runDiffCheck({ silent: true, live: true, save: true, disableButton: false });
    }, delay);
}

function waitForFramePaint(frame) {
    return new Promise((resolve) => {
        if (!frame) {
            resolve();
            return;
        }
        const finish = () => requestAnimationFrame(() => requestAnimationFrame(resolve));
        try {
            if (frame.contentDocument?.readyState === 'complete') {
                finish();
            } else {
                frame.addEventListener('load', finish, { once: true });
                setTimeout(finish, 250);
            }
        } catch (err) {
            resolve();
        }
    });
}

function waitForImageLoad(img) {
    return new Promise((resolve, reject) => {
        if (!img) {
            resolve();
            return;
        }
        if (img.complete && img.naturalWidth > 0) {
            resolve();
            return;
        }
        img.addEventListener('load', resolve, { once: true });
        img.addEventListener('error', reject, { once: true });
        setTimeout(resolve, 1000);
    });
}

function getComparisonSize() {
    const outputSurface = document.querySelector('[data-zoom-surface="output"]');
    const targetSurface = document.querySelector('[data-zoom-surface="target"]');
    const outputRect = outputSurface?.getBoundingClientRect();
    const targetRect = targetSurface?.getBoundingClientRect();
    const width = Math.max(320, Math.round(Math.min(outputRect?.width || 640, targetRect?.width || outputRect?.width || 640)));
    const height = Math.max(240, Math.round(Math.min(outputRect?.height || 480, targetRect?.height || outputRect?.height || 480)));
    return {
        width: Math.min(width, 1200),
        height: Math.min(height, 900)
    };
}

function drawImageContain(ctx, image, width, height) {
    const sourceWidth = image.naturalWidth || image.videoWidth || image.width || width;
    const sourceHeight = image.naturalHeight || image.videoHeight || image.height || height;
    const scale = Math.min(width / Math.max(1, sourceWidth), height / Math.max(1, sourceHeight));
    const drawWidth = sourceWidth * scale;
    const drawHeight = sourceHeight * scale;
    ctx.drawImage(image, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight);
}

function fitCanvasIntoCanvas(sourceCanvas, width, height) {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);
    drawImageContain(ctx, sourceCanvas, width, height);
    return canvas;
}

async function captureFrameFullSurface(frame, width, height) {
    await waitForFramePaint(frame);
    const doc = frame.contentDocument || frame.contentWindow.document;
    const body = doc.body;
    const root = doc.documentElement;
    const fullWidth = Math.max(width, body?.scrollWidth || 0, root?.scrollWidth || 0, body?.offsetWidth || 0, root?.clientWidth || 0);
    const fullHeight = Math.max(height, body?.scrollHeight || 0, root?.scrollHeight || 0, body?.offsetHeight || 0, root?.clientHeight || 0);
    const renderWidth = Math.min(Math.max(width, fullWidth), 1800);
    const renderHeight = Math.min(Math.max(height, fullHeight), 1400);
    const rawCanvas = await html2canvas(body, {
        width: renderWidth,
        height: renderHeight,
        windowWidth: renderWidth,
        windowHeight: renderHeight,
        scrollX: 0,
        scrollY: 0,
        scale: 1,
        backgroundColor: '#ffffff',
        useCORS: true,
        logging: false
    });
    return fitCanvasIntoCanvas(rawCanvas, width, height);
}

function saveArenaToLocal() {
    if (!HTML_LOCKED || CHALLENGE_TYPE !== 'html') {
        window.saveToLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_html`, htmlEditor.getValue());
    }
    window.saveToLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_css`, cssEditor.getValue());
    window.saveToLocal(`arena_${ROOM_ID}_${CURRENT_USERNAME}_js`, jsEditor.getValue());
}

// Tab switching
function switchTab(tab) {
    currentTab = tab;
    
    const htmlEditorDiv = getElement('html-editor');
    const cssEditorDiv = getElement('css-editor');
    const jsEditorDiv = getElement('js-editor');
    const tabs = document.querySelectorAll('.tab-btn');
    
    if (htmlEditorDiv) htmlEditorDiv.style.display = tab === 'html' ? 'block' : 'none';
    if (cssEditorDiv) cssEditorDiv.style.display = tab === 'css' ? 'block' : 'none';
    if (jsEditorDiv) jsEditorDiv.style.display = tab === 'js' ? 'block' : 'none';
    
    tabs.forEach(btn => {
        if (btn.dataset.tab === tab) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    
    // Refresh CodeMirror
    if (tab === 'html' && htmlEditor) htmlEditor.refresh();
    if (tab === 'css' && cssEditor) cssEditor.refresh();
    if (tab === 'js' && jsEditor) jsEditor.refresh();
    
    updateCursorPosition();
}

// Initialize target based on challenge type
function initTarget() {
    const targetImg = getElement('target-image');
    const targetFrame = getElement('target-frame');
    
    if (CHALLENGE_TYPE === 'html') {
        if (targetImg) targetImg.style.display = 'none';
        if (targetFrame) {
            targetFrame.style.display = 'block';
            const guardScript = getPlayerInspectGuardScript();
            const targetDoc = `<!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>${TARGET_CSS || ''}</style>
            </head>
            <body>
                ${TARGET_HTML || ''}
                ${guardScript}
            </body>
            </html>`;
            targetFrame.srcdoc = targetDoc;
        }
        const typeLabel = getElement('target-type-label');
        if (typeLabel) typeLabel.textContent = 'HTML Target';
    } else {
        if (targetFrame) targetFrame.style.display = 'none';
        if (targetImg && TARGET_IMAGE_URL) {
            targetImg.style.display = 'block';
            targetImg.src = TARGET_IMAGE_URL;
        }
        const typeLabel = getElement('target-type-label');
        if (typeLabel) typeLabel.textContent = 'Image Target';
    }
}

function compareMeaningfulPixels(outPixels, targetPixels, diffPixels, width, height, threshold = 0.12) {
    let mismatched = 0;
    let compared = 0;
    const limit = width * height * 4;
    const thresholdValue = threshold * 255;
    const whiteCutoff = 246;

    function isMeaningfulPixel(pixels, i) {
        const alpha = pixels[i + 3];
        if (alpha < 20) return false;
        return pixels[i] < whiteCutoff || pixels[i + 1] < whiteCutoff || pixels[i + 2] < whiteCutoff;
    }

    for (let i = 0; i < limit; i += 4) {
        const dr = Math.abs(outPixels[i] - targetPixels[i]);
        const dg = Math.abs(outPixels[i + 1] - targetPixels[i + 1]);
        const db = Math.abs(outPixels[i + 2] - targetPixels[i + 2]);
        const da = Math.abs(outPixels[i + 3] - targetPixels[i + 3]);
        const delta = (dr + dg + db + da) / 4;
        const shouldCompare = isMeaningfulPixel(targetPixels, i) || isMeaningfulPixel(outPixels, i) || delta > thresholdValue;
        const isMismatch = delta > thresholdValue;

        if (shouldCompare) {
            compared++;
            if (isMismatch) mismatched++;
        }

        if (!shouldCompare) {
            diffPixels[i] = 24;
            diffPixels[i + 1] = 30;
            diffPixels[i + 2] = 44;
            diffPixels[i + 3] = 50;
        } else {
            diffPixels[i] = isMismatch ? 255 : 80;
            diffPixels[i + 1] = isMismatch ? 82 : 255;
            diffPixels[i + 2] = isMismatch ? 112 : 150;
            diffPixels[i + 3] = isMismatch ? 230 : 180;
        }
    }

    return { mismatched, compared };
}

async function saveAndBroadcastScore(accuracy, { live = false } = {}) {
    if (!IS_PLAYER_ROLE) return;
    if (!matchIsRunning && live) return;

    const now = Date.now();
    if (live && now - lastLiveSaveAt < LIVE_SAVE_INTERVAL) {
        return { accuracy: lastSavedScore ?? 0, scoreDetails: {}, skipped: true };
    }
    const codeHash = stableCodeHash();
    if (live && lastSavedCodeHash === codeHash && Number.isFinite(Number(lastSavedScore))) {
        return { accuracy: lastSavedScore, scoreDetails: {}, skipped: true };
    }

    const response = await fetch('/submission/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            room_id: ROOM_ID,
            challenge_id: CHALLENGE_ID || null,
            html_code: htmlEditor.getValue(),
            css_code: cssEditor.getValue(),
            js_code: jsEditor.getValue(),
            accuracy: accuracy,
            code_hash: codeHash
        })
    });

    if (!response.ok) {
        throw new Error('Could not save submission');
    }
    const data = await response.json();
    const serverAccuracy = Number.isFinite(Number(data.accuracy)) ? Number(data.accuracy) : accuracy;
    lastLiveSaveAt = now;
    writeScoreCache(codeHash, serverAccuracy);

    if (window.socket) {
        window.socket.emit('progress_update', {
            room_id: ROOM_ID,
            username: CURRENT_USERNAME,
            accuracy: serverAccuracy
        });
    }
    return { accuracy: serverAccuracy, scoreDetails: data.score_details || {} };
}

function stableCodeHash() {
    const normalizeForOutput = (value, kind) => {
        let text = String(value || '');
        if (kind === 'css') {
            text = text.replace(/\/\*[\s\S]*?\*\//g, '');
        }
        if (kind === 'js') {
            text = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\n)\s*\/\/.*(?=\n|$)/g, '$1');
        }
        return text.replace(/\s+/g, ' ').trim();
    };
    const text = JSON.stringify({
        room: ROOM_ID,
        challenge: CHALLENGE_ID,
        html: normalizeForOutput(htmlEditor?.getValue(), 'html'),
        css: normalizeForOutput(cssEditor?.getValue(), 'css'),
        js: normalizeForOutput(jsEditor?.getValue(), 'js')
    });
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
        hash ^= text.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
}

function readScoreCache() {
    try {
        return JSON.parse(localStorage.getItem(SCORE_CACHE_KEY) || '{}');
    } catch (error) {
        return {};
    }
}

function writeScoreCache(hash, accuracy) {
    lastSavedCodeHash = hash;
    lastSavedScore = Math.max(0, Math.min(100, Number(accuracy) || 0));
    try {
        localStorage.setItem(SCORE_CACHE_KEY, JSON.stringify({
            hash,
            accuracy: lastSavedScore,
            savedAt: Date.now()
        }));
    } catch (error) {}
}

// Diff check system
async function runDiffCheck(options = {}) {
    const {
        silent = false,
        live = false,
        save = true,
        disableButton = true
    } = options;

    if (!htmlEditor || !cssEditor || !jsEditor || !IS_PLAYER_ROLE) return 0;

    if (diffInProgress) {
        diffPending = true;
        return 0;
    }
    diffInProgress = true;

    const btn = getElement('submit-btn');
    if (btn && disableButton) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
    }
    
    try {
        if (!hasPlayerAttempted()) {
            clearDiffViews();
            updateMyProgressBar(0);
            updateAccuracyBadge(0);
            if (save) {
                const saved = await saveAndBroadcastScore(0, { live });
                updateMyProgressBar(saved.accuracy);
                updateAccuracyBadge(saved.accuracy);
            }
            if (!silent) {
                showToast('No code entered yet. Score is 0%.', 'info');
            }
            return 0;
        }

        const { width: W, height: H } = getComparisonSize();
        
        // Screenshot player's output
        const outputFrame = getElement('output-frame');
        if (!outputFrame) throw new Error('Output frame not found');

        const outputCanvas = await captureFrameFullSurface(outputFrame, W, H);
        
        // Get target canvas
        const targetCanvas = document.createElement('canvas');
        targetCanvas.width = W;
        targetCanvas.height = H;
        const tCtx = targetCanvas.getContext('2d');
        tCtx.fillStyle = '#ffffff';
        tCtx.fillRect(0, 0, W, H);
        
        if (CHALLENGE_TYPE === 'image') {
            const targetImg = getElement('target-image');
            await waitForImageLoad(targetImg);
            if (targetImg && targetImg.complete && targetImg.naturalWidth > 0) {
                drawImageContain(tCtx, targetImg, W, H);
            }
        } else {
            const targetFrame = getElement('target-frame');
            if (targetFrame) {
                const tFrameCanvas = await captureFrameFullSurface(targetFrame, W, H);
                tCtx.drawImage(tFrameCanvas, 0, 0, W, H);
            }
        }
        
        // Run pixelmatch
        const outData = outputCanvas.getContext('2d').getImageData(0, 0, W, H);
        const tgtData = targetCanvas.getContext('2d').getImageData(0, 0, W, H);
        
        const diffCanvas = getElement('diff-canvas');
        if (diffCanvas) {
            diffCanvas.width = W;
            diffCanvas.height = H;
            diffCanvas.style.aspectRatio = `${W} / ${H}`;
            const dCtx = diffCanvas.getContext('2d');
            const diffImgData = dCtx.createImageData(W, H);
            
            const result = compareMeaningfulPixels(
                outData.data, tgtData.data, diffImgData.data,
                W, H, 0.035
            );
            
            dCtx.putImageData(diffImgData, 0, 0);
            
            // Calculate accuracy
            const total = result.compared || W * H;
            const accuracy = result.compared > 0
                ? parseFloat((((total - result.mismatched) / total) * 100).toFixed(1))
                : 0;
            
            // The badge can show the immediate visual diff, but the trusted
            // progress bar only moves after the server returns the canonical score.
            updateAccuracyBadge(accuracy);
            
            // Populate slider canvases
            populateSliderCanvases(outputCanvas, targetCanvas);
            
            let finalAccuracy = accuracy;
            if (save) {
                const saved = await saveAndBroadcastScore(accuracy, { live });
                finalAccuracy = Number.isFinite(Number(saved?.accuracy)) ? Number(saved.accuracy) : accuracy;
                updateMyProgressBar(finalAccuracy);
                updateAccuracyBadge(finalAccuracy);
            }
            
            if (!silent) {
                showToast(`Score: ${finalAccuracy}% match`, finalAccuracy >= 80 ? 'success' : 'info');
            }
            return finalAccuracy;
        }
    } catch (err) {
        console.error('Diff failed:', err);
        if (!silent) {
            showToast('Comparison failed. Try again.', 'error');
        }
    } finally {
        diffInProgress = false;
        if (btn && disableButton) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-check-circle"></i> SUBMIT & CHECK';
        }
        if (diffPending) {
            diffPending = false;
            scheduleLiveDiffCheck(150);
        }
    }
    return 0;
}

function updateMyProgressBar(accuracy) {
    if (!IS_PLAYER_ROLE) return;
    const isP1 = USER_ROLE === 'player1';
    const barId = isP1 ? 'p1-progress-fill' : 'p2-progress-fill';
    const lblId = isP1 ? 'p1-accuracy-label' : 'p2-accuracy-label';
    
    const bar = getElement(barId);
    const label = getElement(lblId);
    
    const safeAccuracy = Math.max(0, Math.min(100, Number(accuracy) || 0));
    if (bar) bar.style.width = safeAccuracy + '%';
    if (label) {
        label.textContent = safeAccuracy.toFixed(1) + '%';
        label.classList.add('flash-update');
        setTimeout(() => label.classList.remove('flash-update'), 600);
    }
}

function updateAccuracyBadge(accuracy) {
    const badge = getElement('accuracy-badge');
    if (badge) {
        const safeAccuracy = Math.max(0, Math.min(100, Number(accuracy) || 0));
        badge.textContent = safeAccuracy.toFixed(1) + '% MATCH';
        const stateClass = safeAccuracy >= 80 ? 'badge-success' :
                         safeAccuracy >= 50 ? 'badge-warning' : 'badge-danger';
        badge.className = `accuracy-badge ${stateClass}`;
    }
}

function applyInitialScoreState() {
    const p1Name = arenaConfig.player1Username || '';
    const p2Name = arenaConfig.player2Username || '';
    const ownInitial = Number(INITIAL_SCORES[CURRENT_USERNAME]);
    if (IS_PLAYER_ROLE && Number.isFinite(ownInitial)) {
        updateMyProgressBar(ownInitial);
        updateAccuracyBadge(ownInitial);
    }
    [
        { name: p1Name, bar: 'p1-progress-fill', label: 'p1-accuracy-label' },
        { name: p2Name, bar: 'p2-progress-fill', label: 'p2-accuracy-label' }
    ].forEach((item) => {
        if (!item.name || !Object.prototype.hasOwnProperty.call(INITIAL_SCORES, item.name)) return;
        const accuracy = Math.max(0, Math.min(100, Number(INITIAL_SCORES[item.name]) || 0));
        const bar = getElement(item.bar);
        const label = getElement(item.label);
        if (bar) bar.style.width = `${accuracy}%`;
        if (label) label.textContent = `${accuracy.toFixed(1)}%`;
    });
}

window.addEventListener('arena-score-state', (event) => {
    const score = event.detail || {};
    if (score.username !== CURRENT_USERNAME) return;
    const accuracy = Math.max(0, Math.min(100, Number(score.accuracy) || 0));
    lastSavedScore = accuracy;
    if (htmlEditor && cssEditor && jsEditor) {
        writeScoreCache(stableCodeHash(), accuracy);
    }
    updateMyProgressBar(accuracy);
    updateAccuracyBadge(accuracy);
});

function initRefreshGuard() {
    if (!IS_PLAYER_ROLE) return;
    window.addEventListener('beforeunload', (event) => {
        if (!matchIsRunning || !hasPlayerAttempted()) return;
        event.preventDefault();
        event.returnValue = 'Your code is saved locally, but refreshing during a live match can interrupt your flow.';
        return event.returnValue;
    });
}

function initArenaInspectGuards() {
    if (!document.querySelector('.arena-root') || !IS_PLAYER_ROLE) return;
    const reportAttempt = (source = 'arena page') => {
        const now = Date.now();
        if (now - lastRightClickReportAt < 1500) return;
        lastRightClickReportAt = now;
        if (window.socket) {
            window.socket.emit('right_click_attempt', {
                room_id: ROOM_ID,
                username: CURRENT_USERNAME,
                source,
                blocked: true
            });
        }
    };
    document.addEventListener('contextmenu', (event) => {
        event.preventDefault();
        event.stopPropagation();
        reportAttempt('arena page');
        showToast(PLAYER_INSPECT_WARNING, 'warning');
    });
    document.addEventListener('keydown', (event) => {
        const key = String(event.key || '').toLowerCase();
        const blocked =
            key === 'f12' ||
            ((event.ctrlKey || event.metaKey) && event.shiftKey && ['i', 'j', 'c'].includes(key)) ||
            ((event.ctrlKey || event.metaKey) && ['u', 's'].includes(key));
        if (blocked) {
            event.preventDefault();
            event.stopPropagation();
            reportAttempt('inspect/source shortcut');
            showToast(PLAYER_INSPECT_WARNING, 'warning');
        }
    }, true);
    window.addEventListener('message', (event) => {
        if (event?.data?.type !== 'arena-right-click-attempt') return;
        reportAttempt(event.data.source || 'embedded frame');
        showToast(PLAYER_INSPECT_WARNING, 'warning');
    });
}

function clearDiffViews() {
    const diffCanvas = getElement('diff-canvas');
    if (diffCanvas) {
        diffCanvas.width = 400;
        diffCanvas.height = 300;
        const ctx = diffCanvas.getContext('2d');
        ctx.clearRect(0, 0, diffCanvas.width, diffCanvas.height);
    }

    ['slider-output-canvas', 'slider-target-canvas'].forEach(id => {
        const canvas = getElement(id);
        if (!canvas) return;
        canvas.width = 400;
        canvas.height = 300;
        canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
    });
}

// Slider diff functions
function initSlider() {
    const container = getElement('slider-diff-container');
    const slider = getElement('comparison-opacity-slider');
    const pills = container?.querySelectorAll('[data-compare-mode]');

    if (!container || !slider || sliderInitialized) return;
    sliderInitialized = true;
    container.dataset.compareMode = sliderMode;

    slider.addEventListener('input', () => {
        updateSliderPosition(slider.value);
        applySliderMode('opacity');
    });

    pills.forEach((pill) => {
        pill.addEventListener('click', () => applySliderMode(pill.dataset.compareMode || 'opacity'));
    });

    updateSliderPosition(sliderPercent);
    applySliderMode(sliderMode);
}

function updateSliderPosition(percent) {
    const slider = getElement('comparison-opacity-slider');
    const outputLayer = getElement('slider-output-layer');
    const nextPercent = Math.max(0, Math.min(100, Number(percent) || 0));

    sliderPercent = nextPercent;
    if (slider) {
        slider.value = String(Math.round(nextPercent));
        slider.style.setProperty('background', `linear-gradient(to right, #ff6b35 0%, #ff6b35 ${nextPercent}%, #1e1e35 ${nextPercent}%, #1e1e35 100%)`, 'important');
    }
    if (outputLayer && sliderMode === 'opacity') {
        outputLayer.style.opacity = String(nextPercent / 100);
    }
}

function applySliderMode(mode) {
    const nextMode = ['overlay', 'diff', 'opacity'].includes(mode) ? mode : 'opacity';
    const container = getElement('slider-diff-container');
    const outputLayer = getElement('slider-output-layer');
    const slider = getElement('comparison-opacity-slider');
    const pills = document.querySelectorAll('[data-compare-mode]');

    sliderMode = nextMode;
    if (container) container.dataset.compareMode = nextMode;

    pills.forEach((pill) => {
        pill.classList.toggle('active', pill.dataset.compareMode === nextMode);
        pill.setAttribute('aria-pressed', pill.dataset.compareMode === nextMode ? 'true' : 'false');
    });

    if (slider) {
        slider.disabled = nextMode !== 'opacity';
        slider.setAttribute('aria-disabled', nextMode !== 'opacity' ? 'true' : 'false');
    }

    if (outputLayer) {
        outputLayer.style.mixBlendMode = nextMode === 'diff' ? 'difference' : 'normal';
        outputLayer.style.opacity = nextMode === 'opacity' ? String(sliderPercent / 100) : '1';
    }

    if (nextMode === 'opacity') {
        updateSliderPosition(sliderPercent);
    } else if (slider) {
        slider.style.setProperty('background', `linear-gradient(to right, #ff6b35 0%, #ff6b35 ${sliderPercent}%, #1e1e35 ${sliderPercent}%, #1e1e35 100%)`, 'important');
    }
}

function populateSliderCanvases(outputCanvas, targetCanvas) {
    const sliderOut = getElement('slider-output-canvas');
    const sliderTgt = getElement('slider-target-canvas');
    
    if (sliderOut) {
        sliderOut.width = outputCanvas.width;
        sliderOut.height = outputCanvas.height;
        sliderOut.getContext('2d').drawImage(outputCanvas, 0, 0);
    }
    
    if (sliderTgt) {
        sliderTgt.width = targetCanvas.width;
        sliderTgt.height = targetCanvas.height;
        sliderTgt.getContext('2d').drawImage(targetCanvas, 0, 0);
    }
    
    updateSliderPosition(sliderPercent || 50);
    applySliderMode(sliderMode);
}

// Diff view toggle
function initDiffToggle() {
    const pixelBtn = document.querySelector('[data-view="pixel"]');
    const sliderBtn = document.querySelector('[data-view="slider"]');
    const diffCanvas = getElement('diff-canvas');
    const sliderContainer = getElement('slider-diff-container');
    
    if (pixelBtn) {
        pixelBtn.addEventListener('click', () => {
            if (diffCanvas) diffCanvas.style.display = 'block';
            if (sliderContainer) sliderContainer.style.display = 'none';
            pixelBtn.classList.add('active');
            if (sliderBtn) sliderBtn.classList.remove('active');
        });
    }
    
    if (sliderBtn) {
        sliderBtn.addEventListener('click', () => {
            if (diffCanvas) diffCanvas.style.display = 'none';
            if (sliderContainer) sliderContainer.style.display = 'flex';
            sliderBtn.classList.add('active');
            if (pixelBtn) pixelBtn.classList.remove('active');
            initSlider();
        });
    }
}

const ArenaMedia = (() => {
    const peers = new Map();
    const knownPeers = new Map();
    let localStream = null;

    const rtcConfig = {
        iceServers: [
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' }
        ]
    };

    function safeMediaId(username) {
        return `remote-media-${String(username).replace(/[^a-zA-Z0-9_-]/g, '-')}`;
    }

    function shouldCreateOffer(username) {
        return CURRENT_USERNAME.localeCompare(username) < 0;
    }

    function getRemoteMediaTile(username, role) {
        const remoteCams = getElement('remote-cams');
        if (!remoteCams || !username) return null;

        remoteCams.closest('.cam-container')?.classList.add('has-remote');
        const placeholder = getElement('cam-placeholder');
        if (placeholder) placeholder.style.display = 'none';

        const id = safeMediaId(username);
        let item = getElement(id);
        if (!item) {
            item = document.createElement('div');
            item.className = 'remote-cam-tile remote-media-tile';
            item.id = id;
            item.innerHTML = '<video autoplay playsinline></video><span></span>';
            remoteCams.appendChild(item);
        }
        item.querySelector('span').textContent = role === 'admin' ? `${username} (Admin)` : username;
        return item;
    }

    function removeRemoteMedia(username) {
        const item = getElement(safeMediaId(username));
        if (item) item.remove();
    }

    function closePeer(username) {
        const existing = peers.get(username);
        if (existing) {
            existing.close();
            peers.delete(username);
        }
        removeRemoteMedia(username);
    }

    function attachLocalTracks(peer) {
        if (!localStream || !peer) return;
        const senderTracks = new Set(peer.getSenders().map((sender) => sender.track).filter(Boolean));
        localStream.getTracks().forEach((track) => {
            if (!senderTracks.has(track)) {
                peer.addTrack(track, localStream);
            }
        });
    }

    function createPeer(username, role) {
        if (!window.RTCPeerConnection || !username || username === CURRENT_USERNAME) {
            return null;
        }
        if (peers.has(username)) {
            const existing = peers.get(username);
            attachLocalTracks(existing);
            return existing;
        }

        const peer = new RTCPeerConnection(rtcConfig);
        peers.set(username, peer);
        attachLocalTracks(peer);

        peer.onicecandidate = (event) => {
            if (!event.candidate || !window.socket) return;
            window.socket.emit('media_ice_candidate', {
                room_id: ROOM_ID,
                to: username,
                candidate: event.candidate
            });
        };

        peer.ontrack = (event) => {
            const [stream] = event.streams;
            const tile = getRemoteMediaTile(username, role);
            const video = tile?.querySelector('video');
            if (video && stream && video.srcObject !== stream) {
                video.srcObject = stream;
                video.play?.().catch(() => {});
            }
        };

        peer.onconnectionstatechange = () => {
            if (['closed', 'failed', 'disconnected'].includes(peer.connectionState)) {
                closePeer(username);
            }
        };

        return peer;
    }

    async function createOffer(username, role) {
        const peer = createPeer(username, role);
        if (!peer || !window.socket || !localStream) return;
        attachLocalTracks(peer);
        const offer = await peer.createOffer();
        await peer.setLocalDescription(offer);
        window.socket.emit('media_offer', {
            room_id: ROOM_ID,
            to: username,
            offer
        });
    }

    function announceReady() {
        if (!window.socket || !localStream) return;
        window.socket.emit('media_ready', {
            room_id: ROOM_ID,
            has_audio: localStream.getAudioTracks().length > 0,
            has_video: localStream.getVideoTracks().length > 0
        });
    }

    async function start(stream) {
        localStream = stream;
        announceReady();
        for (const [username, role] of knownPeers.entries()) {
            await createOffer(username, role).catch((err) => console.error('Media offer error:', err));
        }
    }

    function bindSocket(socketInstance) {
        if (!socketInstance || socketInstance.__arenaMediaBound) return;
        socketInstance.__arenaMediaBound = true;

        socketInstance.on('connect', () => {
            if (localStream) setTimeout(announceReady, 300);
        });

        socketInstance.on('media_peer_ready', async (data = {}) => {
            if (Number(data.room_id) !== ROOM_ID || !data.username || data.username === CURRENT_USERNAME) return;
            knownPeers.set(data.username, data.role || 'player');
            if (localStream && shouldCreateOffer(data.username)) {
                await createOffer(data.username, data.role || 'player').catch((err) => console.error('Media offer error:', err));
            }
        });

        socketInstance.on('media_offer', async (data = {}) => {
            if (Number(data.room_id) !== ROOM_ID || !data.from || data.from === CURRENT_USERNAME || !localStream) return;
            knownPeers.set(data.from, data.role || 'player');
            const peer = createPeer(data.from, data.role || 'player');
            if (!peer) return;
            await peer.setRemoteDescription(new RTCSessionDescription(data.offer));
            const answer = await peer.createAnswer();
            await peer.setLocalDescription(answer);
            socketInstance.emit('media_answer', {
                room_id: ROOM_ID,
                to: data.from,
                answer
            });
        });

        socketInstance.on('media_answer', async (data = {}) => {
            if (Number(data.room_id) !== ROOM_ID || !data.from || data.from === CURRENT_USERNAME) return;
            const peer = peers.get(data.from);
            if (!peer || peer.signalingState === 'stable') return;
            await peer.setRemoteDescription(new RTCSessionDescription(data.answer));
        });

        socketInstance.on('media_ice_candidate', async (data = {}) => {
            if (Number(data.room_id) !== ROOM_ID || !data.from || data.from === CURRENT_USERNAME) return;
            const peer = peers.get(data.from);
            if (!peer || !data.candidate) return;
            await peer.addIceCandidate(new RTCIceCandidate(data.candidate)).catch((err) => console.error('ICE candidate error:', err));
        });

        socketInstance.on('media_peer_left', (data = {}) => {
            if (Number(data.room_id) !== ROOM_ID || !data.username) return;
            knownPeers.delete(data.username);
            closePeer(data.username);
        });

        window.addEventListener('beforeunload', () => {
            if (localStream) socketInstance.emit('media_leave', { room_id: ROOM_ID });
        });
    }

    return { start, bindSocket };
})();

window.ArenaMedia = ArenaMedia;
if (window.socket) ArenaMedia.bindSocket(window.socket);

// Camera setup
async function setupCamera() {
    if (!CAN_PUBLISH_MEDIA) return;
    const camFeed = getElement('cam-feed');
    const camPlaceholder = getElement('cam-placeholder');
    const recBadge = getElement('rec-badge');
    const enableBtn = getElement('enable-cam-btn');
    
    if (!camFeed) return;

    function getCameraSupportMessage() {
        const host = window.location.hostname;
        const isLocalHost = ['localhost', '127.0.0.1', '::1'].includes(host);
        const isSecureCameraContext = window.isSecureContext || isLocalHost;

        if (!isSecureCameraContext) {
            return 'Camera access needs HTTPS after deployment. Local testing works on localhost or 127.0.0.1.';
        }

        if (!navigator.mediaDevices?.getUserMedia) {
            return 'This browser does not support camera access here. Try Chrome, Edge, or Firefox with camera permissions enabled.';
        }

        return '';
    }

    function mediaErrorMessage(err) {
        const name = err?.name || '';
        if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
            return 'Camera or microphone permission was blocked. Open site settings for this page and allow camera and microphone.';
        }
        if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
            return 'No camera or microphone was found by this browser. Check browser site settings, OS privacy settings, and try opening the Render URL directly in Chrome or Safari.';
        }
        if (name === 'NotReadableError' || name === 'TrackStartError') {
            return 'The camera or microphone is already being used by another app. Close other camera apps and try again.';
        }
        if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') {
            return 'This device could not use the requested camera settings. Retrying with simpler settings.';
        }
        return err?.message || 'Could not access camera or microphone';
    }

    async function requestMediaStream() {
        const preferredConstraints = {
            video: {
                facingMode: 'user',
                width: { ideal: 640 },
                height: { ideal: 480 }
            },
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        };

        try {
            return await navigator.mediaDevices.getUserMedia(preferredConstraints);
        } catch (err) {
            if (err?.name !== 'OverconstrainedError' && err?.name !== 'ConstraintNotSatisfiedError') {
                throw err;
            }
            return navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        }
    }
    
    async function enableCamera() {
        try {
            const supportMessage = getCameraSupportMessage();
            if (supportMessage) {
                throw new Error(supportMessage);
            }
            const stream = await requestMediaStream();
            camFeed.srcObject = stream;
            if (camPlaceholder) camPlaceholder.style.display = 'none';
            if (recBadge) recBadge.style.display = 'inline-flex';
            camFeed.style.display = 'block';
            if (window.ArenaMedia?.start) {
                window.ArenaMedia.start(stream);
            }
            
            // Broadcast frames
            const canvas = document.createElement('canvas');
            canvas.width = 160;
            canvas.height = 120;
            const ctx = canvas.getContext('2d');
            
            if (window.arenaCamInterval) clearInterval(window.arenaCamInterval);
            window.arenaCamInterval = setInterval(() => {
                if (camFeed.readyState >= camFeed.HAVE_ENOUGH_DATA) {
                    ctx.drawImage(camFeed, 0, 0, 160, 120);
                    if (window.socket) {
                        window.socket.emit('cam_frame', {
                            room_id: ROOM_ID,
                            username: CURRENT_USERNAME,
                            frame_data: canvas.toDataURL('image/jpeg', 0.3)
                        });
                    }
                }
            }, 2000);
        } catch (err) {
            console.error('Camera error:', err);
            const message = mediaErrorMessage(err);
            if (camPlaceholder) {
                camPlaceholder.style.display = 'block';
                const text = camPlaceholder.querySelector('p');
                if (text) text.textContent = message;
            }
            showToast(message, 'error');
        }
    }
    
    if (enableBtn) {
        enableBtn.addEventListener('click', enableCamera);
    } else {
        enableCamera();
    }
    window.requestArenaMedia = enableCamera;
}

function initMediaSettings() {
    if (!CAN_PUBLISH_MEDIA) return;

    const allowBtn = getElement('media-permission-btn');
    const cameraState = getElement('camera-permission-state');
    const microphoneState = getElement('microphone-permission-state');
    const note = getElement('media-settings-note');
    const broadcastBtn = getElement('admin-voice-broadcast-btn');
    let broadcastRecorder = null;
    let broadcastStream = null;

    function setState(el, state) {
        if (!el) return;
        const label = state === 'granted' ? 'Allowed' : state === 'denied' ? 'Blocked' : state === 'prompt' ? 'Ask' : 'Unknown';
        el.textContent = label;
        el.dataset.state = state || 'unknown';
    }

    async function readPermission(name) {
        if (!navigator.permissions?.query) return 'unknown';
        try {
            const status = await navigator.permissions.query({ name });
            status.onchange = updatePermissionStatus;
            return status.state;
        } catch (err) {
            return 'unknown';
        }
    }

    async function updatePermissionStatus() {
        const [camera, microphone] = await Promise.all([
            readPermission('camera'),
            readPermission('microphone')
        ]);
        setState(cameraState, camera);
        setState(microphoneState, microphone);

        if (note) {
            if (camera === 'denied' || microphone === 'denied') {
                note.textContent = 'Blocked in browser site settings';
            } else if (camera === 'granted' && microphone === 'granted') {
                note.textContent = USER_ROLE === 'admin' ? 'Admin media ready' : 'Player media ready';
            } else {
                note.textContent = 'Tap Allow Media to continue';
            }
        }
    }

    async function requestMediaFromSettings() {
        if (window.requestArenaMedia) {
            await window.requestArenaMedia();
        } else {
            getElement('enable-cam-btn')?.click();
        }
        setTimeout(updatePermissionStatus, 250);
    }

    function getSupportedAudioMime() {
        const options = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/mp4',
            ''
        ];
        return options.find((type) => !type || MediaRecorder.isTypeSupported(type)) || '';
    }

    async function startVoiceBroadcast() {
        if (USER_ROLE !== 'admin' || !window.socket) return;
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
            showToast('This browser cannot record microphone broadcasts.', 'error');
            return;
        }

        try {
            broadcastStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                },
                video: false
            });
            const mimeType = getSupportedAudioMime();
            broadcastRecorder = new MediaRecorder(broadcastStream, mimeType ? { mimeType } : undefined);
            broadcastRecorder.ondataavailable = (event) => {
                if (!event.data || event.data.size === 0) return;
                const reader = new FileReader();
                reader.onload = () => {
                    window.socket.emit('voice_broadcast_chunk', {
                        room_id: ROOM_ID,
                        chunk: reader.result
                    });
                };
                reader.readAsDataURL(event.data);
            };
            broadcastRecorder.onstop = () => {
                window.socket.emit('voice_broadcast_end', { room_id: ROOM_ID });
                broadcastStream?.getTracks().forEach((track) => track.stop());
                broadcastStream = null;
                broadcastRecorder = null;
                if (broadcastBtn) {
                    broadcastBtn.classList.remove('active');
                    broadcastBtn.innerHTML = '<i class="fas fa-bullhorn"></i> Broadcast Mic';
                }
            };
            window.socket.emit('voice_broadcast_start', { room_id: ROOM_ID });
            broadcastRecorder.start(900);
            if (broadcastBtn) {
                broadcastBtn.classList.add('active');
                broadcastBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Broadcast';
            }
            showToast('Voice broadcast started', 'success');
            setTimeout(updatePermissionStatus, 250);
        } catch (err) {
            console.error('Voice broadcast error:', err);
            showToast('Microphone broadcast could not start. Check site microphone permission.', 'error');
            setTimeout(updatePermissionStatus, 250);
        }
    }

    function stopVoiceBroadcast() {
        if (broadcastRecorder && broadcastRecorder.state !== 'inactive') {
            broadcastRecorder.stop();
        }
    }

    if (allowBtn) allowBtn.addEventListener('click', requestMediaFromSettings);
    if (broadcastBtn) {
        broadcastBtn.addEventListener('click', () => {
            if (broadcastRecorder && broadcastRecorder.state !== 'inactive') {
                stopVoiceBroadcast();
            } else {
                startVoiceBroadcast();
            }
        });
    }

    updatePermissionStatus();
}

// Reset code
async function resetCode() {
    const confirmed = await showConfirm('Reset your code? This cannot be undone.', 'Reset code');
    if (!confirmed) return;
    if (CHALLENGE_TYPE === 'html' && HTML_LOCKED) {
        // Only reset CSS and JS
        cssEditor.setValue(STARTER_CSS || '');
        jsEditor.setValue('');
        showToast('CSS reset to the admin starter CSS. HTML structure preserved.', 'info');
    } else if (CHALLENGE_TYPE === 'html') {
        htmlEditor.setValue(STARTER_HTML || TARGET_HTML || '');
        cssEditor.setValue(STARTER_CSS || '');
        jsEditor.setValue('');
        showToast('Code reset to the admin starter code.', 'info');
    } else {
        htmlEditor.setValue('');
        cssEditor.setValue('');
        jsEditor.setValue('');
        showToast('Code reset', 'info');
    }
    updatePreview();
}

// Forfeit
async function forfeit() {
    const confirmed = await showConfirm('Forfeit the match? This will end your participation.', 'Forfeit match');
    if (!confirmed) return;
    if (window.socket) {
        window.socket.emit('forfeit', {
            room_id: ROOM_ID,
            username: CURRENT_USERNAME
        });
    }
    window.location.href = '/dashboard';
}

function buildCompiledPreviewHtml() {
    if (!htmlEditor || !cssEditor || !jsEditor) return '';
    const html = htmlEditor.getValue();
    const css = cssEditor.getValue();
    const js = jsEditor.getValue();
    const guardScript = getPlayerInspectGuardScript();
    return `<!DOCTYPE html><html><head><style>${css}</style></head><body>${html}${guardScript}<script>${js}<\/script></body></html>`;
}

function broadcastCodePreview() {
    if (!IS_PLAYER_ROLE || !window.socket) return;
    window.socket.emit('code_preview', {
        room_id: ROOM_ID,
        username: CURRENT_USERNAME,
        compiled_html: buildCompiledPreviewHtml(),
        html_code: htmlEditor.getValue(),
        css_code: cssEditor.getValue(),
        js_code: jsEditor.getValue()
    });
}

function scheduleCodePreviewBroadcast(delay = 450) {
    if (!IS_PLAYER_ROLE) return;
    if (previewBroadcastTimer) clearTimeout(previewBroadcastTimer);
    previewBroadcastTimer = setTimeout(() => {
        previewBroadcastTimer = null;
        broadcastCodePreview();
    }, delay);
}

// Code preview for observers
function startCodePreview() {
    if (!IS_PLAYER_ROLE) return;
    broadcastCodePreview();
    setInterval(broadcastCodePreview, 5000);
}

function initAdminObserverWorkspace() {
    if (USER_ROLE !== 'admin') return;
    const editorPanel = getElement('editor-panel');
    const editorContainer = editorPanel?.querySelector('.editor-container');
    if (!editorPanel || !editorContainer || editorPanel.querySelector('.admin-observer-workspace')) return;

    editorPanel.querySelector('.editor-header-left span:first-of-type').textContent = 'LIVE PLAYER EDITORS';
    editorPanel.querySelector('.editor-tabs')?.remove();
    editorContainer.style.display = 'none';

    const workspace = document.createElement('div');
    workspace.className = 'admin-observer-workspace';
    workspace.innerHTML = ['player1', 'player2'].map((role) => {
        const label = role === 'player1'
            ? (arenaConfig.player1Username || 'Player 1')
            : (arenaConfig.player2Username || 'Player 2');
        return `
            <section class="admin-player-code" data-admin-player="${role}">
                <header><strong>${escapeHtml(label)}</strong><span>read-only live code</span></header>
                <div class="admin-code-columns">
                    <pre data-code-kind="html"><b>HTML</b><code></code></pre>
                    <pre data-code-kind="css"><b>CSS</b><code></code></pre>
                    <pre data-code-kind="js"><b>JS</b><code></code></pre>
                </div>
            </section>
        `;
    }).join('');
    editorContainer.insertAdjacentElement('afterend', workspace);
}

function updateAdminPlayerCode(username, code = {}) {
    if (USER_ROLE !== 'admin' || !username) return;
    const p1Name = arenaConfig.player1Username || getElement('p1-username-data')?.value;
    const p2Name = arenaConfig.player2Username || getElement('p2-username-data')?.value;
    const role = username === p1Name ? 'player1' : username === p2Name ? 'player2' : null;
    const section = role ? document.querySelector(`[data-admin-player="${role}"]`) : null;
    if (!section) return;
    section.querySelector('header strong').textContent = username;
    ['html', 'css', 'js'].forEach((kind) => {
        const codeEl = section.querySelector(`[data-code-kind="${kind}"] code`);
        if (codeEl) codeEl.textContent = code[`${kind}_code`] || '';
    });
}

window.updateAdminPlayerCode = updateAdminPlayerCode;

// Collapse editor
function initCollapseEditor() {
    const collapseBtn = getElement('collapse-editor-btn');
    const collapseBtnBottom = getElement('collapse-editor-btn-bottom');
    const sidebarBtn = getElement('toggle-sidebar-btn');
    const chatBtn = getElement('toggle-chat-btn');
    const chatBtnNav = getElement('toggle-chat-btn-nav');
    const closeChatBtn = getElement('close-chat-drawer');
    const arenaRoot = document.querySelector('.arena-root');
    const arenaMain = document.querySelector('.arena-main');
    const editorPanel = getElement('editor-panel');
    const sidebar = document.querySelector('.right-sidebar');
    
    let layoutSyncTimer = null;

    function refreshArenaSurfaces() {
        if (htmlEditor) htmlEditor.refresh();
        if (cssEditor) cssEditor.refresh();
        if (jsEditor) jsEditor.refresh();

        const outputFrame = getElement('output-frame');
        const targetFrame = getElement('target-frame');
        if (outputFrame) outputFrame.dispatchEvent(new Event('resize'));
        if (targetFrame) targetFrame.dispatchEvent(new Event('resize'));
        if (typeof scheduleLiveDiffCheck === 'function') scheduleLiveDiffCheck(180);
    }

    function syncArenaLayout() {
        if (!arenaMain) return;

        const compact = window.innerWidth <= 980;
        const drawer = false;
        arenaRoot?.classList.toggle('arena-compact', compact);
        arenaRoot?.classList.toggle('arena-drawer-sidebar', drawer);

        if (compact) {
            arenaMain.style.removeProperty('--editor-width');
            arenaMain.style.removeProperty('--sidebar-width');
        } else {
            const available = arenaMain.clientWidth || window.innerWidth;
            const maxEditor = Math.max(280, Math.min(520, available - 620));
            const maxSidebar = Math.max(240, Math.min(420, available - 700));
            const currentEditor = parseFloat(getComputedStyle(arenaMain).getPropertyValue('--editor-width')) || 380;
            const currentSidebar = parseFloat(getComputedStyle(arenaMain).getPropertyValue('--sidebar-width')) || 300;
            arenaMain.style.setProperty('--editor-width', `${Math.min(Math.max(currentEditor, 280), maxEditor)}px`);
            arenaMain.style.setProperty('--sidebar-width', `${Math.min(Math.max(currentSidebar, 240), maxSidebar)}px`);
        }

        window.clearTimeout(layoutSyncTimer);
        layoutSyncTimer = window.setTimeout(refreshArenaSurfaces, 260);
    }

    function queueArenaLayoutSync(delay = 0) {
        window.clearTimeout(layoutSyncTimer);
        layoutSyncTimer = window.setTimeout(syncArenaLayout, delay);
    }
    function syncCollapseLabels() {
        const editorCollapsed = arenaMain?.classList.contains('editor-collapsed');
        const sidebarCollapsed = arenaMain?.classList.contains('sidebar-collapsed');

        if (collapseBtn) {
            collapseBtn.innerHTML = editorCollapsed ? '<i class="fas fa-chevron-right"></i>' : '<i class="fas fa-chevron-left"></i>';
            collapseBtn.title = editorCollapsed ? 'Expand editor' : 'Collapse editor';
        }
        if (collapseBtnBottom) {
            collapseBtnBottom.innerHTML = editorCollapsed ? '<i class="fas fa-chevron-right"></i> Expand Editor' : '<i class="fas fa-chevron-left"></i> Collapse Editor';
        }
        if (sidebarBtn) {
            sidebarBtn.innerHTML = sidebarCollapsed ? '<i class="fas fa-chevron-left"></i> Show Sidebar' : '<i class="fas fa-chevron-right"></i> Hide Sidebar';
        }
        const chatOpen = arenaRoot?.classList.contains('chat-open');
        [chatBtn, chatBtnNav].forEach((btn) => {
            if (!btn) return;
            btn.classList.toggle('active', Boolean(chatOpen));
            btn.setAttribute('aria-expanded', chatOpen ? 'true' : 'false');
        });
    }

    function toggleEditor() {
        if (!arenaMain || !editorPanel) return;
        arenaMain.classList.toggle('editor-collapsed');
        editorPanel.classList.toggle('collapsed', arenaMain.classList.contains('editor-collapsed'));
        syncCollapseLabels();
        queueArenaLayoutSync();
    }

    function toggleSidebar() {
        if (!arenaMain || !sidebar) return;
        arenaMain.classList.toggle('sidebar-collapsed');
        sidebar.classList.toggle('collapsed', arenaMain.classList.contains('sidebar-collapsed'));
        if (!arenaMain.classList.contains('sidebar-collapsed')) {
            arenaRoot?.classList.add('chat-open');
        } else {
            arenaRoot?.classList.remove('chat-open');
        }
        syncCollapseLabels();
        queueArenaLayoutSync();
    }

    function toggleChat(forceOpen = null) {
        if (!arenaRoot || !sidebar) return;
        const shouldOpen = forceOpen === null ? !arenaRoot.classList.contains('chat-open') : Boolean(forceOpen);
        arenaRoot.classList.toggle('chat-open', shouldOpen);
        if (shouldOpen) {
            arenaMain?.classList.remove('sidebar-collapsed');
            sidebar.classList.remove('collapsed');
            window.activateArenaSidebarCard?.('chat');
            setTimeout(() => getElement('chat-input')?.focus(), 160);
        } else {
            arenaMain?.classList.add('sidebar-collapsed');
            sidebar.classList.add('collapsed');
        }
        syncCollapseLabels();
        queueArenaLayoutSync();
    }

    window.setArenaChatOpen = toggleChat;

    if (collapseBtn) collapseBtn.addEventListener('click', toggleEditor);
    if (collapseBtnBottom) collapseBtnBottom.addEventListener('click', toggleEditor);
    if (sidebarBtn) sidebarBtn.addEventListener('click', toggleSidebar);
    if (chatBtn) chatBtn.addEventListener('click', () => toggleChat());
    if (chatBtnNav) chatBtnNav.addEventListener('click', () => toggleChat());
    if (closeChatBtn) closeChatBtn.addEventListener('click', () => toggleChat(false));
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') toggleChat(false);
    });

    window.addEventListener('resize', () => queueArenaLayoutSync(120));
    initArenaResizers(arenaMain);
    if (USER_ROLE !== 'spectator') {
        arenaRoot?.classList.add('chat-open');
        arenaMain?.classList.remove('sidebar-collapsed');
        sidebar?.classList.remove('collapsed');
    }
    syncCollapseLabels();
    syncArenaLayout();
}

function initArenaResizers(arenaMain) {
    if (!arenaMain || window.innerWidth < 900 || arenaMain.dataset.resizersReady) return;
    arenaMain.dataset.resizersReady = 'true';

    const editorHandle = document.createElement('button');
    editorHandle.type = 'button';
    editorHandle.className = 'arena-resizer editor-resizer';
    editorHandle.setAttribute('aria-label', 'Resize editor');

    const sidebarHandle = document.createElement('button');
    sidebarHandle.type = 'button';
    sidebarHandle.className = 'arena-resizer sidebar-resizer';
    sidebarHandle.setAttribute('aria-label', 'Resize sidebar');

    arenaMain.append(editorHandle, sidebarHandle);

    function startResize(kind, event) {
        event.preventDefault();
        const startX = event.clientX;
        const styles = getComputedStyle(arenaMain);
        const startEditor = parseFloat(styles.getPropertyValue('--editor-width')) || 380;
        const startSidebar = parseFloat(styles.getPropertyValue('--sidebar-width')) || 300;

        function move(moveEvent) {
            const dx = moveEvent.clientX - startX;
            if (kind === 'editor') {
                const next = Math.max(280, Math.min(520, startEditor + dx));
                arenaMain.style.setProperty('--editor-width', `${next}px`);
            } else {
                const next = Math.max(240, Math.min(420, startSidebar - dx));
                arenaMain.style.setProperty('--sidebar-width', `${next}px`);
            }
            if (htmlEditor) htmlEditor.refresh();
            if (cssEditor) cssEditor.refresh();
            if (jsEditor) jsEditor.refresh();
        }

        function stop() {
            window.removeEventListener('pointermove', move);
            window.removeEventListener('pointerup', stop);
            document.body.classList.remove('is-resizing-arena');
        }

        document.body.classList.add('is-resizing-arena');
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', stop, { once: true });
    }

    editorHandle.addEventListener('pointerdown', (event) => startResize('editor', event));
    sidebarHandle.addEventListener('pointerdown', (event) => startResize('sidebar', event));
}

function initCenterPanelResizers() {
    const centerPanel = document.querySelector('.center-panel');
    if (!centerPanel || centerPanel.dataset.centerResizersReady) return;
    centerPanel.dataset.centerResizersReady = 'true';

    const savedX = Number(localStorage.getItem(`arena_${ROOM_ID}_center_split_x`) || 50);
    const savedY = Number(localStorage.getItem(`arena_${ROOM_ID}_center_split_y`) || 50);
    const clampPercent = (value) => Math.max(30, Math.min(70, Number(value) || 50));

    centerPanel.style.setProperty('--center-split-x', `${clampPercent(savedX)}%`);
    centerPanel.style.setProperty('--center-split-y', `${clampPercent(savedY)}%`);

    const xHandle = document.createElement('button');
    xHandle.type = 'button';
    xHandle.className = 'center-panel-splitter center-panel-splitter-x';
    xHandle.setAttribute('aria-label', 'Resize arena panels left and right');

    const yHandle = document.createElement('button');
    yHandle.type = 'button';
    yHandle.className = 'center-panel-splitter center-panel-splitter-y';
    yHandle.setAttribute('aria-label', 'Resize arena panels up and down');

    centerPanel.append(xHandle, yHandle);

    function refreshAfterResize() {
        if (typeof drawLiveDiff === 'function') scheduleLiveDiffCheck(80);
        const outputFrame = getElement('output-frame');
        const targetFrame = getElement('target-frame');
        outputFrame?.dispatchEvent(new Event('resize'));
        targetFrame?.dispatchEvent(new Event('resize'));
    }

    function startResize(axis, event) {
        event.preventDefault();
        const rect = centerPanel.getBoundingClientRect();
        document.body.classList.add('is-resizing-center');

        function move(moveEvent) {
            if (axis === 'x') {
                const next = clampPercent(((moveEvent.clientX - rect.left) / rect.width) * 100);
                centerPanel.style.setProperty('--center-split-x', `${next}%`);
                localStorage.setItem(`arena_${ROOM_ID}_center_split_x`, String(Math.round(next)));
            } else {
                const next = clampPercent(((moveEvent.clientY - rect.top) / rect.height) * 100);
                centerPanel.style.setProperty('--center-split-y', `${next}%`);
                localStorage.setItem(`arena_${ROOM_ID}_center_split_y`, String(Math.round(next)));
            }
            refreshAfterResize();
        }

        function stop() {
            window.removeEventListener('pointermove', move);
            window.removeEventListener('pointerup', stop);
            document.body.classList.remove('is-resizing-center');
            refreshAfterResize();
        }

        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', stop, { once: true });
    }

    xHandle.addEventListener('pointerdown', (event) => startResize('x', event));
    yHandle.addEventListener('pointerdown', (event) => startResize('y', event));
}

function initPanelCollapse() {
    function installCollapse(target, headerSelector, collapsedClass, bodySelector = null) {
        const header = target.querySelector(headerSelector);
        if (!header || header.querySelector('.panel-collapse-btn')) return;

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'panel-collapse-btn';
        btn.innerHTML = '<i class="fas fa-minus"></i>';
        btn.title = 'Collapse panel';
        header.appendChild(btn);

        function sync() {
            const collapsed = target.classList.contains(collapsedClass);
            btn.innerHTML = collapsed ? '<i class="fas fa-plus"></i>' : '<i class="fas fa-minus"></i>';
            btn.title = collapsed ? 'Expand panel' : 'Collapse panel';
            target.querySelectorAll(bodySelector || ':scope > :not(.panel-header):not(.sidebar-card-header)').forEach((el) => {
                el.setAttribute('aria-hidden', collapsed ? 'true' : 'false');
            });
        }

        btn.addEventListener('click', () => {
            target.classList.toggle(collapsedClass);
            sync();
            setTimeout(() => {
                if (htmlEditor) htmlEditor.refresh();
                if (cssEditor) cssEditor.refresh();
                if (jsEditor) jsEditor.refresh();
            }, 120);
        });
        sync();
    }

    document.querySelectorAll('.panel').forEach((panel) => {
        installCollapse(panel, '.panel-header', 'panel-collapsed');
    });

    document.querySelectorAll('.sidebar-card').forEach((card) => {
        installCollapse(card, ':scope > .sidebar-card-header', 'sidebar-card-collapsed');
    });

    const collapseAllBtn = getElement('collapse-all-panels-btn');
    const expandAllBtn = getElement('expand-all-panels-btn');
    const setAllCollapsed = (collapsed) => {
        document.querySelectorAll('.panel').forEach((panel) => {
            panel.classList.toggle('panel-collapsed', collapsed);
            panel.querySelectorAll(':scope > :not(.panel-header)').forEach((el) => {
                el.setAttribute('aria-hidden', collapsed ? 'true' : 'false');
            });
        });
        document.querySelectorAll('.panel > .panel-header .panel-collapse-btn').forEach((btn) => {
            btn.innerHTML = collapsed ? '<i class="fas fa-plus"></i>' : '<i class="fas fa-minus"></i>';
            btn.title = collapsed ? 'Expand panel' : 'Collapse panel';
        });
    };
    if (collapseAllBtn) collapseAllBtn.addEventListener('click', () => setAllCollapsed(true));
    if (expandAllBtn) expandAllBtn.addEventListener('click', () => setAllCollapsed(false));
}

function initSidebarTabs() {
    const sidebar = document.querySelector('.right-sidebar');
    if (!sidebar || sidebar.dataset.tabsReady) return;

    const cards = Array.from(sidebar.querySelectorAll(':scope > .sidebar-card'));
    if (!cards.length) return;

    sidebar.dataset.tabsReady = 'true';
    sidebar.classList.add('sidebar-tabs');

    const drawerHeader = sidebar.querySelector(':scope > .sidebar-drawer-header');
    const nav = document.createElement('div');
    nav.className = 'sidebar-tab-nav';
    nav.setAttribute('aria-label', 'Arena sidebar sections');

    const contentPane = document.createElement('div');
    contentPane.className = 'sidebar-tab-content';

    if (drawerHeader) {
        drawerHeader.insertAdjacentElement('afterend', nav);
    } else {
        sidebar.prepend(nav);
    }
    nav.insertAdjacentElement('afterend', contentPane);
    cards.forEach((card) => contentPane.appendChild(card));

    function activateCard(activeCard) {
        cards.forEach((card) => {
            const isActive = card === activeCard;
            card.classList.toggle('sidebar-card-active', isActive);
            card.setAttribute('aria-hidden', isActive ? 'false' : 'true');
            card.hidden = !isActive;
            card.style.display = isActive ? '' : 'none';
            const button = nav.querySelector(`[data-sidebar-target="${card.id}"]`);
            if (button) button.setAttribute('aria-expanded', isActive ? 'true' : 'false');
        });
    }

    window.activateArenaSidebarCard = (target = 'chat') => {
        const normalized = String(target).toLowerCase();
        const match = cards.find((card) => {
            const headerText = card.querySelector(':scope > .sidebar-card-header')?.textContent?.toLowerCase() || '';
            return card.classList.contains(`${normalized}-card`)
                || card.id === normalized
                || headerText.includes(normalized);
        });
        activateCard(match || sidebar.querySelector('.chat-card') || cards[0]);
    };

    cards.forEach((card, index) => {
        const header = card.querySelector(':scope > .sidebar-card-header');
        if (!header) return;
        if (!card.id) card.id = `arena-sidebar-card-${index + 1}`;

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'sidebar-tab-button';
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-controls', card.id);
        button.dataset.sidebarTarget = card.id;

        const icon = header.querySelector('i')?.cloneNode(true);
        const title = header.textContent.replace(/\s+/g, ' ').replace('View Full â†’', '').trim() || `Section ${index + 1}`;
        if (icon) button.appendChild(icon);
        const label = document.createElement('span');
        label.textContent = title;
        button.appendChild(label);
        nav.appendChild(button);

        button.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            activateCard(card);
        });
    });

    window.activateArenaSidebarCard('chat');
}

function initSurfaceZoom() {
    const zoomState = { output: 1, target: 1 };
    const minZoom = 0.2;
    const maxZoom = 3;
    const step = 0.25;

    function getSurface(name) {
        return document.querySelector(`[data-zoom-surface="${name}"]`);
    }

    function getPrimaryContent(name) {
        const surface = getSurface(name);
        if (!surface) return null;
        return Array.from(surface.querySelectorAll('.surface-zoom-content')).find((el) => {
            const styles = getComputedStyle(el);
            return styles.display !== 'none';
        }) || surface.querySelector('.surface-zoom-content');
    }

    function measureContent(name) {
        const surface = getSurface(name);
        const content = getPrimaryContent(name);
        if (!surface || !content) return null;

        if (content.tagName === 'IMG') {
            return {
                width: content.naturalWidth || surface.clientWidth,
                height: content.naturalHeight || surface.clientHeight
            };
        }

        if (content.tagName === 'IFRAME') {
            try {
                const doc = content.contentDocument || content.contentWindow?.document;
                const body = doc?.body;
                const html = doc?.documentElement;
                if (body || html) {
                    return {
                        width: Math.max(body?.scrollWidth || 0, html?.scrollWidth || 0, body?.offsetWidth || 0, html?.offsetWidth || 0, surface.clientWidth),
                        height: Math.max(body?.scrollHeight || 0, html?.scrollHeight || 0, body?.offsetHeight || 0, html?.offsetHeight || 0, surface.clientHeight)
                    };
                }
            } catch (error) {}
        }

        return {
            width: content.scrollWidth || content.offsetWidth || surface.clientWidth,
            height: content.scrollHeight || content.offsetHeight || surface.clientHeight
        };
    }

    function setBaseSize(name, width = null, height = null) {
        const surface = getSurface(name);
        if (!surface) return;
        const nextWidth = Math.max(1, Math.ceil(width || surface.clientWidth || 1));
        const nextHeight = Math.max(1, Math.ceil(height || surface.clientHeight || 1));
        surface.style.setProperty('--surface-base-width', `${nextWidth}px`);
        surface.style.setProperty('--surface-base-height', `${nextHeight}px`);
    }

    function setZoom(name, value, { fit = false } = {}) {
        const surface = getSurface(name);
        if (!surface) return;
        const next = Math.max(minZoom, Math.min(maxZoom, value));
        zoomState[name] = next;
        surface.style.setProperty('--surface-zoom', next.toFixed(3));
        surface.classList.toggle('surface-fit-mode', fit);
        document.querySelectorAll(`[data-zoom-value="${name}"]`).forEach((label) => {
            label.textContent = fit ? `Fit ${Math.round(next * 100)}%` : `${Math.round(next * 100)}%`;
        });
    }

    function fitSurface(name) {
        const surface = getSurface(name);
        if (!surface) return;
        const measured = measureContent(name);
        if (!measured) return;
        setBaseSize(name, measured.width, measured.height);
        const fitScale = Math.min(
            surface.clientWidth / Math.max(1, measured.width),
            surface.clientHeight / Math.max(1, measured.height),
            1
        );
        setZoom(name, fitScale, { fit: true });
    }

    function resetSurface(name) {
        const surface = getSurface(name);
        if (!surface) return;
        setBaseSize(name, surface.clientWidth, surface.clientHeight);
        setZoom(name, 1);
    }

    ['output-frame', 'target-frame'].forEach((id) => {
        const frame = getElement(id);
        if (!frame) return;
        const name = id === 'output-frame' ? 'output' : 'target';
        frame.addEventListener('load', () => setTimeout(() => fitSurface(name), 80));
    });

    const targetImage = getElement('target-image');
    if (targetImage) {
        targetImage.addEventListener('load', () => setTimeout(() => fitSurface('target'), 80));
    }

    document.querySelectorAll('[data-zoom-panel]').forEach((group) => {
        const name = group.dataset.zoomPanel;
        group.querySelectorAll('[data-zoom-action]').forEach((button) => {
            button.addEventListener('click', (event) => {
                event.stopPropagation();
                const action = button.dataset.zoomAction;
                if (action === 'in') setZoom(name, zoomState[name] + step);
                if (action === 'out') setZoom(name, zoomState[name] - step);
                if (action === 'fit') fitSurface(name);
                if (action === 'reset') resetSurface(name);
            });
        });
        resetSurface(name);
        setTimeout(() => fitSurface(name), 180);
    });

    window.addEventListener('resize', debounce(() => {
        Object.keys(zoomState).forEach((name) => fitSurface(name));
    }, 160));
}
function initPanelSizing() {
    const centerPanel = document.querySelector('.center-panel');
    if (!centerPanel) return;

    const buttons = document.querySelectorAll('.panel-size-btn[data-panel-size]');
    const cameraPanel = centerPanel.querySelector('.cam-panel');
    const cameraCompactBtn = getElement('toggle-camera-compact');
    const focusClasses = ['expand-output', 'expand-target', 'expand-diff'];

    function refreshVisibleSurfaces() {
        setTimeout(() => {
            const outputFrame = getElement('output-frame');
            const targetFrame = getElement('target-frame');
            if (outputFrame) outputFrame.dispatchEvent(new Event('resize'));
            if (targetFrame) targetFrame.dispatchEvent(new Event('resize'));
            if (typeof drawLiveDiff === 'function') scheduleLiveDiffCheck(150);
        }, 180);
    }

    function syncCameraButton() {
        if (!cameraCompactBtn) return;
        const compact = centerPanel.classList.contains('camera-compact') || centerPanel.classList.contains('has-expanded-panel');
        cameraCompactBtn.classList.toggle('active', compact);
        cameraCompactBtn.setAttribute('aria-pressed', compact ? 'true' : 'false');
        cameraCompactBtn.title = compact ? 'Restore camera' : 'Minimize camera';
        cameraCompactBtn.setAttribute('aria-label', cameraCompactBtn.title);
    }

    function clearFocusClasses() {
        focusClasses.forEach((className) => centerPanel.classList.remove(className));
    }

    function setExpanded(panel, button) {
        const isExpanded = panel.classList.contains('panel-expanded');
        centerPanel.querySelectorAll('.panel-expanded').forEach((expandedPanel) => {
            expandedPanel.classList.remove('panel-expanded');
        });
        buttons.forEach((btn) => {
            btn.classList.remove('active');
            btn.innerHTML = '<i class="fas fa-up-right-and-down-left-from-center"></i>';
            btn.title = `Focus ${btn.dataset.panelSize} view`;
        });
        clearFocusClasses();

        if (!isExpanded) {
            panel.classList.remove('panel-collapsed');
            panel.classList.add('panel-expanded');
            centerPanel.classList.add('has-expanded-panel');
            centerPanel.classList.remove('camera-compact');
            centerPanel.classList.add(`expand-${button.dataset.panelSize}`);
            button.classList.add('active');
            button.innerHTML = '<i class="fas fa-down-left-and-up-right-to-center"></i>';
            button.title = 'Restore arena grid';
        } else {
            centerPanel.classList.remove('has-expanded-panel');
        }

        if (!centerPanel.querySelector('.panel-expanded')) {
            centerPanel.classList.remove('has-expanded-panel');
            clearFocusClasses();
        }
        syncCameraButton();
        refreshVisibleSurfaces();
    }

    buttons.forEach((button) => {
        const panel = button.closest('.panel');
        if (!panel) return;
        button.addEventListener('click', (event) => {
            event.stopPropagation();
            setExpanded(panel, button);
        });
    });

    if (cameraCompactBtn) {
        cameraCompactBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            centerPanel.querySelectorAll('.panel-expanded').forEach((expandedPanel) => {
                expandedPanel.classList.remove('panel-expanded');
            });
            buttons.forEach((btn) => {
                btn.classList.remove('active');
                btn.innerHTML = '<i class="fas fa-up-right-and-down-left-from-center"></i>';
                btn.title = `Focus ${btn.dataset.panelSize} view`;
            });
            centerPanel.classList.remove('has-expanded-panel');
            clearFocusClasses();
            centerPanel.classList.toggle('camera-compact');
            syncCameraButton();
            refreshVisibleSurfaces();
        });
    }

    if (cameraPanel) {
        cameraPanel.addEventListener('click', (event) => {
            if (!centerPanel.classList.contains('camera-compact') && !centerPanel.classList.contains('has-expanded-panel')) return;
            if (event.target.closest('button')) return;
            centerPanel.classList.remove('camera-compact', 'has-expanded-panel');
            clearFocusClasses();
            centerPanel.querySelectorAll('.panel-expanded').forEach((expandedPanel) => {
                expandedPanel.classList.remove('panel-expanded');
            });
            buttons.forEach((btn) => {
                btn.classList.remove('active');
                btn.innerHTML = '<i class="fas fa-up-right-and-down-left-from-center"></i>';
                btn.title = `Focus ${btn.dataset.panelSize} view`;
            });
            syncCameraButton();
            refreshVisibleSurfaces();
        });
    }

    syncCameraButton();
}

function initSpectatorMode() {
    if (USER_ROLE !== 'spectator') return;
    document.querySelector('.arena-root')?.classList.add('spectator-mode', 'chat-open');
    document.querySelector('.arena-main')?.classList.remove('editor-collapsed');
    getElement('editor-panel')?.classList.remove('collapsed');
    ['toggle-chat-btn', 'toggle-chat-btn-nav'].forEach((id) => {
        const el = getElement(id);
        if (el) {
            el.classList.add('active');
            el.setAttribute('aria-expanded', 'true');
        }
    });
    ['submit-btn', 'reset-code-btn', 'forfeit-btn', 'collapse-editor-btn-bottom', 'toggle-sidebar-btn'].forEach((id) => {
        const el = getElement(id);
        if (el) el.style.display = 'none';
    });
}

function initLiveScoringObservers() {
    if (!IS_PLAYER_ROLE) return;
    const outputFrame = getElement('output-frame');
    const targetFrame = getElement('target-frame');
    [outputFrame, targetFrame].forEach((frame) => {
        if (!frame) return;
        frame.addEventListener('load', () => scheduleLiveDiffCheck(120));
    });
    if (window.ResizeObserver) {
        const observer = new ResizeObserver(() => scheduleLiveDiffCheck(180));
        ['output', 'target', 'diff'].forEach((name) => {
            const node = document.querySelector(`[data-zoom-surface="${name}"]`) || document.querySelector(`.${name}-panel`);
            if (node) observer.observe(node);
        });
    }
}

function showEditorShortcutsMenu() {
    const overlay = document.createElement('div');
    overlay.className = 'shortcuts-overlay';
    overlay.innerHTML = `
        <div class="shortcuts-dialog">
            <header>
                <h3><i class="fas fa-keyboard"></i> Editor Shortcuts</h3>
                <button type="button" aria-label="Close shortcuts"><i class="fas fa-times"></i></button>
            </header>
            <div class="shortcuts-grid">
                ${EDITOR_SHORTCUT_GROUPS.map(([title, rows]) => `
                    <section>
                        <h4>${escapeHtml(title)}</h4>
                        ${rows.map(([keys, detail]) => `
                            <div class="shortcut-row">
                                <kbd>${escapeHtml(keys)}</kbd>
                                <span>${escapeHtml(detail)}</span>
                            </div>
                        `).join('')}
                    </section>
                `).join('')}
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector('button')?.addEventListener('click', close);
    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) close();
    });
    window.addEventListener('keydown', function onKey(event) {
        if (event.key === 'Escape') {
            close();
            window.removeEventListener('keydown', onKey);
        }
    });
}

function renderAdminIncident(data = {}) {
    if (USER_ROLE !== 'admin') return;
    const list = getElement('admin-incident-list');
    if (!list) return;
    list.querySelector('.spectator-placeholder')?.remove();
    const username = data.username || data.player_name || 'Player';
    const blocked = data.blocked !== false;
    const source = data.source || 'arena';
    const defaultWarning = `${username}, warning: right-clicking, Inspect, View Source, or developer-tool shortcuts are prohibited. A repeat attempt can lead to disqualification.`;
    const card = document.createElement('div');
    card.className = 'admin-incident-item';
    card.innerHTML = `
        <div>
            <strong>${escapeHtml(username)}</strong>
            <span>${escapeHtml(data.message || `Player ${username} tried to right-click.`)}</span>
            <small>Source: ${escapeHtml(source)} · Blocked: ${blocked ? 'yes' : 'no'} · Worked: ${data.worked ? 'yes' : 'no'}</small>
        </div>
        <div class="admin-incident-actions">
            <button type="button" data-incident-action="warn"><i class="fas fa-triangle-exclamation"></i> Warn</button>
            <button type="button" data-incident-action="dq"><i class="fas fa-ban"></i> Disqualify</button>
        </div>
    `;
    list.prepend(card);
    card.querySelector('[data-incident-action="warn"]')?.addEventListener('click', async () => {
        const message = await showPrompt({
            title: 'Warn player',
            message: `Send a warning to ${username}.`,
            label: 'Warning message',
            value: defaultWarning,
            multiline: true,
            required: true,
            confirmText: 'Send Warning'
        });
        if (!message) return;
        window.socket?.emit('admin_warn_player', {
            room_id: ROOM_ID,
            username,
            message
        });
    });
    card.querySelector('[data-incident-action="dq"]')?.addEventListener('click', async () => {
        const reason = await showPrompt({
            title: 'Disqualify player',
            message: `${username} will be removed from active play and receive a zero/forfeit score.`,
            label: 'Reason',
            value: `Disqualified: ${username} tried to right-click during the match.`,
            multiline: true,
            required: true,
            confirmText: 'Disqualify'
        });
        if (!reason) return;
        window.socket?.emit('admin_disqualify_player', {
            room_id: ROOM_ID,
            username,
            reason
        });
    });
}

function initEditorShortcutsMenu() {
    getElement('editor-shortcuts-btn')?.addEventListener('click', showEditorShortcutsMenu);
}

function initAdminIncidentControls() {
    if (USER_ROLE !== 'admin' || !window.socket) return;
    window.socket.on('admin_right_click_attempt', (data) => {
        renderAdminIncident(data);
        showToast(data?.message || 'Player right-click attempt reported. It was blocked.', 'warning');
    });
    window.socket.on('admin_right_click_action_result', (data) => {
        showToast(data?.message || 'Admin action completed.', data?.success === false ? 'error' : 'success');
    });
}

// Admin controls
function initAdminControls() {
    if (USER_ROLE !== 'admin') return;
    
    const pauseBtn = getElement('admin-pause');
    const resumeBtn = getElement('admin-resume');
    const addTimeBtn = getElement('admin-addtime');
    const endBtn = getElement('admin-end');
    
    if (pauseBtn) {
        pauseBtn.addEventListener('click', () => {
            window.socket.emit('pause_challenge', { room_id: ROOM_ID });
        });
    }
    
    if (resumeBtn) {
        resumeBtn.addEventListener('click', () => {
            window.socket.emit('resume_challenge', { room_id: ROOM_ID });
        });
    }
    
    if (addTimeBtn) {
        addTimeBtn.addEventListener('click', () => {
            window.socket.emit('add_time', { room_id: ROOM_ID, seconds: 30 });
        });
    }
    
    if (endBtn) {
        endBtn.addEventListener('click', async () => {
            const confirmed = await showConfirm('End this challenge?', 'End challenge');
            if (confirmed) {
                window.socket.emit('end_challenge', { room_id: ROOM_ID });
            }
        });
    }
}

// Initialize all arena features
document.addEventListener('DOMContentLoaded', () => {
    initArenaInspectGuards();
    initEditors();
    initTarget();
    initDiffToggle();
    setupCamera();
    initMediaSettings();
    initCollapseEditor();
    initPanelCollapse();
    initSidebarTabs();
    initCenterPanelResizers();
    initPanelSizing();
    initSurfaceZoom();
    initLiveScoringObservers();
    initSpectatorMode();
    initAdminObserverWorkspace();
    initAdminControls();
    initAdminIncidentControls();
    initEditorShortcutsMenu();
    initRefreshGuard();
    applyInitialScoreState();
    startCodePreview();
    
    // Tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            switchTab(btn.dataset.tab);
        });
    });
    
    // Submit button
    const submitBtn = getElement('submit-btn');
    if (submitBtn) {
        submitBtn.addEventListener('click', runDiffCheck);
    }
    
    // Reset button
    const resetBtn = getElement('reset-code-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', resetCode);
    }
    
    // Forfeit button
    const forfeitBtn = getElement('forfeit-btn');
    if (forfeitBtn) {
        forfeitBtn.addEventListener('click', forfeit);
    }
    
    // Refresh output
    const refreshBtn = getElement('refresh-output');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', updatePreview);
    }
    
    // Initial preview
    updatePreview();
});


// Add this function to arena.js - Poll for challenge status every 2 seconds
let statusPollingInterval = null;

function startStatusPolling() {
    const roomId = document.getElementById('room-id')?.value || window.ARENA_CONFIG?.roomId;
    if (!roomId) return;
    
    console.log('ðŸ”„ Starting status polling for room', roomId);
    
    if (statusPollingInterval) {
        clearInterval(statusPollingInterval);
    }
    
    statusPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/challenge-status/${roomId}`);
            const data = await response.json();
            
            if (data.status === 'running') {
                console.log('ðŸ Polling detected challenge started!');
                setArenaMatchRunning(true);
                
                // Stop polling once started
                if (statusPollingInterval) {
                    clearInterval(statusPollingInterval);
                    statusPollingInterval = null;
                }
                
                // Hide the overlay
                const overlay = document.getElementById('editor-overlay');
                if (overlay) overlay.classList.add('hidden');
                
                // Update room status
                const statusPill = document.getElementById('room-status');
                if (statusPill) {
                    statusPill.textContent = 'LIVE';
                    statusPill.style.background = 'rgba(0,255,136,0.2)';
                    statusPill.style.color = 'var(--success)';
                }
                
                // Enable editors only for active players.
                const userRole = document.getElementById('user-role')?.value || window.ARENA_CONFIG?.userRole;
                const isPlayer = userRole === 'player1' || userRole === 'player2';
                if (isPlayer) {
                    if (window.cssEditor) window.cssEditor.setOption('readOnly', false);
                    if (window.jsEditor) window.jsEditor.setOption('readOnly', false);
                    
                    const challengeType = document.getElementById('challenge-type')?.value || window.ARENA_CONFIG?.challengeType;
                    const htmlLocked = document.getElementById('html-locked')?.value === 'true' || window.ARENA_CONFIG?.htmlLocked === true;
                    if (!(challengeType === 'html' && htmlLocked)) {
                        if (window.htmlEditor) window.htmlEditor.setOption('readOnly', false);
                    }
                }
                
                // Enable submit button
                const submitBtn = document.getElementById('submit-btn');
                if (submitBtn) submitBtn.disabled = !isPlayer;
                
                showToast(`Challenge started! ${data.time_limit}s on the clock!`, 'success');
                
                // Also try to emit a socket event to confirm
        if (window.socket) {
            window.socket.emit('check_challenge_status', { room_id: parseInt(roomId) });
        }
            }
        } catch (err) {
            console.error('Status poll error:', err);
        }
    }, 2000);
}

// Start polling when page loads
document.addEventListener('DOMContentLoaded', () => {
    console.log('ðŸ“„ DOM loaded, starting status polling');
    setArenaMatchRunning(getElement('room-status')?.textContent?.trim().toUpperCase() === 'RUNNING');
    startStatusPolling();
});


// Expose functions globally
window.runDiffCheck = runDiffCheck;
window.setArenaMatchRunning = setArenaMatchRunning;
window.htmlEditor = htmlEditor;
window.cssEditor = cssEditor;
window.jsEditor = jsEditor;
window.switchTab = switchTab;





