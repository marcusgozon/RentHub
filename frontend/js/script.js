/* RentHub shared script: auth (Flask + MySQL), header behaviour, and demo rental data (localStorage). */
(function () {
  const root = document.body.dataset.root || "";
  const $ = (s, r = document) => r.querySelector(s);
  const store = {
    get(k, f) { try { const v = JSON.parse(localStorage.getItem(k)); return v == null ? f : v; } catch (e) { return f; } },
    set(k, v) { localStorage.setItem(k, JSON.stringify(v)); }
  };

  const LISTINGS = [
    { id: 1, title: "Studio near UP Diliman", location: "Diliman, Quezon City", type: "Studio", beds: 0, baths: 1, price: 9500 },
    { id: 2, title: "Cozy 1BR condo", location: "Cubao, Quezon City", type: "Condo", beds: 1, baths: 1, price: 14000 },
    { id: 3, title: "Family apartment", location: "Project 4, Quezon City", type: "Apartment", beds: 2, baths: 1, price: 16500 },
    { id: 4, title: "Bedspace for students", location: "Teachers Village, Quezon City", type: "Bedspace", beds: 0, baths: 1, price: 3500 },
    { id: 5, title: "Modern 2BR condo", location: "Eastwood, Libis", type: "Condo", beds: 2, baths: 2, price: 28000 },
    { id: 6, title: "Townhouse with parking", location: "Kamuning, Quezon City", type: "House", beds: 3, baths: 2, price: 32000 },
    { id: 7, title: "Studio by the MRT", location: "North Avenue, Quezon City", type: "Studio", beds: 0, baths: 1, price: 11000 },
    { id: 8, title: "Garden-view apartment", location: "Marikina Heights, Marikina", type: "Apartment", beds: 2, baths: 1, price: 13500 }
  ];

  const peso = n => "₱" + Number(n).toLocaleString("en-PH");
  const pad = n => String(n).padStart(2, "0");
  const fmt = d => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  const today = () => fmt(new Date());
  const addMonths = (iso, n) => {
    const d = new Date(iso + "T00:00:00"), day = d.getDate();
    d.setDate(1); d.setMonth(d.getMonth() + n);
    d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
    return fmt(d);
  };
  const nice = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-PH", { year: "numeric", month: "short", day: "numeric" });
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const user = () => store.get("rh_session", null);
  const allRentals = () => store.get("rh_rentals", []);
  const myRentals = () => { const u = user(); return u ? allRentals().filter(r => r.owner === u.email) : []; };
  const saveRental = r => { const all = allRentals().filter(x => x.id !== r.id); all.push(r); store.set("rh_rentals", all); };
  const removeRental = id => store.set("rh_rentals", allRentals().filter(r => r.id !== id));
  const endDate = r => addMonths(r.moveIn, r.months);
  const status = r => { const t = today(); return t < r.moveIn ? "Upcoming" : t > endDate(r) ? "Ended" : "Active"; };

  function requireLogin() {
    if (user()) return true;
    const next = location.pathname.split("/").pop() + location.search;
    location.replace(root + "pages/login.html?next=" + encodeURIComponent(next));
    return false;
  }

  // Asks the backend whether an account with this email already exists.
  async function emailTaken(email) {
    email = String(email || "").trim();
    if (!email) return false;
    try {
      const response = await fetch("/api/check-email?email=" + encodeURIComponent(email), { credentials: "same-origin" });
      if (!response.ok) return false;
      return Boolean((await response.json()).exists);
    } catch (error) {
      return false; // Can't reach the server: the register call will report the real problem.
    }
  }

  // Shared helper for the login / 2FA calls. Returns { ok, data } or { ok:false, data:{error} }.
  async function post(url, body) {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body || {})
      });
      return { ok: response.ok, data: await response.json() };
    } catch (error) {
      return { ok: false, data: { error: "Can't reach the backend. Make sure the RentHub Python server is running." } };
    }
  }

  // Step 1 of login. Resolves to { error } | { requires2fa, emailHint } | {} (logged in).
  async function login(email, password) {
    const { ok, data } = await post("/api/login", { email, password });
    if (!ok) return { error: data.error || "Login failed." };
    if (data.requires_2fa) return { requires2fa: true, emailHint: data.email_hint };
    store.set("rh_session", { name: data.user.name, email: data.user.email, role: data.user.role });
    return {};
  }

  // Step 2 of login: the 6-digit code from the email. Resolves to { error } | {}.
  async function verify2fa(code) {
    const { ok, data } = await post("/api/verify-2fa", { code });
    if (!ok) return { error: data.error || "Verification failed." };
    store.set("rh_session", { name: data.user.name, email: data.user.email, role: data.user.role });
    return {};
  }

  // Ask for a new code. Resolves to { error } | { message }.
  async function resend2fa() {
    const { ok, data } = await post("/api/resend-2fa");
    return ok ? { message: data.message } : { error: data.error || "Could not resend the code." };
  }
  // Step 1 of signup: sends the 6-digit code. Resolves to { error } | { emailHint }.
  // The account is NOT created yet; that happens in verifySignup().
  async function signup(name, email, password, role = "tenant") {
    const { ok, data } = await post("/api/register", { name, email, password, role });
    if (!ok) return { error: data.error || "Could not create account." };
    return { emailHint: data.email_hint };
  }

  // Step 2 of signup: the emailed code creates the account and logs the user in.
  async function verifySignup(code) {
    const { ok, data } = await post("/api/verify-signup", { code });
    if (!ok) return { error: data.error || "Verification failed." };
    store.set("rh_session", { name: data.user.name, email: data.user.email, role: data.user.role });
    return {};
  }

  async function resendSignup() {
    const { ok, data } = await post("/api/resend-signup");
    return ok ? { message: data.message } : { error: data.error || "Could not resend the code." };
  }

  async function logout() {
    try { await fetch("/api/logout", { method: "POST", credentials: "same-origin" }); } catch (error) {}
    localStorage.removeItem("rh_session");
    location.href = root + "index.html";
  }


  // Page loader: fades out once the page is ready, and fades back in when switching pages.
  const loader = $("#pageLoader");
  if (loader) {
    const started = Date.now(), MIN_SHOW = 250;
    const hide = () => setTimeout(() => loader.classList.add("is-hidden"), Math.max(0, MIN_SHOW - (Date.now() - started)));
    if (document.readyState === "complete") hide(); else window.addEventListener("load", hide);
    // Coming back with the browser's Back button can restore the page with the loader still showing.
    window.addEventListener("pageshow", e => { if (e.persisted) loader.classList.add("is-hidden"); });
    document.addEventListener("click", e => {
      const a = e.target.closest("a[href]");
      if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (a.target && a.target !== "_self") return;
      if (a.hasAttribute("download")) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin) return;
      if (url.pathname === location.pathname && url.search === location.search) return; // same page / #anchor
      e.preventDefault();
      loader.classList.remove("is-hidden");
      setTimeout(() => { location.href = url.href; }, 220);
    });
  }

  // Header: mobile menu, active link, logged-in state
  const menuBtn = $("#menuBtn");
  const setMenu = open => {
    $("#nav").classList.toggle("open", open); $("#auth").classList.toggle("open", open);
    document.body.classList.toggle("menu-open", open);
    menuBtn.setAttribute("aria-expanded", open);
  };
  if (menuBtn) {
    menuBtn.setAttribute("aria-expanded", "false");
    menuBtn.addEventListener("click", () => setMenu(!$("#nav").classList.contains("open")));
    window.addEventListener("resize", () => { if (window.innerWidth > 760) setMenu(false); });
    // Close the drawer: tap the dimmed page, press Escape, or pick a link.
    document.addEventListener("click", e => {
      if (!$("#nav").classList.contains("open")) return;
      if (e.target.closest("#nav, #auth, #menuBtn")) { if (e.target.closest("#nav a, #auth a")) setMenu(false); return; }
      setMenu(false);
    });
    document.addEventListener("keydown", e => { if (e.key === "Escape") setMenu(false); });
  }
  const here = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll("#nav a").forEach(a => { if (a.getAttribute("href").split("/").pop() === here) a.classList.add("active"); });
  let setAvatar = () => {};
  const u = user(), auth = $("#auth");
  if (u && auth) {
    // Logged in: a profile icon (photo if they have one) that opens the profile page.
    auth.innerHTML = '<button class="btn-primary" id="logoutBtn">Log Out</button>';
    $("#logoutBtn").addEventListener("click", logout);

    const USER_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/></svg>';
    const link = document.createElement("a");
    link.id = "profileLink";
    link.className = "profile-link";
    link.href = root + "pages/profile.html";
    link.title = "Edit profile";
    link.setAttribute("aria-label", "Edit profile");
    if (here === "profile.html") link.classList.add("active");
    const paint = avatar => { link.innerHTML = avatar ? '<img src="' + esc(avatar) + '" alt="" />' : USER_ICON; };
    paint(u.avatar);
    setAvatar = avatar => { store.set("rh_session", { ...(user() || u), avatar: avatar || null }); paint(avatar); };
    auth.parentNode.insertBefore(link, auth);

    // Refresh the saved photo in the background (e.g. changed on another device).
    fetch("/api/profile", { credentials: "same-origin" })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d) return;
        const cur = user() || u;
        if ((cur.avatar || null) !== (d.profile.avatar || null)) {
          store.set("rh_session", { ...cur, avatar: d.profile.avatar });
          paint(d.profile.avatar);
        }
      })
      .catch(() => {});
  }


  // Show/hide toggle on every password field
  const EYE = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  const EYE_OFF = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.9 17.9A10.5 10.5 0 0 1 12 19c-6.4 0-10-7-10-7a18 18 0 0 1 5.1-5.9M9.9 5.2A10 10 0 0 1 12 5c6.4 0 10 7 10 7a18 18 0 0 1-2.2 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2"/><path d="M2 2l20 20"/></svg>';
  document.querySelectorAll('input[type="password"]').forEach(inp => {
    const wrap = document.createElement("div");
    wrap.className = "pw-wrap";
    inp.parentNode.insertBefore(wrap, inp);
    wrap.appendChild(inp);
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "pw-toggle";
    btn.setAttribute("aria-label", "Show password"); btn.innerHTML = EYE;
    btn.addEventListener("click", () => {
      const show = inp.type === "password";
      inp.type = show ? "text" : "password";
      btn.innerHTML = show ? EYE_OFF : EYE;
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
    wrap.appendChild(btn);
  });

  // Home search form validation
  const sf = $("#searchForm");
  if (sf) sf.addEventListener("submit", e => {
    const err = $("#formError"), mi = $("#moveIn").value, mp = $("#maxPrice").value;
    err.textContent = "";
    if (mi && mi < today()) { e.preventDefault(); err.textContent = "Move-in date can't be in the past."; }
    else if (mp && Number(mp) <= 0) { e.preventDefault(); err.textContent = "Enter a price above 0."; }
  });

  window.RH = { setAvatar: a => setAvatar(a), store, LISTINGS, peso, today, addMonths, nice, esc, user, myRentals, saveRental, removeRental, endDate, status, requireLogin, signup, verifySignup, resendSignup, login, verify2fa, resend2fa, emailTaken, root };
})();
