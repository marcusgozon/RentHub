/* RentHub shared script: data, auth, header behaviour. Data lives in localStorage (demo, no backend needed). */
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
  const users = () => store.get("rh_users", []);
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

  function signup(name, email, password) {
    email = email.trim().toLowerCase();
    if (users().some(u => u.email === email)) return "That email already has an account. Try logging in.";
    store.set("rh_users", users().concat({ name: name.trim(), email, password }));
    store.set("rh_session", { name: name.trim(), email });
    return null;
  }
  function login(email, password) {
    email = email.trim().toLowerCase();
    const u = users().find(x => x.email === email && x.password === password);
    if (!u) return "Email or password is incorrect.";
    store.set("rh_session", { name: u.name, email });
    return null;
  }
  function logout() { localStorage.removeItem("rh_session"); location.href = root + "index.html"; }

  // Header: mobile menu, active link, logged-in state
  const menuBtn = $("#menuBtn");
  const setMenu = open => {
    $("#nav").classList.toggle("open", open); $("#auth").classList.toggle("open", open);
    menuBtn.setAttribute("aria-expanded", open); menuBtn.textContent = open ? "✕" : "☰";
  };
  if (menuBtn) {
    menuBtn.setAttribute("aria-expanded", "false");
    menuBtn.addEventListener("click", () => setMenu(!$("#nav").classList.contains("open")));
    window.addEventListener("resize", () => { if (window.innerWidth > 760) setMenu(false); });
  }
  const here = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll("#nav a").forEach(a => { if (a.getAttribute("href").split("/").pop() === here) a.classList.add("active"); });
  const u = user(), auth = $("#auth");
  if (u && auth) {
    auth.innerHTML = '<span class="hello">Hi, ' + esc(u.name.split(" ")[0]) + '</span><button class="btn-primary" id="logoutBtn">Log Out</button>';
    $("#logoutBtn").addEventListener("click", logout);
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

  window.RH = { LISTINGS, peso, today, addMonths, nice, esc, user, myRentals, saveRental, removeRental, endDate, status, requireLogin, signup, login, root };
})();
