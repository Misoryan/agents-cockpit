"use strict";
var _nGenerating=false;
function nSetGen(on){
  if(_nGenerating===on) return;
  _nGenerating=on;
  var sb=$("nativesubmit"); if(!sb) return;
  sb.innerHTML = on ? _I('square') : _I('arrow-up');
  sb.title = on ? "停止生成" : "发送 (Enter)";
}
function nInterrupt(){
  if(!currentSid) return;
  postJSON("/api/ninterrupt",{sid:currentSid}).then(function(){}).catch(function(){});
}
var nativeSlashCommands=[
  {cmd:"/model", fill:"/model ", desc:"Set model for subsequent Codex turns"},
  {cmd:"/compact", fill:"/compact", desc:"Compact this Codex thread context"},
  {cmd:"/approval", fill:"/approval on-request", desc:"Set approval policy: untrusted, on-request, never"},
  {cmd:"/sandbox", fill:"/sandbox workspace-write", desc:"Set sandbox: read-only, workspace-write, danger-full-access"},
  {cmd:"/search", fill:"/search live", desc:"Set web search before the Codex thread starts"},
  {cmd:"/rename", fill:"/rename ", desc:"Rename this Codex thread"},
  {cmd:"/archive", fill:"/archive", desc:"Archive this Codex thread in history"},
  {cmd:"/unarchive", fill:"/unarchive", desc:"Restore this Codex thread from archived history"},
  {cmd:"/fork", fill:"/fork", desc:"Fork this Codex thread into a new history entry"},
  {cmd:"/rollback", fill:"/rollback 1", desc:"Drop the latest Codex turn from this thread"},
  {cmd:"/goal", fill:"/goal get", desc:"Read or update the thread goal: get, set, clear, status"},
  {cmd:"/mcp-resource", fill:"/mcp-resource ", desc:"Read an MCP resource: server uri"},
  {cmd:"/mcp-tool", fill:"/mcp-tool ", desc:"Call an MCP tool: server tool {json}"},
  {cmd:"/steer", fill:"/steer ", desc:"Send guidance to the currently running Codex turn"}
];
var nativeFileSearchTimer=null, nativeFileSearchToken=0;
var nativeImageAttachments=[];
var NATIVE_IMAGE_MAX_BYTES=8*1024*1024;
function nSlashMenu(){ return $("slashmenu"); }
function nCloseSlashMenu(){
  var m=nSlashMenu(); if(m) m.classList.remove("open");
  nativeFileSearchToken+=1;
  if(nativeFileSearchTimer){ clearTimeout(nativeFileSearchTimer); nativeFileSearchTimer=null; }
}
function nSlashItems(){ var m=nSlashMenu(); return m?Array.prototype.slice.call(m.querySelectorAll(".slashitem")):[]; }
function nSlashMove(delta){
  var items=nSlashItems(); if(!items.length) return false;
  var idx=items.findIndex(function(x){ return x.classList.contains("active"); });
  if(idx<0) idx=0;
  items[idx].classList.remove("active");
  idx=(idx+delta+items.length)%items.length;
  items[idx].classList.add("active");
  items[idx].scrollIntoView({block:"nearest"});
  return true;
}
function nSlashPickActive(){
  var items=nSlashItems(), active=items.find(function(x){ return x.classList.contains("active"); })||items[0];
  if(active){ active.click(); return true; }
  return false;
}
function nRenderSlashMenu(){
  var inp=$("nativeinput"), m=nSlashMenu(); if(!inp||!m) return false;
  var s=currentSid?nFindRunSession(currentSid):null;
  if(s && !isCodexBackend(s.backend)){ nCloseSlashMenu(); return false; }
  var q=inp.value.trim().toLowerCase();
  if(q.charAt(0)!=="/" || q.indexOf("\n")>=0){ return false; }
  var items=nativeSlashCommands.filter(function(it){ return it.cmd.indexOf(q.split(/\s+/,1)[0])===0 || it.fill.indexOf(q)===0; });
  if(!items.length){ nCloseSlashMenu(); return false; }
  m.innerHTML="";
  items.forEach(function(it, idx){
    var b=document.createElement("button");
    b.type="button"; b.className="slashitem"+(idx===0?" active":"");
    b.innerHTML='<span class="slashcmd">'+nEsc(it.fill)+'</span><span class="slashdesc">'+nEsc(it.desc)+'</span>';
    b.addEventListener("click", function(){
      inp.value=it.fill; inp.focus(); inp.style.height="auto"; inp.style.height=Math.min(inp.scrollHeight,200)+"px";
      nCloseSlashMenu();
      if(it.fill.charAt(it.fill.length-1)!==" "){ nativeSend(); }
    });
    m.appendChild(b);
  });
  m.classList.add("open");
  return true;
}
function nMentionInfo(){
  var inp=$("nativeinput"); if(!inp) return null;
  var val=inp.value||"", pos=typeof inp.selectionStart==="number"?inp.selectionStart:val.length;
  var left=val.slice(0,pos), m=left.match(/(^|\s)@(?:"([^"]*)|([^\s@"]*))$/);
  if(!m) return null;
  var token=m[0].slice(m[1].length);
  return {start:pos-token.length, end:pos, query:(m[2]!=null?m[2]:m[3]||"")};
}
function nMentionLiteral(path){
  path=String(path||"").replace(/"/g,"");
  return /\s/.test(path)?'@"'+path+'"':"@"+path;
}
function nInsertMention(path){
  var inp=$("nativeinput"), info=nMentionInfo(); if(!inp||!info) return;
  var val=inp.value||"", literal=nMentionLiteral(path);
  inp.value=val.slice(0, info.start)+literal+" "+val.slice(info.end);
  var pos=info.start+literal.length+1;
  inp.focus(); inp.setSelectionRange(pos,pos);
  inp.style.height="auto"; inp.style.height=Math.min(inp.scrollHeight,200)+"px";
  nCloseSlashMenu();
}
function nRenderMentionResults(files, token){
  if(token!==nativeFileSearchToken) return;
  var inp=$("nativeinput"), m=nSlashMenu(); if(!inp||!m) return;
  if(!nMentionInfo() || !files || !files.length){ nCloseSlashMenu(); return; }
  m.innerHTML="";
  files.forEach(function(file, idx){
    var b=document.createElement("button");
    b.type="button"; b.className="slashitem"+(idx===0?" active":"");
    var kind=(file.match_type==="directory")?"dir":"file";
    b.innerHTML='<span class="slashcmd">@'+nEsc(file.name||file.insert||"")+'</span><span class="slashdesc">'+nEsc(kind+" · "+(file.insert||file.path||""))+'</span>';
    b.addEventListener("click", function(){ nInsertMention(file.insert||file.path||""); });
    m.appendChild(b);
  });
  m.classList.add("open");
}
function nRenderFileMentionMenu(){
  var s=currentSid?nFindRunSession(currentSid):null;
  if(s && !isCodexBackend(s.backend)){ nCloseSlashMenu(); return false; }
  var info=nMentionInfo(); if(!info || !currentSid || info.query.length<1){ nCloseSlashMenu(); return false; }
  var token=++nativeFileSearchToken;
  if(nativeFileSearchTimer){ clearTimeout(nativeFileSearchTimer); }
  nativeFileSearchTimer=setTimeout(function(){
    api("/api/nfiles?sid="+encodeURIComponent(currentSid)+"&q="+encodeURIComponent(info.query)+"&limit=12").then(function(r){
      if(token!==nativeFileSearchToken) return;
      if(!r || r.error){ nCloseSlashMenu(); return; }
      nRenderMentionResults(r.files||[], token);
    }).catch(function(){ if(token===nativeFileSearchToken) nCloseSlashMenu(); });
  }, 160);
  return true;
}
function nRenderInputAssist(){
  if(nRenderSlashMenu()) return;
  nRenderFileMentionMenu();
}
function nCurrentCodexSession(){
  var s=currentSid?nFindRunSession(currentSid):null;
  return !!(s && isCodexBackend(s.backend));
}
function nRenderAttachments(){
  var host=$("nattachpreview"); if(!host) return;
  host.innerHTML="";
  if(!nativeImageAttachments.length){ host.classList.remove("open"); return; }
  nativeImageAttachments.forEach(function(img, idx){
    var chip=document.createElement("div"); chip.className="nattach-chip";
    chip.innerHTML='<img alt="" src="'+nEscAttr(img.data_url||"")+'"><span title="'+nEscAttr(img.name||"image")+'">'+nEsc(img.name||"image")+'</span><button type="button" title="Remove">&times;</button>';
    chip.querySelector("button").addEventListener("click", function(){
      nativeImageAttachments.splice(idx,1); nRenderAttachments();
    });
    host.appendChild(chip);
  });
  host.classList.add("open");
}
function nAddImageFile(file){
  if(!file || !/^image\//.test(file.type||"")) return;
  if(!nCurrentCodexSession()){ alert("Image input is only supported for Codex sessions."); return; }
  if(file.size>NATIVE_IMAGE_MAX_BYTES){ alert("Image is too large; max 8 MB."); return; }
  var reader=new FileReader();
  reader.onload=function(){
    nativeImageAttachments.push({
      name:file.name||"image",
      type:file.type||"image/png",
      size:file.size||0,
      data_url:String(reader.result||""),
      detail:"auto"
    });
    nRenderAttachments();
  };
  reader.readAsDataURL(file);
}
function nAddImageFiles(files){
  Array.prototype.slice.call(files||[]).forEach(nAddImageFile);
}
function nImageBlocksForDisplay(images){
  return (images||[]).map(function(img){
    return {type:"image", url:img.data_url, name:img.name, mime:img.type, size:img.size};
  });
}
function nClearAttachments(){
  nativeImageAttachments=[]; nRenderAttachments();
  var f=$("nativeimagefile"); if(f) f.value="";
}
function nativeSlashCommand(command, st){
  postJSON("/api/nslash", {sid:currentSid, command:command}).then(function(r){
    if(r && r.error){ nAddRow(st, "sys", "\u26a0\ufe0f Slash \u547d\u4ee4\u5931\u8d25: "+nEsc(r.error)); }
  }).catch(function(e){ nAddRow(st, "sys", "\u26a0\ufe0f Slash \u547d\u4ee4\u7f51\u7edc\u9519\u8bef: "+nEsc(e&&e.message||e)); });
}
function nativeSend(){
  var inp=$("nativeinput"), p=inp.value.trim(), images=nativeImageAttachments.slice();
  if((!p && !images.length) || !currentSid) return;
  var st=nativeStage(currentSid); if(!st) return;
  if(p.charAt(0)==="/" && !images.length){
    inp.value=""; inp.style.height="auto";
    nCloseSlashMenu();
    nativeSlashCommand(p, st);
    return;
  }
  nCloseSlashMenu();
  var _w=nativeWs[currentSid];
  if(!_w||_w.readyState>1){ nativeConnect(currentSid); }
  var display=[];
  if(p) display.push({type:"text", text:p});
  display=display.concat(nImageBlocksForDisplay(images));
  nHandle(currentSid, {type:"user", message:{role:"user", content:display}});
  nStartThinking(st);
  inp.value=""; inp.style.height="auto";
  nClearAttachments();
  nSetGen(true);
  postJSON("/api/nsend", {sid:currentSid, prompt:p, images:images, plan:!!st.planMode, task:!!st.taskMode}).then(function(r){
    if(r && r.error){ nFinalizeThinking(st); nStopThinking(st); nAddRow(st, "sys", "\u26a0\ufe0f \u53d1\u9001\u5931\u8d25: "+nEsc(r.error)+"\uff08\u82e5\u521a\u66f4\u65b0\u4ee3\u7801,\u8bf7\u300c\u8bbe\u7f6e \u2192 \u91cd\u542f\u540e\u7aef\u5c42\u300d\u52a0\u8f7d native.py \u540e\u5237\u65b0\u9875\u9762\uff09"); nEndTurn(st); nSetGen(false); }
  }).catch(function(e){ nFinalizeThinking(st); nStopThinking(st); nAddRow(st, "sys", "\u26a0\ufe0f \u7f51\u7edc\u9519\u8bef: "+nEsc(e&&e.message||e)); nEndTurn(st); nSetGen(false); });
}

$("nativeback").addEventListener("click", hideNative);
$("nativesend").addEventListener("submit", function(e){
  e.preventDefault();
  var p=($("nativeinput").value||"").trim().toLowerCase();
  if(_nGenerating && p.indexOf("/steer ")!==0 && p!=="/steer"){ nInterrupt(); }
  else{ nativeSend(); }
});
/* 计划/任务模式开关:点击翻转 stage 状态 + 即时同步 UI + 推后端(/api/nmode 广播 mode_state 回环确认)。
   plan/task 两键独立,可同时开(先计划后任务跟踪)。持久化进 localStorage,跨刷新保留。 */
function nToggleMode(which){
  if(!currentSid) return;
  var st=nativeStage(currentSid); if(!st) return;
  var key = which==="plan"?"planMode":"taskMode";
  st[key]=!st[key];
  if(which==="plan"){ localStorage.setItem("acPlan_"+currentSid, st.planMode?"1":"0"); }
  else { localStorage.setItem("acTask_"+currentSid, st.taskMode?"1":"0"); }
  nSyncModes(st);
  var payload={sid:currentSid}; payload[which]=st[key];
  postJSON("/api/nmode", payload);
}
$("nmode-plan").addEventListener("click", function(){ nToggleMode("plan"); });
$("nmode-task").addEventListener("click", function(){ nToggleMode("task"); });
$("nativeattach").addEventListener("click", function(){
  if(!currentSid) return;
  if(!nCurrentCodexSession()){ alert("Image input is only supported for Codex sessions."); return; }
  $("nativeimagefile").click();
});
$("nativeimagefile").addEventListener("change", function(){ nAddImageFiles(this.files); });
$("nativeinput").addEventListener("keydown", function(e){
  if(e.key==="Escape"){ nCloseSlashMenu(); return; }
  if(nSlashMenu() && nSlashMenu().classList.contains("open") && (e.key==="ArrowDown" || e.key==="ArrowUp")){
    e.preventDefault(); nSlashMove(e.key==="ArrowDown"?1:-1); return;
  }
  if(e.key==="Tab" && nSlashMenu() && nSlashMenu().classList.contains("open")){
    if(nSlashPickActive()){ e.preventDefault(); return; }
  }
  if(e.key==="Enter" && !e.shiftKey){
    e.preventDefault();
    var p=($("nativeinput").value||"").trim().toLowerCase();
    if(_nGenerating && p.indexOf("/steer ")!==0 && p!=="/steer"){ nInterrupt(); }
    else{ nativeSend(); }
  }
});
$("nativeinput").addEventListener("input", function(){ this.style.height="auto"; this.style.height=Math.min(this.scrollHeight,200)+"px"; nRenderInputAssist(); });
$("nativeinput").addEventListener("paste", function(e){
  var items=(e.clipboardData&&e.clipboardData.items)||[], files=[];
  for(var i=0;i<items.length;i+=1){
    if(items[i].kind==="file" && /^image\//.test(items[i].type||"")){
      var f=items[i].getAsFile(); if(f) files.push(f);
    }
  }
  if(files.length){ e.preventDefault(); nAddImageFiles(files); }
});
$("nativemsgs").addEventListener("scroll", nUpdateScrollButton);
$("scrollbottom").addEventListener("click", nJumpBottom);
document.addEventListener("keydown", function(e){
  if(e.ctrlKey && e.key==="Tab"){ e.preventDefault(); switchTab(e.shiftKey?-1:1); }
});
function openSessionBySid(sid, skipFetch){
  if(!sid) return false;
  var i, s; for(i=0;i<runSessions.length;i+=1){ if(runSessions[i].sid===sid){ s=runSessions[i]; break; } }
  if(s){
    showNativeSession(s.sid, s.title||basename(s.dir));
    return true;
  }
  if(!skipFetch){ api("/api/sessions").then(function(r){ rememberSessions(r.sessions||[], true); openSessionBySid(sid, true); }); }
  return false;
}
function openForkedCodexThread(threadId, title, cwd){
  if(!threadId) return;
  resumeHist({
    session_id: threadId,
    thread_id: threadId,
    cwd: cwd||"",
    title: title||"Forked Codex thread",
    backend: "codex_native"
  });
}
