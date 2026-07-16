// 会话化登录门禁:启动探测 /api/whoami,未登录则弹登录框,登录成功后刷新页面。
(function(){
  function $(id){ return document.getElementById(id); }
  function showLogin(){ $("loginmodal").classList.add("open"); setTimeout(function(){ var u=$("lg-user"); if(u) u.focus({preventScroll:true}); }, 60); }
  function hideLogin(){ $("loginmodal").classList.remove("open"); }
  function doLogin(){
    var u = $("lg-user").value, p = $("lg-pass").value;
    $("lg-err").textContent = ""; $("lg-btn").disabled = true;
    fetch("/api/login", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({user:u, password:p})})
      .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, json:j}; }); })
      .then(function(x){
        $("lg-btn").disabled = false;
        if (x.ok) { location.reload(); }
        else { $("lg-err").textContent = (x.json && x.json.error) || "登录失败"; $("lg-pass").value=""; }
      })
      .catch(function(){ $("lg-btn").disabled = false; $("lg-err").textContent = "网络错误,请重试"; });
  }
  $("lg-btn").addEventListener("click", doLogin);
  $("lg-pass").addEventListener("keydown", function(e){ if(e.key==="Enter") doLogin(); });
  $("lg-user").addEventListener("keydown", function(e){ if(e.key==="Enter") $("lg-pass").focus({preventScroll:true}); });
  fetch("/api/whoami").then(function(r){
    if(r.ok){
      r.json().then(function(j){ if(window.setAccountUser) window.setAccountUser(j && j.user); }).catch(function(){});
      hideLogin();
    } else {
      if(window.setAccountUser) window.setAccountUser("");
      showLogin();
    }
  }).catch(function(){ if(window.setAccountUser) window.setAccountUser(""); showLogin(); });
})();
