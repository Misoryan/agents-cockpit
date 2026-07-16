"use strict";
/* ---- launch ---- */
function launchDir(dir, title, backend, yolo){
  backend=backend||lmBackend||"codex_native";
  postJSON("/api/launch", {dir:dir, title:title||"", backend:backend, yolo:!!yolo, codex:codexLaunchConfig(backend)}).then(function(r){
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
    btn.addEventListener("click", function(){ lmBackend=b; acPrefSet("acBackend", b, "acBackend"); renderBackend("lm-backend"); renderCodexConfig(); loadCodexOptions(); });
    box.appendChild(btn);
  });
}
function renderYolo(boxId, swId){ var b=$(boxId); if(!b) return; b.classList.toggle("active", lmYolo); if($(swId)) $(swId).textContent=lmYolo?"\u5f00":"\u5173"; }
function setYolo(v, persist){ lmYolo=!!v; if(persist!==false){ acPrefSet("acYolo", lmYolo?"1":"0", "acYolo"); } renderYolo("lm-yolo","lm-yolo-sw"); renderYolo("set-yolo","set-yolo-sw"); }
function updateLmStart(){ $("lm-start").disabled=!lmDir; }
function codexLaunchConfig(backend){
  if(!isCodexBackend(backend||lmBackend)) return {};
  return {
    model:lmCodexModel,
    webSearch:lmCodexSearch,
    sandbox:lmCodexSandbox,
    approvalPolicy:lmCodexApproval,
    reasoningEffort:lmCodexReasoning,
    reasoningSummary:lmCodexSummary,
    serviceTier:lmCodexServiceTier,
    writableRoots:lmCodexWritableRoots
  };
}
function setCodexConfigFromInputs(persist){
  if($("lm-codex-model")) lmCodexModel=$("lm-codex-model").value.trim();
  if($("lm-codex-search")) lmCodexSearch=$("lm-codex-search").value;
  if($("lm-codex-sandbox")) lmCodexSandbox=$("lm-codex-sandbox").value;
  if($("lm-codex-approval")) lmCodexApproval=$("lm-codex-approval").value;
  if($("lm-codex-reasoning")) lmCodexReasoning=$("lm-codex-reasoning").value.trim();
  if($("lm-codex-summary")) lmCodexSummary=$("lm-codex-summary").value;
  if($("lm-codex-service-tier")) lmCodexServiceTier=$("lm-codex-service-tier").value.trim();
  if($("lm-codex-writable-roots")) lmCodexWritableRoots=$("lm-codex-writable-roots").value.trim();
  if(persist!==false){
    acPrefSet("acCodexModel", lmCodexModel, "acCodexModel");
    acPrefSet("acCodexSearch", lmCodexSearch, "acCodexSearch");
    acPrefSet("acCodexSandbox", lmCodexSandbox, "acCodexSandbox");
    acPrefSet("acCodexApproval", lmCodexApproval, "acCodexApproval");
    acPrefSet("acCodexReasoning", lmCodexReasoning, "acCodexReasoning");
    acPrefSet("acCodexSummary", lmCodexSummary, "acCodexSummary");
    acPrefSet("acCodexServiceTier", lmCodexServiceTier, "acCodexServiceTier");
    acPrefSet("acCodexWritableRoots", lmCodexWritableRoots, "acCodexWritableRoots");
  }
}
function renderCodexConfig(){
  var box=$("lm-codex-field"); if(!box) return;
  box.style.display=isCodexBackend(lmBackend)?"block":"none";
  if($("lm-codex-model")) $("lm-codex-model").value=lmCodexModel||"";
  if($("lm-codex-search")) $("lm-codex-search").value=lmCodexSearch||"";
  if($("lm-codex-sandbox")) $("lm-codex-sandbox").value=lmCodexSandbox||"";
  if($("lm-codex-approval")) $("lm-codex-approval").value=lmCodexApproval||"";
  if($("lm-codex-reasoning")) $("lm-codex-reasoning").value=lmCodexReasoning||"";
  if($("lm-codex-summary")) $("lm-codex-summary").value=lmCodexSummary||"";
  if($("lm-codex-service-tier")) $("lm-codex-service-tier").value=lmCodexServiceTier||"";
  if($("lm-codex-writable-roots")) $("lm-codex-writable-roots").value=lmCodexWritableRoots||"";
}
function codexStatusFirst(cfg, keys){
  cfg=cfg||{};
  for(var i=0;i<keys.length;i++){
    var v=cfg[keys[i]];
    if(v!=null && v!=="") return v;
  }
  return "";
}
function codexStatusText(r){
  if(!r) return "";
  var cfg=r.config||{}, rows=[
    ["model", ["model"]],
    ["approval", ["approval_policy"]],
    ["sandbox", ["sandbox_mode", "sandbox"]],
    ["search", ["web_search"]],
    ["reasoning", ["model_reasoning_effort", "reasoning_effort"]],
    ["summary", ["model_reasoning_summary", "reasoning_summary"]],
    ["tier", ["service_tier"]]
  ];
  var parts=[];
  rows.forEach(function(row){
    var v=codexStatusFirst(cfg, row[1]);
    if(Array.isArray(v)) v=v.join(", ");
    if(v && typeof v==="object") v=JSON.stringify(v);
    if(v) parts.push(row[0]+"="+v);
  });
  var meta=[];
  if(Array.isArray(r.models)) meta.push("models="+r.models.length);
  if(Array.isArray(r.permission_profiles)) meta.push("permission profiles="+r.permission_profiles.length);
  var body=parts.length?parts.join(" · "):"未返回高频字段";
  return "只读 Codex config/read: "+body+(meta.length?" · "+meta.join(" · "):"");
}
function renderCodexStatus(r){
  var box=$("lm-codex-status"); if(!box) return;
  box.textContent=codexStatusText(r);
}
function loadCodexOptions(){
  if(!isCodexBackend(lmBackend) || !lmDir) return;
  var key=lmDir+"|"+lmBackend; if(lmCodexOptionsKey===key) return; lmCodexOptionsKey=key;
  var hint=$("lm-codex-hint"); if(hint) hint.textContent="正在读取 Codex app-server 可用模型/配置，不影响启动。";
  renderCodexStatus({config:{}, models:[], permission_profiles:[]});
  api("/api/codex_options?dir="+encodeURIComponent(lmDir)).then(function(r){
    if(lmCodexOptionsKey!==key) return;
    var dl=$("lm-codex-model-list"); if(dl){ dl.innerHTML=""; (r.models||[]).forEach(function(m){
      var id=m.id||m.model||""; if(!id) return;
      var opt=document.createElement("option"); opt.value=id; opt.label=m.displayName||m.description||id; dl.appendChild(opt);
    }); }
    if(r.config){
      if(!lmCodexModel && r.config.model) lmCodexModel=r.config.model;
      if(!lmCodexSearch && r.config.web_search) lmCodexSearch=r.config.web_search;
      if(!lmCodexSandbox && r.config.sandbox_mode) lmCodexSandbox=r.config.sandbox_mode;
      if(!lmCodexApproval && r.config.approval_policy) lmCodexApproval=r.config.approval_policy;
      if(!lmCodexReasoning && r.config.model_reasoning_effort) lmCodexReasoning=r.config.model_reasoning_effort;
      if(!lmCodexSummary && r.config.model_reasoning_summary) lmCodexSummary=r.config.model_reasoning_summary;
      if(!lmCodexServiceTier && r.config.service_tier) lmCodexServiceTier=r.config.service_tier;
      renderCodexConfig();
    }
    renderCodexStatus(r);
    if(hint) hint.textContent=r.error ? ("Codex 配置读取部分失败："+r.error) : "这些字段直接透传给 Codex app-server；留空则使用 CODEX_HOME/config.toml。";
  }).catch(function(e){ if(hint) hint.textContent="Codex 配置读取失败："+e; renderCodexStatus(null); });
}
function openLaunchModal(){
  updateLmStart(); renderBackend("lm-backend"); setYolo(lmYolo, false); renderCodexConfig(); loadCodexOptions();
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
["lm-codex-model","lm-codex-search","lm-codex-sandbox","lm-codex-approval","lm-codex-reasoning","lm-codex-summary","lm-codex-service-tier","lm-codex-writable-roots"].forEach(function(id){
  var el=$(id); if(el) el.addEventListener("change", function(){ setCodexConfigFromInputs(); });
  if(el && (id==="lm-codex-model" || id==="lm-codex-reasoning" || id==="lm-codex-service-tier" || id==="lm-codex-writable-roots")) el.addEventListener("input", function(){ setCodexConfigFromInputs(); });
});
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
  lmDir=browseCur; lmTitle=basename(browseCur); $("lm-dir").innerHTML='<i class="ic" data-lucide="folder"></i> '+esc(browseCur); updateLmStart(); loadCodexOptions();
  closeBrowse();
});
