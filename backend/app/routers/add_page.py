"""/add: a plain web page for adding documents from a phone.

iPhone Safari only opens the file chooser during the tap itself. The app's own button has to
go via the server first, so Safari ignores it; this page uses a native file input instead,
which always works and offers Photo Library, Take Photo or Choose File. It uses the login the
DocVault app saved in this browser (same site), uploads, then goes back to the app.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#00796B">
<title>Add documents · DocVault</title>
<link rel="icon" href="/app/favicon.png">
<style>
  :root { --bg:#ffffff; --fg:#1b1c1c; --muted:#5f6368; --card:#f1f4f3; --accent:#00796B; --accent-fg:#ffffff;
          --ok:#2e7d32; --err:#c62828; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1414; --fg:#e3e3e3; --muted:#a3abaa; --card:#1c2423; --accent:#80cbc4; --accent-fg:#003731;
            --ok:#81c784; --err:#ef9a9a; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.4 -apple-system, system-ui, "Segoe UI", Roboto, sans-serif;
         padding: max(16px, env(safe-area-inset-top)) 16px max(24px, env(safe-area-inset-bottom)); }
  main { max-width: 520px; margin: 0 auto; }
  header { display:flex; align-items:center; gap:12px; margin: 8px 0 20px; }
  header a { color:var(--accent); text-decoration:none; font-size:15px; }
  h1 { font-size: 24px; margin: 0; flex: 1; }
  p.hint { color: var(--muted); margin: 0 0 20px; }
  .button { text-decoration:none; }
  .ios { display:none !important; } body.is-ios .ios { display:flex !important; } body.is-ios details.ios { display:block !important; }
  details { background:var(--card); border-radius:14px; padding:12px 14px; margin-top:8px; font-size:15px; }
  summary { color:var(--accent); font-weight:600; cursor:pointer; }
  details li { display:list-item; background:none; padding:2px 0; margin:0 0 8px; }
  details ol { padding-left:20px; margin:8px 0; list-style:decimal; }
  code { word-break:break-all; font-size:13px; }
  #copy { border:1px solid var(--accent); color:var(--accent); background:none; border-radius:12px; padding:2px 10px; font-size:13px; }
  .button { display:flex; align-items:center; justify-content:center; gap:10px; width:100%; padding:16px;
                 border-radius:28px; font-size:17px; font-weight:600; margin-bottom:12px; cursor:pointer; user-select:none; }
  .primary { background:var(--accent); color:var(--accent-fg); }
  .secondary { border:1.5px solid var(--accent); color:var(--accent); }
  input[type=file] { display:none; }
  ul { list-style:none; padding:0; margin:20px 0; }
  li { background:var(--card); border-radius:14px; padding:12px 14px; margin-bottom:8px; display:flex; gap:10px; align-items:center; }
  li .name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  li .state { font-size:14px; color:var(--muted); white-space:nowrap; }
  li.ok .state { color:var(--ok); } li.err .state { color:var(--err); white-space:normal; }
  a.done { display:none; text-align:center; padding:16px; border-radius:28px; background:var(--accent); color:var(--accent-fg);
           font-weight:600; text-decoration:none; }
  .notice { background:var(--card); border-radius:14px; padding:16px; display:none; }
  .notice a { color:var(--accent); font-weight:600; }
</style>
</head>
<body>
<main>
  <header><h1>Add documents</h1><a href="/app/">Cancel</a></header>
  <div class="notice" id="login">Log in to DocVault first, then come back here.<br><br><a href="/app/">Open DocVault</a></div>
  <div id="picker">
    <p class="hint">PDFs or photos of documents. You can pick several at once.</p>
    <label class="button primary">&#128196; Choose files or photos
      <input id="files" type="file" multiple accept="application/pdf,.pdf,image/*"></label>
    <a class="button primary ios" id="scan" href="shortcuts://run-shortcut?name=Scan%20to%20DocVault">&#128209; Scan document</a>
    <label class="button secondary">&#128247; Take a photo
      <input id="camera" type="file" accept="image/*" capture="environment"></label>
    <details class="ios" id="setup">
      <summary>Set up Scan document (once)</summary>
      <p>Scanning uses the iPhone's own document scanner (edges found, page straightened, several pages
         in one PDF) through a shortcut:</p>
      <ol>
        <li>Open <b>Shortcuts</b>, tap <b>+</b> and name it exactly <b>Scan to DocVault</b>.</li>
        <li>Add <b>Scan Document</b>, then <b>Make PDF</b>.</li>
        <li>Add <b>Get Contents of URL</b> with this URL:
          <code id="url">…</code> <button type="button" id="copy">Copy</button><br>
          Show More &rarr; Method <b>POST</b>, Request Body <b>File</b>, File = <b>PDF</b>.</li>
        <li>Add <b>Show Notification</b> with <b>Contents of URL</b>.</li>
      </ol>
      <p>Then tap Scan document here, or run the shortcut from your home screen or Siri.</p>
    </details>
  </div>
  <ul id="list"></ul>
  <a class="done" id="done" href="/app/">Back to DocVault</a>
</main>
<script>
  function token() {
    try { const raw = localStorage.getItem("flutter.dv_token"); return raw ? JSON.parse(raw) : null; }
    catch (e) { return null; }
  }
  const list = document.getElementById("list"), done = document.getElementById("done");
  if (!token()) { document.getElementById("login").style.display = "block"; document.getElementById("picker").style.display = "none"; }

  // iPhone/iPad: the system document scanner is only reachable from Shortcuts.
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (ios) {
    document.body.classList.add("is-ios");
    document.querySelector("label.primary").className = "button secondary";
  }
  if (ios && token()) {
    fetch("/me", { headers: { "Authorization": "Bearer " + token() } }).then(r => r.ok ? r.json() : null).then(me => {
      if (!me) return;
      const url = location.origin + "/u/" + me.api_key + "?name=Scan.pdf";
      document.getElementById("url").textContent = url;
      document.getElementById("copy").onclick = async () => {
        try { await navigator.clipboard.writeText(url); document.getElementById("copy").textContent = "Copied ✓"; } catch (e) {}
      };
    });
  }

  async function upload(files) {
    if (!files.length) return;
    done.style.display = "none";
    let saved = 0;
    for (const file of files) {
      const li = document.createElement("li");
      li.innerHTML = '<span class="name"></span><span class="state">Uploading…</span>';
      li.querySelector(".name").textContent = file.name || "Photo";
      list.appendChild(li);
      const form = new FormData();
      form.append("file", file, file.name || "photo.jpg");
      try {
        const r = await fetch("/documents", { method: "POST", body: form, headers: { "Authorization": "Bearer " + token() } });
        const body = await r.json().catch(() => ({}));
        if (r.status === 401) { throw new Error("Please log in to DocVault again"); }
        if (!r.ok) { throw new Error(body.detail || ("Error " + r.status)); }
        li.className = "ok";
        li.querySelector(".state").textContent = body.already_saved ? "Already saved ✓" : "Saved ✓";
        if (!body.already_saved) saved++;
      } catch (e) {
        li.className = "err";
        li.querySelector(".state").textContent = e.message;
      }
    }
    done.textContent = saved ? "Back to DocVault (" + saved + " added)" : "Back to DocVault";
    done.style.display = "block";
  }
  for (const id of ["files", "camera"]) {
    const input = document.getElementById(id);
    input.addEventListener("change", () => { upload([...input.files]); input.value = ""; });
  }
</script>
</body>
</html>"""


@router.get("/add", response_class=HTMLResponse)
def add_page():
    return HTMLResponse(PAGE, headers={"Cache-Control": "no-cache"})
