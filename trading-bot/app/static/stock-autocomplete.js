"use strict";

(() => {
  const stockInputs = [
    document.querySelector("#symbols-input"),
    document.querySelector("#symbol-input"),
    document.querySelector("#paper-stock-code"),
    document.querySelector("#auto-buy-code"),
  ].filter(Boolean);

  function activeQuery(value) {
    return value.split(",").at(-1).trim();
  }

  function replaceActiveQuery(value, name) {
    const parts = value.split(",");
    parts[parts.length - 1] = parts.length > 1 ? ` ${name}` : name;
    return parts.join(",");
  }

  function attachAutocomplete(input) {
    input.removeAttribute("pattern");
    input.setAttribute("autocomplete", "off");
    const wrapper = document.createElement("div");
    wrapper.className = "stock-autocomplete";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.append(input);

    const list = document.createElement("div");
    list.className = "stock-suggestions";
    list.setAttribute("role", "listbox");
    wrapper.append(list);
    let timer;
    let requestNumber = 0;

    function close() {
      list.replaceChildren();
      list.hidden = true;
    }

    function render(items) {
      list.replaceChildren();
      if (!items.length) return close();
      for (const item of items) {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "stock-suggestion";
        option.setAttribute("role", "option");
        const name = document.createElement("strong");
        name.textContent = item.name;
        const code = document.createElement("span");
        code.textContent = item.stock_code;
        option.append(name, code);
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          input.value = replaceActiveQuery(input.value, item.name);
          close();
          input.focus();
          input.dispatchEvent(new Event("change", { bubbles: true }));
        });
        list.append(option);
      }
      list.hidden = false;
    }

    input.addEventListener("input", () => {
      clearTimeout(timer);
      const query = activeQuery(input.value);
      if (query.length < 3) return close();
      timer = setTimeout(async () => {
        const currentRequest = ++requestNumber;
        try {
          const response = await fetch(`/market/search?query=${encodeURIComponent(query)}`);
          const body = await response.json();
          if (!response.ok || currentRequest !== requestNumber) return close();
          render(body.items || []);
        } catch {
          close();
        }
      }, 250);
    });
    input.addEventListener("blur", () => setTimeout(close, 120));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close();
    });
  }

  stockInputs.forEach(attachAutocomplete);
})();
