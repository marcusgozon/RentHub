/* RentHub shared script: auth (Flask + MySQL), header behaviour, and demo rental data (localStorage). */
(function () {
  const root = document.body.dataset.root || "";
  const $ = (s, r = document) => r.querySelector(s);
  const store = {
    get(k, f) { try { const v = JSON.parse(localStorage.getItem(k)); return v == null ? f : v; } catch (e) { return f; } },
    set(k, v) { localStorage.setItem(k, JSON.stringify(v)); }
  };

  const LISTINGS = [];

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
  const rememberedUser = () => store.get("rh_remember_me", { email: "", password: "", enabled: false });
  const setRememberedUser = (email, password, enabled) => {
    if (!enabled || !email) { localStorage.removeItem("rh_remember_me"); return; }
    store.set("rh_remember_me", { email: String(email).trim().toLowerCase(), password: String(password), enabled: true });
  };
  const clearRememberedUser = () => localStorage.removeItem("rh_remember_me");
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

  // Forgot password flow: requests a code, verifies it, and then sets a new password.
  async function forgotPassword(email) {
    const { ok, data } = await post("/api/forgot-password", { email });
    if (!ok) return { error: data.error || "Could not send reset code." };
    return { emailHint: data.email_hint || email, message: data.message };
  }

  async function verifyResetCode(code) {
    const { ok, data } = await post("/api/verify-reset-code", { code });
    if (!ok) return { error: data.error || "Verification failed." };
    return {};
  }

  async function resendResetCode() {
    const { ok, data } = await post("/api/resend-reset-code");
    return ok ? { message: data.message } : { error: data.error || "Could not resend the code." };
  }

  async function resetPassword(password) {
    const { ok, data } = await post("/api/reset-password", { password });
    if (!ok) return { error: data.error || "Could not update your password." };
    return { message: data.message };
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
    auth.innerHTML = `
      <div class="notification-wrap" id="notificationWrap">
        <button class="notification-toggle" id="notificationToggle" type="button"
          aria-label="Notifications" aria-expanded="false" aria-controls="notificationPanel">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/>
            <path d="M10 21h4"/>
          </svg>
          <span class="notification-count" id="notificationCount" hidden></span>
        </button>
        <section class="notification-panel" id="notificationPanel" aria-label="Notifications" hidden>
          <div class="notification-heading">
            <strong>Notifications</strong>
            <button type="button" class="notification-refresh" id="notificationRefresh">Refresh</button>
          </div>
          <div class="notification-list" id="notificationList" aria-live="polite">
            <p class="notification-empty">Loading notifications…</p>
          </div>
          <a class="notification-all" href="${esc(root)}pages/myrentals.html">View all rental requests</a>
        </section>
      </div>
      <button class="btn-primary" id="logoutBtn">Log Out</button>`;
    $("#logoutBtn").addEventListener("click", logout);

    const notificationWrap = $("#notificationWrap");
    const notificationToggle = $("#notificationToggle");
    const notificationPanel = $("#notificationPanel");
    const notificationList = $("#notificationList");
    const notificationCount = $("#notificationCount");
    let notificationItems = [];
    const closeNotifications = () => {
      notificationPanel.hidden = true;
      notificationToggle.setAttribute("aria-expanded", "false");
    };
    const notificationStatus = status => status.charAt(0).toUpperCase() + status.slice(1);
    const renderNotifications = () => {
      const attention = notificationItems.filter(item =>
        u.role === "landlord" ? item.status === "pending" :
          item.status !== "paid"
      ).length;
      notificationCount.textContent = attention > 9 ? "9+" : String(attention);
      notificationCount.hidden = attention === 0;
      if (!notificationItems.length) {
        notificationList.innerHTML = '<p class="notification-empty">You have no rental notifications.</p>';
        return;
      }
      notificationList.innerHTML = notificationItems.slice(0, 8).map(item => {
        const status = notificationStatus(item.status);
        const message = u.role === "landlord"
          ? `Rental request from ${esc(item.tenant_name)}`
          : `Your request was ${esc(item.status)}`;
        const details = u.role === "landlord"
          ? `${esc(item.title)} · ${esc(item.tenant_email)}`
          : `${esc(item.title)} · ${esc(item.location)}`;
        const actions = u.role === "landlord" && item.status === "pending"
          ? `<div class="notification-actions"><button type="button" data-notification-action="approve" data-id="${item.id}">Approve</button><button type="button" data-notification-action="reject" data-id="${item.id}">Decline</button></div>`
          : u.role === "tenant" && item.status === "approved"
            ? `<a class="notification-pay" href="${esc(root)}pages/browse.html?payRequest=${item.id}">Continue to payment</a>`
            : "";
        return `<article class="notification-item">
          <div class="notification-item-top"><strong>${message}</strong><span>${status}</span></div>
          <p>${details}</p>
          ${actions}
        </article>`;
      }).join("");
    };
    const loadNotifications = async () => {
      try {
        const response = await fetch("/api/rental-requests", {
          credentials: "same-origin",
          cache: "no-store"
        });
        if (!response.ok) {
          throw new Error(response.status === 401
            ? "Please log in again to see notifications."
            : "Could not load notifications. Try refreshing.");
        }
        const data = await response.json();
        notificationItems = Array.isArray(data.requests) ? data.requests : [];
        renderNotifications();
      } catch (error) {
        notificationItems = [];
        notificationCount.hidden = true;
        notificationList.innerHTML = `<p class="notification-empty">${esc(error.message || "Could not load notifications. Try refreshing.")}</p>`;
      }
    };
    notificationToggle.addEventListener("click", () => {
      const open = notificationPanel.hidden;
      notificationPanel.hidden = !open;
      notificationToggle.setAttribute("aria-expanded", String(open));
      if (open) loadNotifications();
    });
    $("#notificationRefresh").addEventListener("click", loadNotifications);
    notificationWrap.addEventListener("click", async event => {
      const button = event.target.closest("[data-notification-action]");
      if (!button) return;
      button.disabled = true;
      try {
        const response = await fetch(`/api/rental-requests/${button.dataset.id}/decision`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: button.dataset.notificationAction })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "Could not update the rental request.");
        await loadNotifications();
      } catch (error) {
        notificationList.insertAdjacentHTML("afterbegin",
          `<p class="notification-error">${esc(error.message || "Could not update the rental request.")}</p>`);
        button.disabled = false;
      }
    });
    document.addEventListener("click", event => {
      if (!notificationWrap.contains(event.target)) closeNotifications();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") closeNotifications();
    });
    loadNotifications();
    window.setInterval(() => {
      if (!document.hidden) loadNotifications();
    }, 30000);

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

    // Landlords don't rent homes: "My Rentals" becomes "My Listings" and "Extend Stay" is hidden.
    if (u.role === "landlord") {
      document.querySelectorAll("#nav a").forEach(a => {
        const file = a.getAttribute("href").split("/").pop();
        if (file === "myrentals.html") a.textContent = "My Listings";
        if (file === "extendstay.html") a.parentElement.remove();
      });
    }

    // Role-based dashboard link (tenant.html or landlord.html) in the main menu.
    const navList = document.querySelector("#nav ul");
    if (navList && (u.role === "tenant" || u.role === "landlord") && !navList.querySelector("[data-dash]")) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.setAttribute("data-dash", "");
      a.href = root + "pages/" + u.role + ".html";
      a.textContent = "Dashboard";
      if (here === u.role + ".html") a.classList.add("active");
      li.appendChild(a);
      navList.appendChild(li);
    }

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

  window.RH = { setAvatar: a => setAvatar(a), store, LISTINGS, peso, today, addMonths, nice, esc, user, rememberedUser, setRememberedUser, clearRememberedUser, myRentals, saveRental, removeRental, endDate, status, requireLogin, signup, verifySignup, resendSignup, login, verify2fa, resend2fa, forgotPassword, verifyResetCode, resendResetCode, resetPassword, emailTaken, root };
})();

/* RentHub payments: billing + late-fee maths. Pure logic (no DOM), so it is easy to test and
   easy to move to the Flask backend later. Dates are "YYYY-MM-DD" strings, money is rounded to cents. */
(function (root) {
  const round2 = n => Math.round((Number(n) + Number.EPSILON) * 100) / 100;
  const pad = n => String(n).padStart(2, "0");
  const parse = iso => new Date(iso + "T00:00:00");
  const fmt = d => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  const daysBetween = (a, b) => Math.round((parse(b) - parse(a)) / 86400000);
  const addDays = (iso, n) => { const d = parse(iso); d.setDate(d.getDate() + n); return fmt(d); };
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  // What a landlord can customise. Late-fee types: none | flat | per_day | percent
  const DEFAULT_SETTINGS = {
    dueDay: 5,
    graceDays: 3,
    penalty: { type: "per_day", value: 50, cap: 0 },
    extras: [], // recurring monthly charges: { id, name, amount }
    methods: [
      { id: "gcash", name: "GCash", details: "", enabled: true },
      { id: "maya", name: "Maya", details: "", enabled: true },
      { id: "bank", name: "Bank transfer", details: "", enabled: true },
      { id: "cash", name: "Cash", details: "Pay your landlord in person.", enabled: true }
    ]
  };

  const dueDate = (period, dueDay) => {
    const [y, m] = period.split("-").map(Number);
    return y + "-" + pad(m) + "-" + pad(Math.min(dueDay, new Date(y, m, 0).getDate()));
  };

  const itemsTotal = bill => round2(bill.items.reduce((s, i) => s + Number(i.amount || 0), 0));

  // Late fee as of a given day. Nothing is charged until the grace period has passed.
  function penalty(bill, asOf) {
    const rule = bill.rule;
    if (!rule || rule.type === "none") return 0;
    const late = daysBetween(addDays(bill.dueDate, rule.graceDays), asOf); // days past the grace period
    if (late <= 0) return 0;
    const base = itemsTotal(bill);
    let p = 0;
    if (rule.type === "flat") p = rule.value;
    else if (rule.type === "per_day") p = rule.value * late;
    else if (rule.type === "percent") p = base * rule.value / 100;
    if (rule.cap > 0) p = Math.min(p, rule.cap);
    return round2(p);
  }

  const totalDue = (bill, asOf) => round2(itemsTotal(bill) + penalty(bill, asOf));
  const sumBy = (bill, status) => round2(bill.payments.filter(p => p.status === status).reduce((s, p) => s + p.amount, 0));

  // The late fee stops growing on the day a payment fully covers the bill.
  function settle(bill) {
    delete bill.settledOn;
    let cum = 0;
    const verified = bill.payments.filter(p => p.status === "verified").sort((a, b) => a.on.localeCompare(b.on));
    for (const p of verified) {
      cum = round2(cum + p.amount);
      if (cum + 0.005 >= totalDue(bill, p.on)) { bill.settledOn = p.on; break; }
    }
    return bill;
  }

  function summary(bill, today) {
    const asOf = bill.settledOn || today;
    const pen = penalty(bill, asOf);
    const total = round2(itemsTotal(bill) + pen);
    const paid = sumBy(bill, "verified");
    return {
      penalty: pen, total, paid,
      pending: sumBy(bill, "pending"),
      balance: bill.settledOn ? 0 : Math.max(0, round2(total - paid)),
      status: bill.settledOn ? "Paid" : today > bill.dueDate ? "Overdue" : "Unpaid",
      daysToDue: daysBetween(today, bill.dueDate)
    };
  }

  function makeBill({ rental, period, settings, extraItems }) {
    const items = [{ name: "Rent", amount: Number(rental.price) }]
      .concat((settings.extras || []).map(x => ({ name: x.name, amount: Number(x.amount) })))
      .concat(extraItems || [])
      .filter(i => i.name && i.amount > 0);
    return {
      id: uid(), rentalId: rental.id, owner: rental.owner, title: rental.title, location: rental.location,
      period, dueDate: dueDate(period, settings.dueDay), items,
      // The rule is copied into the bill so later setting changes never alter an agreed bill.
      rule: { type: settings.penalty.type, value: settings.penalty.value, cap: settings.penalty.cap, graceDays: settings.graceDays },
      payments: [], createdOn: fmt(new Date())
    };
  }

  const ruleText = (r, peso) => {
    if (!r || r.type === "none") return "No late fee";
    const what = r.type === "flat" ? peso(r.value) + " one-time" : r.type === "per_day" ? peso(r.value) + " per late day" : r.value + "% of the bill";
    return what + (r.cap > 0 ? ", max " + peso(r.cap) : "") + ", after " + r.graceDays + " grace day" + (r.graceDays === 1 ? "" : "s");
  };

  const api = { round2, daysBetween, addDays, uid, DEFAULT_SETTINGS, dueDate, itemsTotal, penalty, totalDue, settle, summary, makeBill, ruleText };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Pay = api;
})(typeof window !== "undefined" ? window : globalThis);