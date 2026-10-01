(() => {
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const initialURL = new URL(location.href);
  const initialEntry = history.state?.siteNavigation;
  const visitType = performance.getEntriesByType("navigation")[0]?.type;
  const initialScroll = ["reload", "back_forward"].includes(visitType) ? initialEntry?.scroll : null;
  const storage = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* Storage is optional. */ } },
  };
  const animations = new Set();
  const positions = new Map();
  let controller;
  let navigation = 0;
  let renderedURL = new URL(location.href);
  let currentKey;
  let tocLinks = [];
  let pageSections = [];
  let scrollFrame = 0;
  let scrollSaveTimer = 0;
  let lastScrollSave = -Infinity;
  let selectReadingMode;

  const entryKey = () => `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const stateWith = (key, scroll) => ({ ...history.state, siteNavigation: { key, scroll } });
  const scrollPosition = () => ({ x: scrollX, y: scrollY });
  const samePage = (a, b) => a.pathname === b.pathname && a.search === b.search;
  const hashTarget = (hash) => {
    if (!hash || hash === "#") return null;
    try { return document.getElementById(decodeURIComponent(hash.slice(1))); } catch { return null; }
  };

  function saveScroll() {
    clearTimeout(scrollSaveTimer);
    scrollSaveTimer = 0;
    const scroll = scrollPosition();
    positions.set(currentKey, scroll);
    if (history.state?.siteNavigation?.key === currentKey) {
      const saved = history.state.siteNavigation.scroll;
      if (saved?.x !== scroll.x || saved?.y !== scroll.y) {
        history.replaceState(stateWith(currentKey, scroll), "");
        lastScrollSave = performance.now();
      }
    }
  }

  function persistScroll() {
    positions.set(currentKey, scrollPosition());
    if (scrollSaveTimer) return;
    const remaining = 500 - (performance.now() - lastScrollSave);
    if (remaining <= 0) saveScroll();
    else scrollSaveTimer = setTimeout(saveScroll, remaining);
  }

  function animate(element, frames, options, group) {
    if (reducedMotion.matches || !element.animate) return Promise.resolve();
    const animation = element.animate(frames, options);
    animations.add(animation);
    group?.add(animation);
    return animation.finished.catch(() => {}).finally(() => {
      animations.delete(animation);
      group?.delete(animation);
      animation.cancel();
    });
  }

  function stopNavigation() {
    controller?.abort();
    controller = null;
    animations.forEach((animation) => animation.cancel());
    animations.clear();
    document.getElementById("content")?.removeAttribute("aria-busy");
    return ++navigation;
  }

  function updateSectionNavigation() {
    const sections = pageSections.filter((section) => section.getClientRects().length);
    if (!sections.length) return;
    const threshold = Math.min(300, Math.max(160, innerHeight * 0.35));
    let active = sections[0];
    sections.forEach((section) => {
      if (section.getBoundingClientRect().top <= threshold) active = section;
    });
    const last = sections[sections.length - 1];
    const lastBounds = last.getBoundingClientRect();
    const atBottom = scrollY > 1 && scrollY + innerHeight >= document.documentElement.scrollHeight - 2;
    if (atBottom && lastBounds.top < innerHeight && lastBounds.bottom > 0) active = last;
    document.querySelectorAll(".nav a").forEach((link) => {
      if (hashTarget(link.hash) === active) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }

  function updateTOC() {
    scrollFrame = 0;
    const visible = tocLinks.filter(({ link, target }) => link.getClientRects().length && target?.getClientRects().length);
    let active = visible[0];
    visible.forEach((item) => {
      if (item.target.getBoundingClientRect().top <= 140) active = item;
    });
    tocLinks.forEach(({ link }) => {
      if (link === active?.link) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
    updateSectionNavigation();
  }

  function initializeContent() {
    pageSections = [...document.querySelectorAll("[data-page-section][id]")];
    const tabs = [...document.querySelectorAll("[data-reading-mode]")];
    const panels = [...document.querySelectorAll("[data-reading-panel]")];
    const panelAnimations = new Set();
    let activeMode;
    const setMode = (mode, withMotion = false) => {
      const changed = activeMode !== mode;
      activeMode = mode;
      panelAnimations.forEach((animation) => animation.cancel());
      panelAnimations.clear();
      tabs.forEach((tab) => {
        const selected = tab.dataset.readingMode === mode;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
      });
      panels.forEach((panel) => { panel.hidden = panel.dataset.readingPanel !== mode; });
      document.querySelectorAll("[data-reading-toc]").forEach((toc) => {
        toc.hidden = toc.dataset.readingToc !== mode;
      });
      const active = tabs.find((tab) => tab.dataset.readingMode === mode);
      const time = document.querySelector(".reading-time");
      if (active && time) time.textContent = `${active.dataset.readingMinutes} min read`;
      storage.set("readingMode", mode);
      updateTOC();
      const panel = panels.find((item) => item.dataset.readingPanel === mode);
      if (changed && withMotion && panel) {
        void animate(panel, [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "translateY(0)" }], {
          duration: 200, easing: "ease-out",
        }, panelAnimations);
      }
    };
    selectReadingMode = setMode;
    tabs.forEach((tab, index) => {
      const panel = panels.find((item) => item.dataset.readingPanel === tab.dataset.readingMode);
      if (!panel) return;
      tab.id ||= `reading-tab-${index}`;
      panel.id ||= `reading-panel-${index}`;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", panel.id);
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id);
      panel.tabIndex = 0;
      tab.addEventListener("click", () => setMode(tab.dataset.readingMode, true));
      tab.addEventListener("keydown", (event) => {
        let next;
        if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "Home") next = 0;
        if (event.key === "End") next = tabs.length - 1;
        if (next === undefined) return;
        event.preventDefault();
        setMode(tabs[next].dataset.readingMode, true);
        tabs[next].focus();
      });
    });
    tocLinks = [...document.querySelectorAll('.toc a[href^="#"]')].map((link) => ({
      link, target: hashTarget(link.hash),
    }));
    if (tabs.length) {
      const targetPanel = hashTarget(location.hash)?.closest("[data-reading-panel]");
      const preferred = targetPanel?.dataset.readingPanel || storage.get("readingMode");
      setMode(tabs.some((tab) => tab.dataset.readingMode === preferred) ? preferred : tabs[0].dataset.readingMode);
    }
    updateTOC();
    requestAnimationFrame(updateTOC);
  }

  function updatePageDetails(nextDocument) {
    document.title = nextDocument.title;
    document.documentElement.lang = nextDocument.documentElement.lang || "en";
    const metadata = 'meta[name="description"], meta[property^="og:"], link[rel="canonical"]';
    document.head.querySelectorAll(metadata).forEach((element) => element.remove());
    nextDocument.head.querySelectorAll(metadata).forEach((element) => document.head.append(element.cloneNode(true)));
    const nextLinks = [...nextDocument.querySelectorAll(".nav a")];
    document.querySelectorAll(".nav a").forEach((link) => {
      const next = nextLinks.find((item) => item.getAttribute("href") === link.getAttribute("href"));
      const current = next?.getAttribute("aria-current");
      if (current) link.setAttribute("aria-current", current);
      else link.removeAttribute("aria-current");
    });
  }

  function revealHashTarget(url) {
    const target = hashTarget(url.hash);
    const panel = target?.closest("[data-reading-panel]");
    if (panel?.hidden) selectReadingMode?.(panel.dataset.readingPanel);
    return target;
  }

  function restorePosition(url, position, focus) {
    const main = document.getElementById("content");
    if (focus) main?.focus({ preventScroll: true });
    const target = revealHashTarget(url);
    if (position) window.scrollTo({ left: position.x, top: position.y, behavior: "instant" });
    else if (target) target.scrollIntoView({ behavior: "instant", block: "start" });
    else window.scrollTo({ left: 0, top: 0, behavior: "instant" });
    updateTOC();
  }

  async function navigate(url, { pop = false, state = null } = {}) {
    saveScroll();
    const request = stopNavigation();
    const saved = state?.siteNavigation;
    const position = pop ? positions.get(saved?.key) || saved?.scroll : null;
    if (pop && samePage(url, renderedURL)) {
      currentKey = saved?.key || entryKey();
      history.replaceState(stateWith(currentKey, position || scrollPosition()), "");
      renderedURL = url;
      restorePosition(url, position, false);
      return;
    }
    controller = new AbortController();
    const main = document.getElementById("content");
    main?.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(url.href, { signal: controller.signal, headers: { Accept: "text/html" } });
      if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) throw new Error("Page unavailable");
      const finalURL = new URL(response.url);
      if (finalURL.origin !== location.origin) throw new Error("External redirect");
      finalURL.hash = url.hash;
      const nextDocument = new DOMParser().parseFromString(await response.text(), "text/html");
      const nextMain = nextDocument.getElementById("content");
      if (!main || !nextMain || !nextDocument.title) throw new Error("Unsupported page");
      if (request !== navigation) return;
      await animate(main, [{ opacity: 1, transform: "translateY(0)" }, { opacity: 0, transform: "translateY(-6px)" }], {
        duration: 140, easing: "ease-out", fill: "forwards",
      });
      if (request !== navigation) return;
      nextMain.tabIndex = -1;
      main.replaceWith(nextMain);
      updatePageDetails(nextDocument);
      currentKey = pop ? saved?.key || entryKey() : entryKey();
      const nextState = stateWith(currentKey, position || { x: 0, y: 0 });
      if (pop) history.replaceState(nextState, "", finalURL.href);
      else history.pushState(nextState, "", finalURL.href);
      renderedURL = finalURL;
      initializeContent();
      restorePosition(finalURL, position, true);
      void animate(nextMain, [{ opacity: 0, transform: "translateY(14px)" }, { opacity: 1, transform: "translateY(0)" }], {
        duration: 400, easing: "cubic-bezier(.22, 1, .36, 1)",
      });
    } catch (error) {
      if (request !== navigation || error.name === "AbortError") return;
      if (pop) location.reload();
      else location.assign(url.href);
    } finally {
      if (request === navigation) {
        controller = null;
        document.getElementById("content")?.removeAttribute("aria-busy");
      }
    }
  }

  initializeContent();
  if (!window.fetch || !window.DOMParser || !history.pushState) return;
  currentKey = initialEntry?.key || entryKey();
  history.replaceState(stateWith(currentKey, initialScroll || scrollPosition()), "");
  history.scrollRestoration = "manual";
  if (initialScroll || initialURL.hash) {
    const restoreInitialPosition = () => requestAnimationFrame(() => {
      if (navigation || location.href !== initialURL.href) return;
      restorePosition(initialURL, initialScroll, false);
      saveScroll();
    });
    if (document.readyState === "complete") restoreInitialPosition();
    else window.addEventListener("load", restoreInitialPosition, { once: true });
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.hasAttribute("download") || (link.target && link.target !== "_self") || link.relList.contains("external")) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !/^https?:$/.test(url.protocol)) return;
    const segment = url.pathname.split("/").pop();
    if (segment.includes(".") && !/\.html?$/i.test(segment)) return;
    if (samePage(url, renderedURL) && url.href.includes("#")) {
      event.preventDefault();
      saveScroll();
      stopNavigation();
      if (url.href !== location.href) {
        currentKey = entryKey();
        history.pushState(stateWith(currentKey, scrollPosition()), "", url.href);
      }
      renderedURL = url;
      const target = revealHashTarget(url);
      const behavior = reducedMotion.matches ? "instant" : "smooth";
      if (target) {
        if (!target.hasAttribute("tabindex")) {
          target.tabIndex = -1;
          target.addEventListener("blur", () => target.removeAttribute("tabindex"), { once: true });
        }
        target.focus({ preventScroll: true });
        target.scrollIntoView({ behavior, block: "start" });
      } else if (!url.hash) window.scrollTo({ left: 0, top: 0, behavior });
      return;
    }
    event.preventDefault();
    void navigate(url);
  });
  window.addEventListener("popstate", (event) => { void navigate(new URL(location.href), { pop: true, state: event.state }); });
  window.addEventListener("hashchange", () => {
    if (controller || location.href === renderedURL.href) return;
    currentKey = entryKey();
    renderedURL = new URL(location.href);
    history.replaceState(stateWith(currentKey, scrollPosition()), "");
    updateTOC();
  });
  window.addEventListener("pagehide", saveScroll);
  window.addEventListener("scroll", () => {
    persistScroll();
    if (!scrollFrame) scrollFrame = requestAnimationFrame(updateTOC);
  }, { passive: true });
  window.addEventListener("scrollend", persistScroll);
  window.addEventListener("resize", () => {
    if (!scrollFrame) scrollFrame = requestAnimationFrame(updateTOC);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") saveScroll();
  });
  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches) animations.forEach((animation) => animation.cancel());
  });

  if (!location.hash && !initialScroll?.y) {
    [...document.querySelectorAll(".intro, .section-heading, .post-card, .page-head, .profile-about, .article-header, .archive-row")]
      .filter((element) => element.getBoundingClientRect().top < innerHeight)
      .slice(0, 8)
      .forEach((element, index) => {
        void animate(element, [{ opacity: 0, transform: "translateY(12px)" }, { opacity: 1, transform: "translateY(0)" }], {
          duration: 480, delay: index * 45, easing: "cubic-bezier(.22, 1, .36, 1)", fill: "backwards",
        });
      });
  }
})();
