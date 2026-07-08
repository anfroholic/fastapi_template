/* In-browser file viewer for component packages.
 *
 * Fetches a text view (LEF / Verilog / Liberty / YAML) and renders it with
 * highlight.js syntax highlighting + line numbers, in a modal overlay. LEF and
 * Liberty have no stock highlight.js grammar, so we register compact ones here.
 */
(function () {
  "use strict";

  // --- custom grammars ----------------------------------------------------
  // LEF: keyword-driven ASCII (MACRO/PIN/PORT/LAYER/RECT/SIZE ...).
  hljs.registerLanguage("lef", function (hljs) {
    return {
      case_insensitive: false,
      keywords:
        "VERSION BUSBITCHARS DIVIDERCHAR UNITS MACRO CLASS FOREIGN ORIGIN SIZE BY " +
        "SYMMETRY SITE PIN DIRECTION USE SHAPE PORT LAYER RECT POLYGON PATH " +
        "OBS END LIBRARY PROPERTY ANTENNAMODEL INPUT OUTPUT INOUT POWER GROUND " +
        "SIGNAL ANALOG CLOCK BLOCK CORE PAD RING",
      contains: [
        hljs.COMMENT("#", "$"),
        hljs.QUOTE_STRING_MODE,
        hljs.C_NUMBER_MODE,
      ],
    };
  });

  // Liberty (.lib): C-like blocks -- library(){ cell(){ pin(){...} } }.
  hljs.registerLanguage("liberty", function (hljs) {
    return {
      case_insensitive: true,
      keywords:
        "library cell pin bus bundle timing internal_power leakage_power " +
        "related_pin timing_sense timing_type direction capacitance " +
        "max_transition function clock ff latch table_lookup wire_load " +
        "operating_conditions default_operating_conditions lu_table_template " +
        "index_1 index_2 values rise_delay fall_delay cell_rise cell_fall " +
        "rise_transition fall_transition when unit true false",
      contains: [
        hljs.COMMENT("/\\*", "\\*/"),
        hljs.C_LINE_COMMENT_MODE,
        hljs.QUOTE_STRING_MODE,
        hljs.C_NUMBER_MODE,
      ],
    };
  });

  // map file extension -> highlight.js language id
  function langFor(name) {
    const n = name.toLowerCase();
    if (n.endsWith(".yaml") || n.endsWith(".yml")) return "yaml";
    if (n.endsWith(".json")) return "json";
    if (n.endsWith(".vh") || n.endsWith(".v") || n.endsWith(".sv") || n.endsWith(".svh"))
      return "verilog";
    if (n.endsWith(".lef")) return "lef";
    if (n.endsWith(".lib")) return "liberty";
    if (n.endsWith(".sdc") || n.endsWith(".tcl")) return "tcl";
    return "plaintext";
  }

  // --- modal wiring -------------------------------------------------------
  const el = {
    modal: document.getElementById("viewer"),
    name: document.getElementById("viewer-name"),
    lang: document.getElementById("viewer-lang"),
    code: document.getElementById("viewer-code"),
    copy: document.getElementById("viewer-copy"),
    download: document.getElementById("viewer-download"),
  };
  if (!el.modal) return;

  let currentText = "";

  function open() { el.modal.hidden = false; document.body.classList.add("no-scroll"); }
  function close() { el.modal.hidden = true; document.body.classList.remove("no-scroll"); }

  async function view(url, name) {
    const lang = langFor(name);
    el.name.textContent = name;
    el.lang.textContent = lang === "plaintext" ? "" : lang;
    el.download.href = url;
    el.code.textContent = "Loading…";
    el.code.removeAttribute("data-highlighted");
    open();

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("HTTP " + res.status);
      currentText = await res.text();
    } catch (e) {
      el.code.textContent = "Could not load file: " + e.message;
      return;
    }

    // highlight, then prepend a line-number gutter
    let html;
    try {
      html = hljs.highlight(currentText, { language: lang, ignoreIllegals: true }).value;
    } catch (_) {
      html = hljs.highlightAuto(currentText).value;
    }
    const lines = html.split("\n");
    const gutter = lines.map((_, i) => (i + 1)).join("\n");
    el.code.innerHTML =
      '<span class="ln-gutter">' + gutter + "</span>" +
      '<span class="ln-code">' + html + "</span>";
  }

  // delegate clicks from any [data-url] view trigger
  document.addEventListener("click", function (ev) {
    const trigger = ev.target.closest(".js-view");
    if (trigger) {
      ev.preventDefault();
      view(trigger.dataset.url, trigger.dataset.name || "file");
      return;
    }
    if (ev.target.closest("[data-close]")) close();
  });

  el.copy.addEventListener("click", function () {
    navigator.clipboard.writeText(currentText).then(() => {
      el.copy.textContent = "copied!";
      setTimeout(() => (el.copy.textContent = "copy"), 1400);
    });
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !el.modal.hidden) close();
  });
})();
