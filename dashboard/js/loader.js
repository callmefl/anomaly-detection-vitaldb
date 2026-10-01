/**
 * VITALDB HTML PARTIAL LOADER
 * Lightweight include system — fetches HTML partials and injects them into data-include slots.
 * No build tools, no frameworks. Just fetch + innerHTML.
 */

async function loadPartials() {
  const slots = document.querySelectorAll('[data-include]');
  const version = '3.8';

  await Promise.all([...slots].map(async (el) => {
    const path = el.getAttribute('data-include');
    try {
      const res = await fetch(`${path}?v=${version}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const htmlContent = await res.text();
      el.outerHTML = htmlContent;
    } catch (err) {
      console.error(`[loader] Failed to load partial: ${path}`, err);
      el.innerHTML = `<div style="color:#ef4444;padding:1rem;font-size:0.8rem;">Errore caricamento: ${path}</div>`;
    }
  }));
}
