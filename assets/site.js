(() => {
  const root = document.documentElement;
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") root.dataset.theme = stored;

  document.querySelector(".theme-toggle")?.addEventListener("click", () => {
    const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
    const currentDark = root.dataset.theme === "dark" || (!root.dataset.theme && systemDark);
    root.dataset.theme = currentDark ? "light" : "dark";
    localStorage.setItem("theme", root.dataset.theme);
  });

  const readingTabs = [...document.querySelectorAll("[data-reading-mode]")];
  if (readingTabs.length) {
    const setReadingMode = (mode) => {
      readingTabs.forEach((tab) => {
        const selected = tab.dataset.readingMode === mode;
        tab.setAttribute("aria-selected", String(selected));
      });
      document.querySelectorAll("[data-reading-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.readingPanel !== mode;
      });
      document.querySelectorAll("[data-reading-toc]").forEach((toc) => {
        toc.hidden = toc.dataset.readingToc !== mode;
      });
      const active = readingTabs.find((tab) => tab.dataset.readingMode === mode);
      const time = document.querySelector(".reading-time");
      if (active && time) time.textContent = `${active.dataset.readingMinutes} min read`;
      localStorage.setItem("readingMode", mode);
    };
    readingTabs.forEach((tab) => tab.addEventListener("click", () => setReadingMode(tab.dataset.readingMode)));
    const preferred = localStorage.getItem("readingMode");
    setReadingMode(preferred === "long" ? "long" : "coffee");
  }
})();
