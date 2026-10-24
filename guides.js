// Setup guides as pages in the app (#/guides and #/guides/<name>), drawn from the same docs/*.md files the repo keeps.
// A small Markdown reader for what those files use: headings, numbered steps with sub-points, bullets, code blocks,
// `code`, **bold**, [links](...) and bare https:// links. Everything is escaped first; links are http(s) or another guide only.
(function () {
  const C = window.C, esc = C.esc, ic = C.ic;
  const GUIDES = {
    google: { file: "GOOGLE-SETUP.md", title: "Connect Google Calendar", icon: "calendar", blurb: "Your own Google sign-in, so Overture can read your calls. About ten minutes." },
    hubspot: { file: "HUBSPOT-SETUP.md", title: "Connect HubSpot", icon: "building", blurb: "Companies, deals, contacts and notes. Writes only when you press Save to HubSpot." },
    gong: { file: "GONG-SETUP.md", title: "Connect Gong", icon: "trend", blurb: "The last call's summary, key points and trackers." },
    meetily: { file: "MEETILY-SETUP.md", title: "Live transcript with Meetily", icon: "note", blurb: "Free and on this PC: Overture reads along while a call runs." },
    granola: { file: "GRANOLA-SETUP.md", title: "After the call with Granola", icon: "note", blurb: "Overture reads Granola's note and transcript when the call ends." },
    extension: { file: "CHROME-EXTENSION.md", title: "Overture beside Google Meet and Zoom", icon: "panel", blurb: "The Chrome side panel: load it once, then it opens next to your call." },
    "in-call": { file: "IN-CALL.md", title: "Install as a Meet add-on or Zoom App", icon: "video", blurb: "For developers: publish the in-call panel inside Google Meet and Zoom (HTTPS hosting, Marketplace)." },
  };
  const FILE_TO_NAME = Object.fromEntries(Object.entries(GUIDES).map(([k, g]) => [g.file, k]));
  const cache = {};

  // Inline text: escape, then code spans, bold, links and bare links. Code spans are kept apart so nothing inside them changes.
  function inline(raw) {
    const codes = [];
    let s = esc(raw).replace(/`([^`]+)`/g, (m, c) => "\u0000" + (codes.push(c) - 1) + "\u0000");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, text, href) => link(text, href));
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:])/g, (m, pre, href) => pre + link(href, href));
    return s.replace(/\u0000(\d+)\u0000/g, (m, i) => '<code class="gd-code">' + codes[+i] + "</code>");
  }
  function link(text, href) {
    const plain = href.replace(/&amp;/g, "&");
    const md = plain.match(/(?:^|\/)([A-Z-]+\.md)$/);
    if (md && FILE_TO_NAME[md[1]]) return '<a href="#/guides/' + FILE_TO_NAME[md[1]] + '">' + text + "</a>";
    if (!/^https?:\/\//i.test(plain)) return text;
    return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + text + ic("link", "ext") + '<span class="sr-only"> (opens in a new tab)</span></a>';
  }

  // Blocks: a fenced code block, a heading, a list (numbered or not, with indented sub-points and wrapped lines), or a paragraph.
  function render(md) {
    const lines = md.replace(/\r/g, "").split("\n");
    const out = [], toc = [];
    let title = "", i = 0, n = 0;
    const listAt = (l) => l.match(/^(\s*)(\d+\.|[-*])\s+(.*)$/);
    while (i < lines.length) {
      const l = lines[i];
      if (!l.trim()) { i++; continue; }
      const fence = l.match(/^(\s*)```\s*([\w-]*)/);
      if (fence) { // also indented under a step; its language names the box (json, text), plain or shell is a command
        const body = [], pad = fence[1].length;
        for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) body.push(lines[i].slice(Math.min(pad, lines[i].search(/\S|$/))));
        i++;
        const lang = fence[2].toLowerCase(), label = { json: "JSON", text: "Text", txt: "Text", "": "Command", bash: "Command", sh: "Command", powershell: "Command" }[lang] || lang.toUpperCase();
        out.push('<div class="gd-pre"><div class="gd-pre-bar"><span>' + esc(label) + '</span><span class="sr-only" role="status" data-copy-status></span>'
          + '<button type="button" class="gd-copy" data-copy-code aria-label="' + esc("Copy " + label.toLowerCase()) + '">Copy</button></div><pre><code>' + esc(body.join("\n")) + "</code></pre></div>");
        continue;
      }
      const h = l.match(/^(#{1,3})\s+(.*)$/);
      if (h) {
        if (h[1].length === 1 && !title) title = h[2];
        else {
          const id = "gd-" + (++n);
          if (h[1].length === 2) toc.push({ id, text: h[2] });
          out.push("<h" + (h[1].length === 2 ? 2 : 3) + ' class="gd-h" id="' + id + '" tabindex="-1">' + inline(h[2]) + "</h" + (h[1].length === 2 ? 2 : 3) + ">");
        }
        i++;
        continue;
      }
      if (listAt(l) && !listAt(l)[1]) {
        const ordered = /\d/.test(listAt(l)[2]);
        const items = [];
        while (i < lines.length && lines[i].trim() && !/^\s*```/.test(lines[i])) { // a code block ends the list; numbering resumes after it
          const m = listAt(lines[i]);
          if (m && !m[1]) { items.push({ text: m[3], subs: [], num: parseInt(m[2], 10) || items.length + 1 }); } // keep the guide's own number
          else if (m && items.length) { items[items.length - 1].subs.push(m[3]); }
          else if (items.length) { // a wrapped line belongs to the last point or sub-point
            const it = items[items.length - 1];
            if (it.subs.length) it.subs[it.subs.length - 1] += " " + lines[i].trim(); else it.text += " " + lines[i].trim();
          }
          i++;
          if (i < lines.length && listAt(lines[i]) && !listAt(lines[i])[1] && /\d/.test(listAt(lines[i])[2]) !== ordered) break;
        }
        const tag = ordered ? "ol" : "ul";
        out.push("<" + tag + ' class="' + (ordered ? "gd-steps" : "gd-list") + '" role="list"' + (ordered && items[0].num > 1 ? ' start="' + items[0].num + '"' : "") + ">" + items.map((it) => "<li>"
          + (ordered ? '<span class="gd-num" aria-hidden="true">' + it.num + "</span>" : "") + '<div class="gd-li"><p>' + inline(it.text) + "</p>"
          + (it.subs.length ? '<ul class="gd-sub" role="list">' + it.subs.map((s) => "<li>" + inline(s) + "</li>").join("") + "</ul>" : "") + "</div></li>").join("") + "</" + tag + ">");
        continue;
      }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^\s*```/.test(lines[i]) && !/^#{1,3}\s/.test(lines[i]) && !(listAt(lines[i]) && !listAt(lines[i])[1])) para.push(lines[i++].trim());
      const text = para.join(" ");
      // A short line with no full stop right before a list ("Notes") reads as a small heading.
      if (para.length === 1 && text.length < 40 && !/[.:!?]$/.test(text) && i < lines.length && listAt(lines[i] || "")) out.push('<h3 class="gd-h">' + inline(text) + "</h3>");
      else out.push('<p class="gd-p">' + inline(text) + "</p>");
    }
    return { title, toc, html: out.join("") };
  }

  function crumbs(here) {
    return '<div class="topbar"><div class="topbar-inner"><nav class="co-crumbs" aria-label="Breadcrumb"><a href="#/settings">Settings</a><span class="co-crumb-sep" aria-hidden="true">/</span>'
      + (here ? '<a href="#/guides">Setup guides</a><span class="co-crumb-sep" aria-hidden="true">/</span><span class="co-crumb-here" aria-current="page">' + esc(here) + "</span>"
        : '<span class="co-crumb-here" aria-current="page">Setup guides</span>') + "</nav></div></div>";
  }

  function indexHtml() {
    return crumbs("") + '<div class="gd-page"><header class="gd-head"><h1 class="page-title" tabindex="-1">Setup guides</h1>'
      + '<p class="gd-lead">Step-by-step help for connecting Overture to your calendar, your sales tools and your calls.</p></header>'
      + '<ul class="gd-cards" role="list">' + Object.entries(GUIDES).map(([k, g]) => '<li><a class="gd-card" href="#/guides/' + k + '"><span class="gd-card-ic" aria-hidden="true">' + ic(g.icon)
        + '</span><span class="gd-card-t"><strong>' + esc(g.title) + "</strong><span>" + esc(g.blurb) + "</span></span>" + ic("chevron", "gd-chev") + "</a></li>").join("") + "</ul></div>";
  }

  // Draws #/guides or #/guides/<name> into el. Returns the page title.
  function show(name, el) {
    if (!name || !GUIDES[name]) { el.innerHTML = indexHtml(); return "Setup guides"; }
    const g = GUIDES[name];
    const paint = (md) => {
      const r = render(md);
      const others = Object.entries(GUIDES).filter(([k]) => k !== name);
      el.innerHTML = crumbs(g.title) + '<div class="gd-page"><div class="gd-grid"><article class="gd-doc"><header class="gd-head"><span class="gd-head-ic" aria-hidden="true">' + ic(g.icon) + "</span>"
        + '<h1 class="page-title" tabindex="-1">' + inline(r.title || g.title) + "</h1></header>" + r.html + "</article>"
        + '<aside class="gd-side">' + (r.toc.length > 1 ? '<nav class="gd-toc" aria-label="On this page"><p class="gd-side-h">On this page</p><ul role="list">'
          + r.toc.map((t) => '<li><a href="#' + t.id + '" data-gd-jump="' + t.id + '">' + inline(t.text) + "</a></li>").join("") + "</ul></nav>" : "")
        + '<nav class="gd-more" aria-label="Other guides"><p class="gd-side-h">Other guides</p><ul role="list">'
        + others.map(([k, o]) => '<li><a href="#/guides/' + k + '">' + esc(o.title) + "</a></li>").join("") + "</ul></nav></aside></div></div>";
    };
    if (cache[name]) { paint(cache[name]); return g.title; }
    el.innerHTML = crumbs(g.title) + '<div class="gd-page"><p class="gd-p" role="status">Loading the guide…</p></div>';
    const still = () => { const p = location.hash.slice(2).split("/"); return p[0] === "guides" && (p[1] || "") === name; }; // still on "#/guides/<name>[/]"
    fetch("docs/" + g.file).then((r) => (r.ok ? r.text() : Promise.reject(new Error("not sent")))).then((md) => {
      cache[name] = md;
      if (!still()) return;
      paint(md);
      // The page's heading arrived after the route tried to focus it: focus it now, unless you've moved focus yourself.
      if (document.activeElement === document.body || !document.activeElement) { const h1 = el.querySelector("h1"); if (h1) h1.focus({ preventScroll: true }); }
    }, () => {
      if (still()) el.innerHTML = crumbs(g.title) + '<div class="gd-page"><p class="gd-p" role="alert">Overture\'s server didn\'t send this guide. Is server.py running?</p></div>';
    });
    return g.title;
  }

  // Copy buttons on code blocks, and "On this page" links that scroll instead of changing the route.
  document.addEventListener("click", (e) => {
    const cp = e.target.closest("[data-copy-code]");
    if (cp) {
      const box = cp.closest(".gd-pre"), code = box.querySelector("code"), status = box.querySelector("[data-copy-status]");
      (navigator.clipboard ? navigator.clipboard.writeText(code.textContent) : Promise.reject(new Error("no clipboard"))).then(() => {
        cp.textContent = "Copied"; status.textContent = "Copied to the clipboard.";
        setTimeout(() => { cp.textContent = "Copy"; status.textContent = ""; }, 1500);
      }, () => { // no clipboard access: select the text so Ctrl+C copies it
        getSelection().selectAllChildren(code);
        status.textContent = "Selected. Press Ctrl+C to copy.";
      });
      return;
    }
    const j = e.target.closest("[data-gd-jump]");
    if (j) {
      e.preventDefault();
      const t = document.getElementById(j.dataset.gdJump);
      if (t) { t.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); t.focus({ preventScroll: true }); }
    }
  });

  window.MoabGuides = { show, GUIDES, href: (name) => "#/guides/" + name };
})();
