/* ============================================================
   app.js — небольшие улучшения страницы.
   Здесь всего две функции:
   1. копирование готового поста в буфер обмена;
   2. состояние загрузки, пока нейросеть пишет текст.
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
