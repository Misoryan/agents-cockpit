"use strict";
function runCodexAction(sid, command, btn, cwd){
  if(!command) return;
  if(btn){ btn.disabled=true; btn.dataset.oldText=btn.textContent; btn.textContent="\u5904\u7406\u4e2d"; }
  postJSON("/api/nslash", {sid:sid, command:command}).then(function(r){
    if(r && r.error){ alert("Codex \u64cd\u4f5c\u5931\u8d25\uff1a"+r.error); }
    if(command==="/fork" && r && r.thread_id && typeof openForkedCodexThread==="function"){
      openForkedCodexThread(r.thread_id, "\u5206\u53c9\u7684 Codex \u4f1a\u8bdd", cwd||"");
    }
    pollSessionSignals(); loadSidebarData();
  }).catch(function(e){
    alert("Codex \u64cd\u4f5c\u7f51\u7edc\u9519\u8bef\uff1a"+(e&&e.message||e));
  }).finally(function(){
    if(btn){ btn.disabled=false; btn.textContent=btn.dataset.oldText||btn.textContent; }
  });
}
function appendCodexActionMenu(el, actions){
  var more=document.createElement("button");
  more.className="cbtn ghost more-actions"; more.type="button"; more.textContent="\u66f4\u591a"; more.title="\u5c55\u5f00\u66f4\u591a Codex \u64cd\u4f5c";
  actions.classList.add("collapsed");
  more.addEventListener("click", function(ev){
    ev.stopPropagation();
    var open=actions.classList.toggle("open");
    more.textContent=open?"\u6536\u8d77":"\u66f4\u591a";
    more.title=open?"\u6536\u8d77 Codex \u64cd\u4f5c":"\u5c55\u5f00\u66f4\u591a Codex \u64cd\u4f5c";
  });
  el.appendChild(more);
  el.appendChild(actions);
}
function appendCodexRunActions(el, s){
  if(!isCodexBackend(s.backend)) return;
  var actions=document.createElement("div"); actions.className="cactions";
  [
    {label:"\u91cd\u547d\u540d", title:"\u91cd\u547d\u540d\u6b64 Codex \u4f1a\u8bdd", build:function(){
      var value=prompt("\u4f1a\u8bdd\u540d\u79f0", s.title||basename(s.dir)||"");
      return value?("/rename "+value):"";
    }},
    {label:"\u76ee\u6807", title:"\u8bbe\u7f6e\u6b64 Codex \u4f1a\u8bdd\u76ee\u6807", build:function(){
      var value=prompt("\u4f1a\u8bdd\u76ee\u6807", "");
      return value?("/goal set "+value):"";
    }},
    {label:"\u5206\u53c9", title:"\u5206\u53c9\u6b64 Codex \u4f1a\u8bdd", command:"/fork"},
    {label:"\u56de\u6eda", title:"\u56de\u6eda\u4e00\u8f6e Codex \u5bf9\u8bdd", command:"/rollback 1"},
    {label:"\u538b\u7f29", title:"\u538b\u7f29\u6b64 Codex \u4f1a\u8bdd\u4e0a\u4e0b\u6587", command:"/compact"},
    {label:"\u5f52\u6863", title:"\u5c06\u6b64 Codex \u4f1a\u8bdd\u5f52\u6863\u5230\u5386\u53f2", command:"/archive"}
  ].forEach(function(action){
    var btn=document.createElement("button");
    btn.className="cbtn ghost"; btn.type="button"; btn.textContent=action.label; btn.title=action.title;
    btn.addEventListener("click", function(ev){
      ev.stopPropagation();
      runCodexAction(s.sid, action.build?action.build():action.command, btn, s.dir);
    });
    actions.appendChild(btn);
  });
  appendCodexActionMenu(el, actions);
}
function runCodexHistoryAction(h, action, btn, extra){
  var be=h.backend||"codex";
  if(btn){ btn.disabled=true; btn.dataset.oldText=btn.textContent; btn.textContent="\u5904\u7406\u4e2d"; }
  var payload={
    thread_id:h.thread_id||h.session_id,
    session_id:h.session_id,
    backend:be,
    action:action
  };
  Object.keys(extra||{}).forEach(function(key){ payload[key]=extra[key]; });
  postJSON("/api/codex_history_action", payload).then(function(r){
    if(r && r.error){ alert("Codex \u5386\u53f2\u64cd\u4f5c\u5931\u8d25\uff1a"+r.error); return; }
    if(action==="fork" && r && r.thread_id && typeof openForkedCodexThread==="function"){
      openForkedCodexThread(r.thread_id, "\u5206\u53c9\u7684 Codex \u4f1a\u8bdd", h.cwd||"");
    }
    loadSidebarData();
  }).catch(function(e){
    alert("Codex \u5386\u53f2\u64cd\u4f5c\u7f51\u7edc\u9519\u8bef\uff1a"+(e&&e.message||e));
  }).finally(function(){
    if(btn){ btn.disabled=false; btn.textContent=btn.dataset.oldText||btn.textContent; }
  });
}
function appendCodexHistoryActions(el, h){
  var be=h.backend||"codex";
  if(!isCodexBackend(be)) return;
  var actions=document.createElement("div"); actions.className="cactions";
  [
    {label:"\u91cd\u547d\u540d", title:"\u91cd\u547d\u540d\u6b64 Codex \u5386\u53f2\u4f1a\u8bdd", action:"rename", extra:function(){
      var value=prompt("\u4f1a\u8bdd\u540d\u79f0", h.title||"");
      return value?{name:value}:null;
    }},
    {label:"\u76ee\u6807", title:"\u8bbe\u7f6e\u6b64 Codex \u5386\u53f2\u4f1a\u8bdd\u76ee\u6807", action:"goal_set", extra:function(){
      var value=prompt("\u4f1a\u8bdd\u76ee\u6807", "");
      return value?{objective:value}:null;
    }},
    {label:"\u5206\u53c9", title:"\u5206\u53c9\u6b64 Codex \u5386\u53f2\u4f1a\u8bdd", action:"fork"},
    h.archived
      ? {label:"\u53d6\u6d88\u5f52\u6863", title:"\u4ece\u5f52\u6863\u4e2d\u6062\u590d\u6b64 Codex \u5386\u53f2\u4f1a\u8bdd", action:"unarchive"}
      : {label:"\u5f52\u6863", title:"\u5f52\u6863\u6b64 Codex \u5386\u53f2\u4f1a\u8bdd", action:"archive"}
  ].forEach(function(action){
    var btn=document.createElement("button");
    btn.className="cbtn ghost"; btn.type="button"; btn.textContent=action.label; btn.title=action.title;
    btn.addEventListener("click", function(ev){
      ev.stopPropagation();
      var extra=action.extra?action.extra():{};
      if(extra===null) return;
      runCodexHistoryAction(h, action.action, btn, extra);
    });
    actions.appendChild(btn);
  });
  appendCodexActionMenu(el, actions);
}
