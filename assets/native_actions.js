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
  {cmd:"/model", fill:"/model ", desc:"\u5207\u6362\u540e\u7eed Codex \u8f6e\u6b21\u4f7f\u7528\u7684\u6a21\u578b"},
  {cmd:"/compact", fill:"/compact", desc:"\u538b\u7f29\u5f53\u524d Codex \u4f1a\u8bdd\u4e0a\u4e0b\u6587"},
  {cmd:"/approval", fill:"/approval on-request", desc:"\u8bbe\u7f6e\u5ba1\u6279\u7b56\u7565\uff1auntrusted / on-request / never"},
  {cmd:"/sandbox", fill:"/sandbox workspace-write", desc:"\u8bbe\u7f6e\u6c99\u7bb1\uff1aread-only / workspace-write / danger-full-access"},
  {cmd:"/search", fill:"/search live", desc:"\u5728 Codex \u7ebf\u7a0b\u5f00\u59cb\u524d\u8bbe\u7f6e\u8054\u7f51\u641c\u7d22"},
  {cmd:"/reasoning", fill:"/reasoning medium", desc:"\u8bbe\u7f6e\u540e\u7eed\u8f6e\u6b21\u7684\u63a8\u7406\u5f3a\u5ea6"},
  {cmd:"/summary", fill:"/summary auto", desc:"\u8bbe\u7f6e\u63a8\u7406\u6458\u8981\uff1aauto / concise / detailed / none"},
  {cmd:"/service-tier", fill:"/service-tier auto", desc:"\u8bbe\u7f6e\u540e\u7eed\u8f6e\u6b21\u7684\u670d\u52a1\u6863\u4f4d"},
  {cmd:"/add-dir", fill:"/add-dir ", desc:"\u6dfb\u52a0 workspace-write \u6c99\u7bb1\u4e0b\u7684\u989d\u5916\u53ef\u5199\u76ee\u5f55"},
  {cmd:"/rename", fill:"/rename ", desc:"\u91cd\u547d\u540d\u5f53\u524d Codex \u4f1a\u8bdd"},
  {cmd:"/archive", fill:"/archive", desc:"\u5c06\u5f53\u524d Codex \u4f1a\u8bdd\u5f52\u6863\u5230\u5386\u53f2"},
  {cmd:"/unarchive", fill:"/unarchive", desc:"\u4ece\u5df2\u5f52\u6863\u5386\u53f2\u4e2d\u6062\u590d\u5f53\u524d\u4f1a\u8bdd"},
  {cmd:"/fork", fill:"/fork", desc:"\u5c06\u5f53\u524d Codex \u4f1a\u8bdd\u5206\u53c9\u4e3a\u65b0\u5386\u53f2"},
  {cmd:"/rollback", fill:"/rollback 1", desc:"\u56de\u6eda\u6700\u8fd1\u4e00\u8f6e Codex \u5bf9\u8bdd"},
  {cmd:"/goal", fill:"/goal get", desc:"\u8bfb\u53d6\u6216\u66f4\u65b0\u4f1a\u8bdd\u76ee\u6807\uff1aget / set / clear / status"},
  {cmd:"/mcp-status", fill:"/mcp-status full", desc:"\u67e5\u770b MCP \u670d\u52a1\u5668\u3001\u6388\u6743\u3001\u5de5\u5177\u548c\u8d44\u6e90"},
  {cmd:"/mcp-resources", fill:"/mcp-resources ", desc:"\u6d4f\u89c8\u67d0\u4e2a MCP \u670d\u52a1\u5668\u7684\u8d44\u6e90\u548c\u5de5\u5177"},
  {cmd:"/mcp-resource", fill:"/mcp-resource ", desc:"\u8bfb\u53d6 MCP \u8d44\u6e90\uff1aserver uri"},
  {cmd:"/mcp-tool", fill:"/mcp-tool ", desc:"\u8c03\u7528 MCP \u5de5\u5177\uff1aserver tool {json}"},
  {cmd:"/skills", fill:"/skills", desc:"\u5217\u51fa\u5f53\u524d\u5de5\u4f5c\u533a\u53ef\u7528\u7684 Codex skills"},
  {cmd:"/plugins", fill:"/plugins", desc:"\u53ea\u8bfb\u5217\u51fa\u5df2\u5b89\u88c5\u7684 Codex \u63d2\u4ef6"},
  {cmd:"/account-status", fill:"/account-status", desc:"\u8bfb\u53d6 Codex \u8d26\u53f7\u3001\u7528\u91cf\u548c\u9650\u989d\u72b6\u6001"},
  {cmd:"/exec", fill:"/exec ", desc:"\u901a\u8fc7 Codex app-server \u6267\u884c\u4e00\u6761\u663e\u5f0f shell \u547d\u4ee4"},
  {cmd:"/exec-stream", fill:"/exec-stream ", desc:"\u6267\u884c\u6d41\u5f0f\u547d\u4ee4\uff0c\u5e76\u63d0\u4f9b\u6d4f\u89c8\u5668 stdin / \u7ec8\u6b62\u63a7\u4ef6"},
  {cmd:"/steer", fill:"/steer ", desc:"\u5411\u6b63\u5728\u8fd0\u884c\u7684 Codex \u8f6e\u6b21\u8ffd\u52a0\u6307\u5f15"}
];
var nativeFileSearchTimer=null, nativeFileSearchToken=0;
var nativeImageAttachments=[];
var NATIVE_IMAGE_MAX_BYTES=8*1024*1024;
var nativeInputAssistTimer=null;
var nativeHeightTimer=null;
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
function nRenderFileMentionMenu(info){
  var s=currentSid?nFindRunSession(currentSid):null;
  if(s && !isCodexBackend(s.backend)){ nCloseSlashMenu(); return false; }
  info=info||nMentionInfo(); if(!info || !currentSid || info.query.length<1){ nCloseSlashMenu(); return false; }
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
  var inp=$("nativeinput"); if(!inp) return;
  var value=inp.value||"";
  if(value.trim().charAt(0)==="/"){ nRenderSlashMenu(); return; }
  var info=nMentionInfo();
  if(info && info.query.length>=1){ nRenderFileMentionMenu(info); return; }
  var m=nSlashMenu();
  if(m && m.classList.contains("open")) nCloseSlashMenu();
}
function nLooksLikeAssistInput(value){
  value=String(value||"");
  if(value.trim().charAt(0)==="/") return true;
  return /(^|\s)@(?:"[^"]*|[^\s@"]*)$/.test(value);
}
function nScheduleInputAssist(inp){
  if(!inp) return;
  var value=inp.value||"";
  if(nativeInputAssistTimer){ clearTimeout(nativeInputAssistTimer); nativeInputAssistTimer=null; }
  if(nativeHeightTimer){ clearTimeout(nativeHeightTimer); nativeHeightTimer=null; }
  if(nLooksLikeAssistInput(value)){
    nativeInputAssistTimer=setTimeout(function(){ nativeInputAssistTimer=null; nRenderInputAssist(); }, 60);
  }else{
    var m=nSlashMenu();
    if(m && m.classList.contains("open")) nCloseSlashMenu();
  }
  if(value.indexOf("\n")>=0 || value.length>160 || inp.offsetHeight>70){
    nativeHeightTimer=setTimeout(function(){
      nativeHeightTimer=null;
      inp.style.height="auto";
      inp.style.height=Math.min(inp.scrollHeight,200)+"px";
    }, 120);
  }
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
    chip.innerHTML='<img alt="" src="'+nEscAttr(img.data_url||"")+'"><span title="'+nEscAttr(img.name||"\u56fe\u7247")+'">'+nEsc(img.name||"\u56fe\u7247")+'</span><button type="button" title="\u79fb\u9664">&times;</button>';
    chip.querySelector("button").addEventListener("click", function(){
      nativeImageAttachments.splice(idx,1); nRenderAttachments();
    });
    host.appendChild(chip);
  });
  host.classList.add("open");
}
function nAddImageFile(file){
  if(!file || !/^image\//.test(file.type||"")) return;
  if(!nCurrentCodexSession()){ alert("\u53ea有 Codex 会话支持图片输入。"); return; }
  if(file.size>NATIVE_IMAGE_MAX_BYTES){ alert("\u56fe片过大，最多 8 MB。"); return; }
  var reader=new FileReader();
  reader.onload=function(){
    nativeImageAttachments.push({
      name:file.name||"\u56fe\u7247",
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

var slashHelp=$("nativeslashhelp");
if(slashHelp) slashHelp.addEventListener("click", function(){
  var inp=$("nativeinput"); if(!inp) return;
  if((inp.value||"").trim().charAt(0)!=="/") inp.value="/";
  inp.focus();
  nRenderSlashMenu();
});

$("nativeattach").addEventListener("click", function(){
  if(!currentSid) return;
  if(!nCurrentCodexSession()){ alert("\u53ea有 Codex 会话支持图片输入。"); return; }
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
$("nativeinput").addEventListener("input", function(){ nScheduleInputAssist(this); });
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
$("nativemsgs").addEventListener("click", function(e){
  var btn=e.target && e.target.closest ? e.target.closest(".mcp-action") : null;
  if(!btn) return;
  var command=btn.dataset ? (btn.dataset.mcpCommand||"") : "";
  if(!command || !currentSid) return;
  e.preventDefault();
  nativeSlashCommand(command, nativeStage(currentSid));
});
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
    title: title||"\u5206\u53c9\u7684 Codex \u4f1a\u8bdd",
    backend: "codex_native"
  });
}
