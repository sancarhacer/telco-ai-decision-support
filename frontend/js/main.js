async function loadPartial(targetId, path) {
  const target = document.getElementById(targetId);
  if (!target) return;

  const response = await fetch(path);
  if (!response.ok) {
    target.innerHTML = "";
    return;
  }

  target.innerHTML = await response.text();
}

function markActiveNav() {
  const currentPage = window.location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".top-nav a").forEach((link) => {
    const href = link.getAttribute("href")?.replace("./", "");
    if (href === currentPage) {
      link.classList.add("active");
    }
  });

  // Ana sayfadaysa geri butonunu gizle
  if (currentPage === "index.html" || currentPage === "") {
    document.querySelectorAll(".back-button").forEach((btn) => {
      btn.style.display = "none";
    });
  }
}

async function bootstrapLayout() {
  await Promise.all([
    loadPartial("siteHeader", "./partials/header.html"),
    loadPartial("siteFooter", "./partials/footer.html"),
  ]);
  markActiveNav();
}

bootstrapLayout();
