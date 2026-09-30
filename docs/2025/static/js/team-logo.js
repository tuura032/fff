// Team logo fallback for the static pages (ENH-006). Mirrors the live
// page's behavior (live.js): a team logo that is missing or fails to load
// (most are third-party hosts that die with the image) is swapped for the
// initials in a rounded square, so a broken image never leaves a broken
// icon in a table row.
//
// The template bakes the fallback into each <img>: data-logo-fb holds the
// initials and data-logo-fb-cls the exact classes of the replacement span,
// so this script never has to guess what the fallback should look like.
// Image error events do not bubble, so the listener is capture-phase, the
// same way live.js registers its swap.
(function () {
  document.addEventListener("error", function (e) {
    var img = e.target;
    if (!img || img.tagName !== "IMG" || !img.hasAttribute("data-logo-fb")) return;
    var span = document.createElement("span");
    span.setAttribute("aria-hidden", "true");
    span.className = img.getAttribute("data-logo-fb-cls") || "";
    span.textContent = img.getAttribute("data-logo-fb") || "?";
    img.replaceWith(span);
  }, true);
})();