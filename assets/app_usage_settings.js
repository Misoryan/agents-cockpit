"use strict";
/* ---- usage ---- */
var ccCache=null;
function fmtTok(n){ n=Number(n)||0; if(n>=1e9) return (n/1e9).toFixed(2)+"B"; if(n>=1e6) return (n/1e6).toFixed(1)+"M"; if(n>=1e3) return (n/1e3).toFixed(1)+"k"; return String(n); }
function renderSummary(){
  var el=$("summary"); if(!el) return;
  if(!ccCache){ el.innerHTML='<div class="empty" style="grid-column:1/-1">用量加载中…</div>'; return; }
  if(!ccCache.enabled){ el.innerHTML='<div class="empty" style="grid-column:1/-1">未检测到 CC Switch 用量数据</div>'; return; }
  if(ccCache.error){ el.innerHTML='<div class="err" style="grid-column:1/-1">'+esc(ccCache.error)+'</div>'; return; }
  var u=ccCache.usage||{}, t=u.today||{}, mo=u.month||{}, chips=[];
  chips.push('<div class="sumchip"><div class="sv">'+fmtTok(t.input_tokens)+'</div><div class="sl">今日输入 tokens</div></div>');
  chips.push('<div class="sumchip"><div class="sv">'+fmtTok(t.output_tokens)+'</div><div class="sl">今日输出 tokens</div></div>');
  chips.push('<div class="sumchip"><div class="sv">'+fmtTok(t.cache_tokens)+'</div><div class="sl">今日缓存 tokens</div></div>');
  chips.push('<div class="sumchip"><div class="sv">'+fmtTok((Number(mo.input_tokens)||0)+(Number(mo.output_tokens)||0)+(Number(mo.cache_tokens)||0))+'</div><div class="sl">本月总 tokens</div></div>');
  var prov=(ccCache.providers||[]).filter(function(p){return p.is_current;})[0];
  var provTxt=prov?(prov.app_type==="claude"?"Claude":prov.app_type==="codex"?"Codex":prov.app_type)+" · "+esc(prov.name)+(prov.model?" · "+esc(prov.model):""):"";
  el.innerHTML=chips.join("")+(provTxt?'<div class="sumprov" style="grid-column:1/-1">'+provTxt+'</div>':'');
}
function refreshCC(){
  api("/api/cc_usage").then(function(d){
    ccCache=d; renderSummary();
    if(!d||!d.enabled){ $("usagebody").innerHTML='<div class="empty">未检测到 CC Switch (~/.cc-switch/cc-switch.db)</div>'; return; }
    if(d.error){ $("usagebody").innerHTML='<div class="err">读取失败:'+esc(d.error)+'</div>'; return; }
    var u=d.usage||{}, list=[];
    (d.providers||[]).filter(function(p){return p.is_current;}).forEach(function(p){
      var be=p.app_type==="claude"?'<span class="tag be-claude">Claude</span>':p.app_type==="codex"?'<span class="tag be-codex">Codex</span>':'<span class="tag">'+esc(p.app_type)+'</span>';
      list.push('<div class="dirrow"><div class="nm">'+be+' '+esc(p.name)+'</div><div class="mt">模型 '+(p.model?esc(p.model):'—')+' · '+(p.host?esc(p.host):'本机')+'</div></div>');
    });
    var t=u.today||{}, mo=u.month||{};
    var todayTotal=(Number(t.input_tokens)||0)+(Number(t.output_tokens)||0)+(Number(t.cache_tokens)||0);
    var monthTotal=(Number(mo.input_tokens)||0)+(Number(mo.output_tokens)||0)+(Number(mo.cache_tokens)||0);
    list.push('<div class="dirrow"><div class="nm">今日 '+fmtTok(todayTotal)+' tokens</div><div class="mt">输入 '+fmtTok(t.input_tokens)+' / 输出 '+fmtTok(t.output_tokens)+' / 缓存 '+fmtTok(t.cache_tokens)+'</div><div class="mt" style="margin-top:6px">本月 '+fmtTok(monthTotal)+' tokens</div></div>');
    var bm=u.by_model||[];
    if(bm.length){
      var maxTok=Math.max.apply(null, bm.map(function(x){return Number(x.tokens)||0;}))||1;
      var rows=bm.map(function(x){ var tok=Number(x.tokens)||0; var w=Math.max(4,Math.round(tok/maxTok*100)); return '<div style="margin:5px 0"><div style="display:flex;justify-content:space-between;font-size:12px"><span>'+esc(x.model)+'</span><span style="color:#747474">'+fmtTok(tok)+' tokens</span></div><div style="height:5px;background:#f3f2f0;border-radius:3px;margin-top:3px"><div style="height:5px;width:'+w+'%;background:#151515;border-radius:3px"></div></div></div>'; }).join("");
      list.push('<div class="dirrow"><div class="nm" style="font-size:13px">按模型（今日）</div>'+rows+'</div>');
    } else { list.push('<div class="empty">暂无 token 用量记录（请确认 CC Switch 的本地代理已启用并记录请求）</div>'); }
    if(u.last_ts){ list.push('<div style="font-size:11px;color:#a3a29f;margin:6px 2px">最近一条:'+fmtTime(u.last_ts)+(d.cached?' · (缓存)':'')+'</div>'); }
    $("usagebody").innerHTML=list.join("");
  }).catch(function(){ $("usagebody").innerHTML='<div class="err">加载失败</div>'; });
}

/* ---- sidebar open/close (responsive) ---- */
var SIDEBAR_OVERLAY_QUERY="(max-width:1020px)";
function isNarrow(){ return window.matchMedia(SIDEBAR_OVERLAY_QUERY).matches; }
function syncSidebarChrome(){
  var menu=$("menubtn"); if(!menu) return;
  var visible=isNarrow()?document.body.classList.contains("sb-open"):!document.body.classList.contains("sb-collapsed");
  menu.setAttribute("aria-expanded", visible?"true":"false");
}
function openSidebar(){
  document.body.classList.remove("sb-collapsed");
  if(isNarrow()) document.body.classList.add("sb-open");
  syncSidebarChrome();
}
function closeSidebar(){ document.body.classList.remove("sb-open"); syncSidebarChrome(); }
function toggleSidebar(){
  if(isNarrow()){
    document.body.classList.remove("sb-collapsed");
    document.body.classList.toggle("sb-open");
  } else {
    document.body.classList.toggle("sb-collapsed");
  }
  syncSidebarChrome();
}
$("menubtn").addEventListener("click", toggleSidebar);
$("sb-close").addEventListener("click", function(){ if(isNarrow()) closeSidebar(); else { document.body.classList.add("sb-collapsed"); syncSidebarChrome(); } });
$("sbreopen").addEventListener("click", openSidebar);
$("shade").addEventListener("click", closeSidebar);
window.addEventListener("resize", function(){ if(!isNarrow()) document.body.classList.remove("sb-open"); syncSidebarChrome(); });
syncSidebarChrome();
$("sb-search").addEventListener("input", function(){ sbSearch=$("sb-search").value; renderSidebar(); });
if($("hist-active")) $("hist-active").addEventListener("click", function(){ setHistoryView(false); });
if($("hist-archived")) $("hist-archived").addEventListener("click", function(){ setHistoryView(true); });

/* bottom buttons + settings */
$("usagebtn").addEventListener("click", function(){ closeSidebar(); setMainView("usage"); });
$("settingsbtn").addEventListener("click", function(){ openSettings(); });
if($("landing-open-sidebar")) $("landing-open-sidebar").addEventListener("click", openSidebar);
$("landing-usage").addEventListener("click", function(){ setMainView("usage"); });
$("usageback").addEventListener("click", function(){ setMainView("landing"); });
function openSettings(){ renderYolo("set-yolo","set-yolo-sw"); var sv=$("set-visitor"); if(sv) sv.textContent=AC_VISITOR; $("settingsmodal").classList.add("open"); }
function closeSettings(){ $("settingsmodal").classList.remove("open"); }
function logoutAndSwitchUser(){
  if(!confirm("登出当前用户" + (AC_USER ? "「" + AC_USER + "」" : "") + "？正在运行的会话不会被停止。")) return;
  fetch("/api/logout", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
    .then(function(){ location.reload(); })
    .catch(function(){
      acSetCookie("ac_session", "", -1);
      location.reload();
    });
}
$("set-restartweb").addEventListener("click", restartWebOnly);
$("set-softrestart").addEventListener("click", restartManagerOnly);
$("set-fullrestart").addEventListener("click", fullRestart);
$("logoutbtn").addEventListener("click", logoutAndSwitchUser);
$("set-logout").addEventListener("click", logoutAndSwitchUser);
$("set-close").addEventListener("click", closeSettings);
$("settingsmodal").addEventListener("click", function(e){ if(e.target===$("settingsmodal")) closeSettings(); });
