(function () {
  const form = document.getElementById("config-form");
  const list = document.getElementById("steps-list");
  const addButton = document.getElementById("add-step");
  const sequenceJson = document.getElementById("sequence_json");
  if (!form || !list || !addButton || !sequenceJson) return;

  function addStep(playlist, seconds) {
    const row = document.createElement("div");
    row.className = "step-row flex flex-wrap items-end gap-3";
    row.innerHTML =
      '<label class="block">' +
      '<span class="mb-1 block text-xs text-mist">Playlist (1–250)</span>' +
      '<input type="number" min="1" max="250" value="' + playlist + '" class="field step-playlist w-28" required />' +
      "</label>" +
      '<label class="block">' +
      '<span class="mb-1 block text-xs text-mist">Segundos</span>' +
      '<input type="number" min="1" max="3600" value="' + seconds + '" class="field step-seconds w-28" required />' +
      "</label>" +
      '<button type="button" class="remove-step rounded-lg border border-line px-3 py-2 text-sm text-mist hover:border-ember hover:text-ember">Quitar</button>';
    row.querySelector(".remove-step").addEventListener("click", function () {
      if (list.children.length === 1) return;
      row.remove();
    });
    list.appendChild(row);
  }

  addButton.addEventListener("click", function () {
    addStep(1, 10);
  });

  form.addEventListener("submit", function (event) {
    const steps = Array.from(list.querySelectorAll(".step-row")).map(function (row) {
      return {
        playlist: Number(row.querySelector(".step-playlist").value),
        seg: Number(row.querySelector(".step-seconds").value),
      };
    });
    if (!steps.length) {
      event.preventDefault();
      return;
    }
    sequenceJson.value = JSON.stringify({ loop: true, steps: steps });
  });

  addStep(1, 3);
  addStep(4, 2);
})();
