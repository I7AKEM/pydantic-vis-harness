// Small composer extension for Pydantic's pinned chat UI, served via Agent.to_web(html_source=...).
// https://pydantic.dev/docs/ai/guides/web/#custom-html-source
// Chat messages, streaming, history, and tool rendering remain owned by Pydantic's UI.
(() => {
  let mountedForm;

  function mountUpload() {
    if (mountedForm?.isConnected) return;
    const textarea = document.querySelector('textarea[name="message"]');
    const form = textarea?.form;
    if (!form) return;
    mountedForm = form;

    const controls = document.createElement("div");
    controls.className = "csv-upload";
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = ".csv,text/csv";
    picker.hidden = true;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Upload CSV";
    button.title = "Upload a CSV to visualize in this conversation";
    const status = document.createElement("span");
    status.setAttribute("role", "status");
    status.textContent = "Upload a CSV to visualize";
    controls.append(button, picker, status);
    textarea.after(controls);

    button.addEventListener("click", () => picker.click());
    picker.addEventListener("change", async () => {
      const file = picker.files[0];
      if (!file) return;
      const conversation = location.pathname;
      button.disabled = true;
      status.setAttribute("role", "status");
      status.textContent = `Uploading ${file.name}…`;
      try {
        const body = new FormData();
        body.append("file", file);
        const response = await fetch("/datasets/upload", { method: "POST", body });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "The CSV could not be uploaded.");
        if (!form.isConnected || location.pathname !== conversation) return;

        const filename = result.filename.replace(/[\r\n]/g, " ").replace(/[\\[\]`*_]/g, "\\$&");
        const reference = `[${filename}](/datasets/${result.dataset_id}/profile)`;
        const question = textarea.value.trim() || "Visualize this supplied CSV using its brief and column meanings.";
        const message = `${question}\n\nAttached CSV: ${reference}`;

        // Use native input/form events so the existing chat sends and saves the message normally.
        const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
        setValue.call(textarea, message);
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        await new Promise(requestAnimationFrame);
        form.requestSubmit();
        status.textContent = `Uploaded ${result.filename}`;
      } catch (error) {
        status.setAttribute("role", "alert");
        status.textContent = error.message || "Upload failed. Try again.";
      } finally {
        button.disabled = false;
        picker.value = "";
      }
    });
  }

  // The built-in UI mounts and replaces the composer during navigation.
  new MutationObserver(mountUpload).observe(document.getElementById("root"), { childList: true, subtree: true });
  mountUpload();
})();
