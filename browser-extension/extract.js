(() => {
  const visible = selector => [...document.querySelectorAll(selector)].some(el => el.getClientRects().length);
  if (visible("#captchacharacters, input[name='cvf_captcha_input'], form[action*='validateCaptcha']"))
    return {status:"waiting", message:"请在采集标签页完成 Amazon 验证，再点击扩展的继续按钮。"};
  if (/\/ap\/(signin|cvf)/.test(location.pathname) || visible("#ap_email, #ap_password, form[name='signIn']"))
    return {status:"waiting", message:"此浏览器配置尚未登录该 Amazon 站点，请在当前标签页登录后继续。"};
  const cards = [...new Set(document.querySelectorAll('div[data-hook="review"], div[id^="customer_review-"]'))];
  const reviews = cards.map(card => {
    const text = selector => (card.querySelector(selector)?.textContent || "").trim();
    const ratingText = text('i[data-hook="review-star-rating"] span, i[data-hook="cmps-review-star-rating"] span, .a-icon-alt');
    const match = ratingText.match(/\d+(?:[.,]\d+)?/);
    const title = text('[data-hook="review-title"]').replace(ratingText, "").trim();
    const id = card.id.match(/customer_review[-_]([A-Za-z0-9]+)/)?.[1] || "";
    return {review_id:id, element_id:card.id, rating:match ? Number(match[0].replace(",", ".")) : null,
      title, content:text('[data-hook="review-body"]'), reviewer_name:text('.a-profile-name'),
      date:text('[data-hook="review-date"]'), verified_purchase:!!card.querySelector('[data-hook="avp-badge"]'),
      helpful_votes:text('[data-hook="helpful-vote-statement"]')};
  }).filter(row => row.content && row.rating >= 1 && row.rating <= 5).slice(0,100);
  return {status:reviews.length ? "ready" : "empty", url:location.href,
    title:(document.querySelector('[data-hook="product-link"], #productTitle')?.textContent || "").trim(),
    reviews};
})()
