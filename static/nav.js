const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.querySelector(".site-nav");

if (navToggle && siteNav) {
  navToggle.addEventListener("click", () => {
    const isOpen = siteNav.classList.toggle("nav-open");
    navToggle.setAttribute("aria-expanded", String(isOpen));
  });

  siteNav.querySelectorAll("nav a").forEach((link) => {
    link.addEventListener("click", () => {
      siteNav.classList.remove("nav-open");
      navToggle.setAttribute("aria-expanded", "false");
    });
  });
}
