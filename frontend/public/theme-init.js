// 깜빡임 방지: 저장된 테마(또는 시스템 설정)를 렌더 전에 적용 (CSP 를 위해 외부 파일로 분리)
(function () {
  try {
    var t = localStorage.getItem("uw-theme");
    var dark = t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (dark) document.documentElement.classList.add("dark");
  } catch (e) {}
})();
