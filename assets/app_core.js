"use strict";
var $ = function(id){ return document.getElementById(id); };
function api(p, opts){ return fetch(p, opts).then(function(r){ return r.json(); }); }
function postJSON(p, obj){ return fetch(p, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(obj||{})}).then(function(r){ return r.json(); }); }
/* ---- cookie helper + 访客标识(内网穿透下区分不同访问者;随每个请求自动回传后端) ---- */
function acGetCookie(name){
  var n = name + "=", parts = (document.cookie || "").split(";");
  for(var i=0;i<parts.length;i++){
    var p = parts[i].trim();
    if(p.indexOf(n) === 0){
      try { return decodeURIComponent(p.substring(n.length)); } catch(e){ return p.substring(n.length); }
    }
  }
  return "";
}
function acSetCookie(name, value, maxAgeDays){
  var v = encodeURIComponent(String(value == null ? "" : value));
  var sec = (location.protocol === "https:") ? " Secure;" : "";
  var ma = "; Max-Age=" + Math.round((maxAgeDays || 3650) * 86400);
  document.cookie = name + "=" + v + "; Path=/; SameSite=Lax;" + sec + ma;
}
function acPrefGetRaw(cookieName, lsKey){
  var cv = acGetCookie(cookieName);
  if(cv !== "") return {val: cv, src: "cookie"};
  var lv = "";
  try { lv = localStorage.getItem(lsKey) || ""; } catch(e){}
  if(lv !== ""){ acSetCookie(cookieName, lv, 3650); return {val: lv, src: "migrated"}; }
  return {val: "", src: "none"};
}
function acPrefSet(cookieName, value, lsKey){
  acSetCookie(cookieName, value, 3650);
  try { localStorage.setItem(lsKey, value); } catch(e){}
}
function acNewVisitorId(){
  try {
    var b = new Uint8Array(16);
    (window.crypto || window.msCrypto).getRandomValues(b);
    var s = "v-";
    for(var i=0;i<b.length;i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16);
    return s;
  } catch(e){
    return "v-" + (Math.random().toString(16) + "00000000000000000000").slice(2, 18)
                 + (Math.random().toString(16) + "00000000000000000000").slice(2, 18);
  }
}
var AC_VISITOR = acGetCookie("ac_visitor");
if(!AC_VISITOR){ AC_VISITOR = acNewVisitorId(); acSetCookie("ac_visitor", AC_VISITOR, 3650); }
var AC_USER = "";
function setAccountUser(user){
  AC_USER = user || "";
  var el = $("account-user");
  if(el) el.textContent = AC_USER || "—";
}
function esc(s){
  s = String(s == null ? "" : s);
  return s.replace(/[&<>"]/g, function(c){
    if(c === "&") return "&amp;";
    if(c === "<") return "&lt;";
    if(c === ">") return "&gt;";
    return "&quot;";
  });
}
function empty(msg){ var e=document.createElement("div"); e.className="empty"; e.textContent=msg; return e; }
function fmtTime(ts){
  if(!ts) return "";
  var d=new Date(ts*1000); function p(x){ return x<10?"0"+x:x; }
  return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate())+" "+p(d.getHours())+":"+p(d.getMinutes());
}
function relTime(ts){
  if(!ts) return "—";
  var s=Math.max(0, Math.floor(Date.now()/1000-ts));
  if(s<60) return "刚刚";
  if(s<3600) return Math.floor(s/60)+"分钟前";
  if(s<86400) return Math.floor(s/3600)+"小时前";
  if(s<86400*7) return Math.floor(s/86400)+"天前";
  return fmtTime(ts);
}
function elapsedStr(ts){ if(!ts) return "—"; var s=Math.max(0,Math.floor(Date.now()/1000-ts)); var h=Math.floor(s/3600),m=Math.floor((s%3600)/60),ss=s%60; return (h?h+":":"")+(m<10?"0":"")+m+":"+("0"+ss).slice(-2); }
function basename(p){
  var s=String(p||"");
  var i=Math.max(s.lastIndexOf("/"), s.lastIndexOf(String.fromCharCode(92)));
  return i>=0 ? s.slice(i+1) : s;
}
function normDir(p){
  var s=String(p||"").split(String.fromCharCode(92)).join("/").toLowerCase();
  while(s.length>1 && s.slice(-1)==="/") s=s.slice(0,-1);
  return s;
}
function stateTag(st){
  if(st==="running") return '<span class="tag run">运行中</span>';
  if(st==="confirm") return '<span class="tag confirm">需确认</span>';
  if(st==="plan") return '<span class="tag plan">Plan 待确认</span>';
  if(st==="new") return '<span class="tag new">新窗口</span>';
  return '<span class="tag idle">空闲</span>';
}
function isCodexBackend(b){ return b==="codex" || b==="codex_native"; }
function isClaudeBackend(b){ return b==="claude" || b==="native" || b==="claude_native"; }
function isNativeBackend(b){ return isCodexBackend(b) || isClaudeBackend(b); }
function backendLabel(b){ return isCodexBackend(b)?"Codex":"Claude"; }
function backendTag(b){ return isClaudeBackend(b)?'<span class="tag be-claude">Claude</span>':'<span class="tag be-codex">Codex</span>'; }
function backendShort(b){ return isCodexBackend(b)?"Codex":"Claude"; }

/* ---- restart ---- */
function restartWebOnly(){
  if(!confirm("仅重启网站服务？运行中的会话会继续保留。")) return;
  postJSON("/api/restart_web").catch(function(){});
  var t=document.createElement("div"); t.textContent="重启中…"; t.style.cssText="position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);background:#ffffff;border:1px solid #e9e8e5;box-shadow:0 14px 40px rgba(0,0,0,.12);padding:14px 22px;border-radius:9px;z-index:99999;color:#151515;font-weight:600";
  document.body.appendChild(t);
  setTimeout(function(){ location.reload(); }, 1600);
}
function fullRestart(){
  if(!confirm("完全重启整个服务？会杀掉所有运行中的 codex / claude 会话并重新加载代码，约 3-6 秒后自动重连。")) return;
  var o=document.createElement("div"); o.id="rstoast";
  o.style.cssText="position:fixed;inset:0;background:rgba(255,255,255,.94);color:#151515;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:99999;gap:12px;font-size:15px";
  o.innerHTML='<div style="font-size:28px">🔄</div><div>正在完全重启服务…</div><div style="font-size:12px;color:#747474">所有会话将被终止,几秒后自动重连</div>';
  document.body.appendChild(o);
  postJSON("/api/restart").catch(function(){});
  var n=0; var iv=setInterval(function(){ n++; api("/api/backends").then(function(){ clearInterval(iv); location.reload(); }).catch(function(){}); if(n>40){ clearInterval(iv); var t=$("rstoast"); if(t) t.innerHTML='<div style="font-size:15px">重启超时,请手动刷新页面</div>'; } }, 1000);
}
function restartManagerOnly(){
  if(!confirm("仅重启后端层(manager)？运行中的会话会保留并在重启后重连(含滚动历史),约 4-8 秒。")) return;
  var o=document.createElement("div"); o.id="rstoast";
  o.style.cssText="position:fixed;inset:0;background:rgba(255,255,255,.94);color:#151515;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:99999;gap:12px;font-size:15px";
  o.innerHTML='<div style="font-size:28px">♻️</div><div>正在重启后端层…</div><div style="font-size:12px;color:#747474">会话保留,几秒后自动重连</div>';
  document.body.appendChild(o);
  postJSON("/api/restart_manager").catch(function(){});
  var n=0; var iv=setInterval(function(){ n++;
    api("/api/backends").then(function(){
      api("/api/sessions").then(function(){ clearInterval(iv); location.reload(); }).catch(function(){});
    }).catch(function(){});
    if(n>40){ clearInterval(iv); var t=$("rstoast"); if(t) t.innerHTML='<div style="font-size:15px">重启超时,请手动刷新页面</div>'; }
  }, 1000);
}

/* ---- backends ---- */
var availBackends=["codex_native","claude_native"];
api("/api/backends").then(function(r){ if(r.backends && r.backends.length){ availBackends=r.backends; if(availBackends.indexOf(lmBackend)<0){ lmBackend=availBackends[0]; acPrefSet("acBackend", lmBackend, "acBackend"); } renderBackend("lm-backend"); } });

/* ---- notifications (in-site only) ---- */
var noticeTimers={};
function removeNotice(key, immediate){
  var el=document.querySelector('[data-notice-key="'+key+'"]');
  if(noticeTimers[key]) clearTimeout(noticeTimers[key]); delete noticeTimers[key];
  if(!el) return;
  if(immediate){ el.remove(); return; }
  if(el.classList.contains("leaving")) return;
  el.classList.add("leaving"); el.setAttribute("aria-hidden", "true");
  setTimeout(function(){ if(el.parentNode) el.remove(); }, 190);
}
function emitAndroidNotice(kind, s, title, body){
  try{
    s=s||{};
    if(window.AndroidNotify && typeof window.AndroidNotify.notify==="function"){
      window.AndroidNotify.notify(JSON.stringify({kind:kind, sid:s.sid||"", title:title||"", body:body||"", backend:s.backend||"", dir:s.dir||"", state:s.state||""}));
    }
  }catch(e){}
}
function emitAndroidSessionNotice(kind, sid, title, body){ emitAndroidNotice(kind, {sid:sid||"", state:kind}, title, body); }
function noticeKindMeta(kind){
  if(kind==="confirm") return {kicker:"需要你确认", label:"需要确认", action:"处理", icon:_I('alert'), timeout:70000, role:"alert"};
  if(kind==="plan") return {kicker:"计划审阅", label:"计划待审阅", action:"审阅", icon:_I('clipboard-list'), timeout:70000, role:"alert"};
  if(kind==="done") return {kicker:"已完成", label:"任务完成", action:"查看", icon:_I('circle-check'), timeout:14000, role:"status"};
  if(kind==="new") return {kicker:"新会话", label:"已创建", action:"打开", icon:_I('sparkles'), timeout:18000, role:"status"};
  return {kicker:"Agent 通知", label:"通知", action:"打开", icon:_I('bell'), timeout:18000, role:"status"};
}
function noticeSessionTitle(s){ return String((s&&s.title)||basename(s&&s.dir)||"未命名任务").trim(); }
function noticeProjectName(s){
  var dir=(s&&s.dir)||"";
  return String(basename(dir)||dir||"当前会话").trim();
}
function noticePayload(kind, s, detail){
  var meta=noticeKindMeta(kind);
  var task=noticeSessionTitle(s);
  var project=noticeProjectName(s);
  var backend=backendLabel((s&&s.backend)||"codex");
  var hint=detail||({confirm:"点击处理确认请求",plan:"点击审阅计划并决定是否继续",done:"等待下一条指令",new:"点击打开新会话"}[kind]||"点击打开会话");
  return {
    meta:meta,
    title:meta.label+" · "+task,
    body:backend+" · "+project+"\n"+hint,
  };
}
function openNoticeSession(s, key){
  removeNotice(key);
  if(s&&s.sid) openSessionBySid(s.sid);
}
function showSiteNotice(kind, s, title, body, payload){
  var key=((s&&s.sid)||"notice")+"-"+kind; removeNotice(key, true);
  payload=payload||{meta:noticeKindMeta(kind), title:title, body:body};
  var meta=payload.meta||noticeKindMeta(kind);
  var box=document.createElement("div"); box.className="notice "+kind; box.setAttribute("data-notice-key", key);
  box.setAttribute("role", meta.role||"status"); box.tabIndex=0;
  box.innerHTML='<div class="notice-accent" aria-hidden="true"></div><div class="notice-icon" aria-hidden="true">'+(meta.icon||_I('bell'))+'</div><div class="notice-main"><div class="notice-kicker">'+esc(meta.kicker||"通知")+'</div><div class="notice-title">'+esc(title||payload.title||"通知")+'</div><div class="notice-body">'+esc(body||payload.body||"")+'</div></div>';
  var acts=document.createElement("div"); acts.className="notice-actions";
  var open=document.createElement("button"); open.textContent=meta.action||"打开";
  var close=document.createElement("button"); close.className="ghost"; close.textContent="稍后"; close.setAttribute("aria-label", "关闭通知");
  open.addEventListener("click", function(ev){ ev.stopPropagation(); openNoticeSession(s, key); });
  close.addEventListener("click", function(ev){ ev.stopPropagation(); removeNotice(key); });
  box.addEventListener("click", function(){ openNoticeSession(s, key); });
  box.addEventListener("keydown", function(ev){ if(ev.key==="Enter"||ev.key===" "){ ev.preventDefault(); openNoticeSession(s, key); } });
  acts.appendChild(open); acts.appendChild(close); box.appendChild(acts);
  var area=$("noticearea"); if(!area) return;
  area.appendChild(box);
  while(area.children.length>3){
    var old=area.children[0], oldKey=old&&old.getAttribute("data-notice-key");
    if(oldKey) removeNotice(oldKey, true); else if(old) old.remove(); else break;
  }
  noticeTimers[key]=setTimeout(function(){ removeNotice(key); }, meta.timeout||18000);
}
function emitAiNotice(kind, s){
  var payload=noticePayload(kind, s);
  showSiteNotice(kind, s, payload.title, payload.body, payload);
  emitAndroidNotice(kind, s, payload.title, payload.body);
}
