/* ============================================================
   app.js — маленькие улучшения страницы.
   Здесь всего две функции:
   1. копирование готового поста в буфер обмена;
   2. кнопка «Заполнить примером» (чтобы быстро попробовать генератор).
   ============================================================ */

// ---------- 1. Копирование поста ----------
const copyButton = document.querySelector("[data-copy]");
const postElement = document.getElementById("post-text");
const copyStatus = document.getElementById("copy-status");

if (copyButton && postElement) {
  copyButton.addEventListener("click", async () => {
    const postText = postElement.textContent; // текст поста как есть, с переносами

    try {
      // Современный способ копирования
      await navigator.clipboard.writeText(postText);
    } catch (error) {
      // Запасной способ — если браузер не разрешил доступ к буферу обмена
      copyWithFallback(postText);
    }

    showCopied();
  });
}

// Запасной способ: создаём невидимое поле, выделяем текст и копируем
function copyWithFallback(text) {
  const helper = document.createElement("textarea");
  helper.value = text;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.opacity = "0";
  document.body.appendChild(helper);
  helper.select();
  document.execCommand("copy");
  document.body.removeChild(helper);
}

// Показываем сообщение «Пост скопирован» на 2,5 секунды
function showCopied() {
  if (!copyStatus) return;

  copyStatus.textContent = "Пост скопирован";
  copyStatus.classList.add("is-visible");
  document.querySelector("[data-copy]").classList.add("is-done");

  clearTimeout(showCopied.timer);
  showCopied.timer = setTimeout(() => {
    copyStatus.classList.remove("is-visible");
    document.querySelector("[data-copy]").classList.remove("is-done");
  }, 2500);
}

// ---------- 2. Кнопка «Заполнить примером» ----------
const exampleButton = document.querySelector("[data-example]");

if (exampleButton) {
  exampleButton.addEventListener("click", () => {
    document.getElementById("name").value = "Керамическая кружка «Утро»";
    document.getElementById("description").value =
      "Кружка из плотной керамики с матовой глазурью. Держит тепло до 40 минут, " +
      "удобно лежит в руке и не скользит. Подойдёт для кофе, чая и какао — " +
      "а ещё это отличный подарок коллеге или другу.";
    document.getElementById("price").value = "1 490 ₽";

    // Убираем красную подсветку, если она осталась после проверки
    const description = document.getElementById("description");
    description.removeAttribute("aria-invalid");
    description.focus();
  });
}
