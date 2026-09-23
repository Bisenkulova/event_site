"use strict";
const button = document.getElementById("access-toggle");
function renderAccessible(on) {
  document.body.classList.toggle("accessible", on);
  button.setAttribute("aria-pressed", on ? "true" : "false");
  button.textContent = on ? "Обычная версия" : "Версия для слабовидящих";
}
try { renderAccessible(localStorage.getItem("accessible") === "yes"); }
catch (error) { renderAccessible(false); }
button.addEventListener("click", () => {
  const next = !document.body.classList.contains("accessible");
  renderAccessible(next);
  try { localStorage.setItem("accessible", next ? "yes" : "no"); }
  catch (error) { /* сохранение предпочтения необязательно */ }
});
