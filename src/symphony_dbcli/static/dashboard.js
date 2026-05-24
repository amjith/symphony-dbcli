(() => {
  const form = document.querySelector("[data-ask-form]");
  const answer = document.querySelector("[data-ask-answer]");
  if (!form || !answer) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const question = String(data.get("q") || "").trim();
    if (!question) {
      renderAnswer({
        answer: "Ask a question about workers, issues, timing, turns, or errors.",
        links: [],
      });
      return;
    }

    answer.classList.add("is-loading");
    try {
      const response = await fetch(`/ask/answer?q=${encodeURIComponent(question)}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Ask failed with HTTP ${response.status}`);
      }
      renderAnswer(await response.json());
      window.history.replaceState({}, "", `/?q=${encodeURIComponent(question)}`);
    } catch (error) {
      renderAnswer({
        answer: error instanceof Error ? error.message : "Ask failed.",
        links: [],
      });
    } finally {
      answer.classList.remove("is-loading");
    }
  });

  function renderAnswer(payload) {
    answer.replaceChildren();
    answer.classList.remove("is-empty");

    const paragraph = document.createElement("p");
    paragraph.textContent = String(payload.answer || "");
    answer.append(paragraph);

    const links = Array.isArray(payload.links) ? payload.links : [];
    if (!links.length) {
      return;
    }

    const linkList = document.createElement("div");
    linkList.className = "answer-links";
    for (const link of links) {
      const anchor = document.createElement("a");
      anchor.href = String(link.url || "#");
      anchor.textContent = String(link.label || link.url || "Detail");
      linkList.append(anchor);
    }
    answer.append(linkList);
  }
})();
