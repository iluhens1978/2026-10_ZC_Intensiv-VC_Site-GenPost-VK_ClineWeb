/* ============================================================
   app.js — небольшие улучшения страницы:
   1. копирование поста (в «Готовом посте» и в «Избранном»);
   2. состояние загрузки, пока нейросеть пишет текст;
   3. удобный минимум для поля с датой публикации.
   ============================================================ */

// ---------- 1. Копирование поста ----------
// Кнопок копирования на странице может быть несколько, поэтому
// каждая ищет свой текст в ближайшем блоке .copyable
const copyButtons = document.querySelectorAll("[data-copy]");

copyButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    const block = button.closest(".copyable");
    const postElement = block ? block.querySelector(".post") : null;
    const status = block ? block.querySelector("[data-copy-status]") : null;

    if (!postElement) return;

    const postText = postElement.textContent; // текст поста как есть, с переносами

    try {
      await navigator.clipboard.writeText(postText); // современный способ
    } catch (error) {
      copyWithFallback(postText); // запасной способ
    }

    showCopied(button, status);
  });
});

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
function showCopied(button, status) {
  if (!status) return;

  status.textContent = "Пост скопирован";
  status.classList.add("is-visible");
  button.classList.add("is-done");

  clearTimeout(showCopied.timer);
  showCopied.timer = setTimeout(() => {
    status.classList.remove("is-visible");
    button.classList.remove("is-done");
  }, 2500);
}

// ---------- 2. Загрузка, пока нейросеть пишет пост ----------
const forms = document.querySelectorAll("[data-form]");
const loadingHint = document.querySelector("[data-loading]");

forms.forEach((form) => {
  const submitButton = form.querySelector("[data-submit]");

  if (!submitButton) return;

  form.addEventListener("submit", () => {
    submitButton.classList.add("is-loading");
    submitButton.disabled = true; // защита от двойного нажатия

    if (loadingHint) {
      loadingHint.classList.add("is-visible");
    }

    // Если ответа нет дольше 100 секунд — возвращаем кнопку в рабочее состояние
    setTimeout(() => {
      submitButton.classList.remove("is-loading");
      submitButton.disabled = false;
    }, 100000);
  });
});

// ---------- 3. Поле «дата и время» для отложенного поста ----------
const scheduleInput = document.querySelector(".input--datetime");

if (scheduleInput) {
  // Подставляем ближайшее удобное время (через час), чтобы не вводить вручную
  scheduleInput.addEventListener("focus", () => {
    if (scheduleInput.value) return;

    const soon = new Date(Date.now() + 60 * 60 * 1000);
    const pad = (number) => String(number).padStart(2, "0");
    scheduleInput.value =
      soon.getFullYear() +
      "-" + pad(soon.getMonth() + 1) +
      "-" + pad(soon.getDate()) +
      "T" + pad(soon.getHours()) +
      ":" + pad(soon.getMinutes());
  });
}
