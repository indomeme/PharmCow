(function () {
  "use strict";

  const form = document.getElementById("upload-form");
  const input = document.getElementById("vcf-input");
  const drop = document.getElementById("dropzone");
  const nameEl = document.getElementById("file-name");
  const submit = document.getElementById("submit-btn");
  if (!form || !input || !drop || !nameEl || !submit) return;

  const human = (bytes) => {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    let n = bytes;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i++;
    }
    return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  };

  const refresh = () => {
    const file = input.files && input.files[0];
    if (!file) {
      nameEl.textContent = "No file selected";
      nameEl.classList.remove("ready");
      drop.classList.remove("has-file");
      submit.disabled = true;
      return;
    }
    nameEl.textContent = `${file.name} · ${human(file.size)}`;
    nameEl.classList.add("ready");
    drop.classList.add("has-file");
    submit.disabled = false;
  };

  input.addEventListener("change", refresh);

  ["dragenter", "dragover"].forEach((event) => {
    drop.addEventListener(event, (e) => {
      e.preventDefault();
      e.stopPropagation();
      drop.classList.add("dragging");
    });
  });
  ["dragleave", "dragend"].forEach((event) => {
    drop.addEventListener(event, () => drop.classList.remove("dragging"));
  });
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    drop.classList.remove("dragging");
    const files = e.dataTransfer && e.dataTransfer.files;
    if (!files || !files.length) return;
    const dt = new DataTransfer();
    dt.items.add(files[0]);
    input.files = dt.files;
    refresh();
  });

  form.addEventListener("submit", () => {
    submit.disabled = true;
    submit.classList.add("loading");
    const label = submit.querySelector(".btn-label");
    if (label) label.textContent = "Uploading…";
  });

  refresh();
})();
