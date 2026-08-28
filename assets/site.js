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
})();
