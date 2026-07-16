"use strict";
/* ---- launch ---- */
function launchDir(dir, title, backend, yolo){
  backend=backend||lmBackend||"codex_native";
  postJSON("/api/launch", {dir:dir, title:title||"", backend:backend, yolo:!!yolo}).then(function(r){
    if(r.error){ alert("\u542f\u52a8\u5931\u8d25\uff1a"+r.error); return; }
    var be=r.backend||backend;
    if(!isNativeBackend(be)){ alert("\u540e\u7aef\u8fd4\u56de\u4e86\u4e0d\u652f\u6301\u7684\u4f1a\u8bdd\u7c7b\u578b\u3002\u8bf7\u5148\u5728\u8bbe\u7f6e\u91cc\u91cd\u542f\u540e\u7aef\u5c42\uff0c\u518d\u5237\u65b0\u9875\u9762\u91cd\u8bd5\u3002"); return; }
    showNativeSession(r.sid, (title||basename(r.dir)) + " \u00b7 " + backendLabel(be));
    nRenderYoloBadge({yolo:r.yolo});
    loadSidebarData(); pollSessionSignals();
  });
}
function renderBackend(boxId){
  var box=$(boxId); if(!box) return; box.innerHTML="";
  availBackends.forEach(function(b){
    var btn=document.createElement("button"); btn.textContent=isClaudeBackend(b)?"Claude":"Codex";
    if(b===lmBackend) btn.classList.add("active");
    btn.addEventListener("click", function(){ lmBackend=b; acPrefSet("acBackend", b, "acBackend"); renderBackend("lm-backend"); });
    box.appendChild(btn);
  });
}
function renderYolo(boxId, swId){ var b=$(boxId); if(!b) return; b.classList.toggle("active", lmYolo); if($(swId)) $(swId).textContent=lmYolo?"\u5f00":"\u5173"; }
function setYolo(v, persist){ lmYolo=!!v; if(persist!==false){ acPrefSet("acYolo", lmYolo?"1":"0", "acYolo"); } renderYolo("lm-yolo","lm-yolo-sw"); renderYolo("set-yolo","set-yolo-sw"); }
function updateLmStart(){ $("lm-start").disabled=!lmDir; }
function openLaunchModal(){
  updateLmStart(); renderBackend("lm-backend"); setYolo(lmYolo, false);
  $("launchmodal").classList.add("open");
}
function openLaunchNew(){
  lmDir=""; lmTitle=""; $("lm-dir").textContent="\ud83d\udcc1 \u672a\u9009\u62e9\u76ee\u5f55 \u2014 \u70b9\u300c\u9009\u62e9\u76ee\u5f55\u300d"; openLaunchModal();
}
function openLaunchForDir(dir, title){
  lmDir=dir||""; lmTitle=title||basename(dir); $("lm-dir").textContent="\ud83d\udcc1 "+lmDir; openLaunchModal();
}
function closeLaunch(){ $("launchmodal").classList.remove("open"); }
$("newbtn").addEventListener("click", openLaunchNew);
$("mbnew").addEventListener("click", function(){ openSidebar(); openLaunchNew(); });
$("lm-pickdir").addEventListener("click", openBrowse);
$("lm-yolo").addEventListener("click", function(){ setYolo(!lmYolo); });
$("set-yolo").addEventListener("click", function(){ setYolo(!lmYolo); });
$("lm-cancel").addEventListener("click", closeLaunch);
$("launchmodal").addEventListener("click", function(e){ if(e.target===$("launchmodal")) closeLaunch(); });
$("lm-start").addEventListener("click", function(){
  if(!lmDir) return; var dir=lmDir, title=lmTitle||basename(lmDir), backend=lmBackend, yolo=lmYolo;
  closeLaunch(); launchDir(dir, title, backend, yolo);
});

/* ---- browse modal ---- */
var browseCur="";
function browseRender(b){
  browseCur=b.path||"";
  $("browsecrumbs").innerHTML=browseCur?'当前目录：<b>'+esc(browseCur)+'</b>':'<b>我的电脑</b> · 选一个盘进入';
  $("browse-open").disabled=!browseCur;
  var list=$("browselist"); list.innerHTML="";
  if(b.error){ var e=document.createElement("div"); e.className="err"; e.textContent=b.error; list.appendChild(e); }
  if(b.parent!==undefined && (b.parent||browseCur)) list.appendChild(makeBitem("…  上级目录", b.parent, "parent"));
  (b.entries||[]).forEach(function(en){ list.appendChild(makeBitem(en.name, en.path, "")); });
  if(!b.error && !(b.entries && b.entries.length)){ var n=empty("（没有子文件夹）"); list.appendChild(n); }
}
function makeBitem(name, path, extra){
  var a=document.createElement("div"); a.className="bitem "+(extra||"");
  var ic=document.createElement("span"); ic.className="ic"; ic.innerHTML='<i class="ic" data-lucide="folder"></i>';
  var t=document.createElement("span"); t.textContent=name;
  a.appendChild(ic); a.appendChild(t);
  a.addEventListener("click", function(){ browseGo(path); });
  return a;
}
function browseGo(path){ api("/api/browse?path="+encodeURIComponent(path)).then(browseRender); }
function openBrowse(){ $("browsemodal").classList.add("open"); if(!browseCur) browseGo(""); }
function closeBrowse(){ $("browsemodal").classList.remove("open"); }
$("browse-cancel").addEventListener("click", closeBrowse);
$("browsemodal").addEventListener("click", function(e){ if(e.target===$("browsemodal")) closeBrowse(); });
$("browse-open").addEventListener("click", function(){
  if(!browseCur) return;
  lmDir=browseCur; lmTitle=basename(browseCur); $("lm-dir").innerHTML='<i class="ic" data-lucide="folder"></i> '+esc(browseCur); updateLmStart();
  closeBrowse();
});
