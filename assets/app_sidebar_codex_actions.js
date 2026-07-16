"use strict";
function runCodexAction(sid, command, btn, cwd){
  if(!command) return;
  if(btn){ btn.disabled=true; btn.dataset.oldText=btn.textContent; btn.textContent="..."; }
  postJSON("/api/nslash", {sid:sid, command:command}).then(function(r){
    if(r && r.error){ alert("Codex action failed: "+r.error); }
    if(command==="/fork" && r && r.thread_id && typeof openForkedCodexThread==="function"){
      openForkedCodexThread(r.thread_id, "Forked Codex thread", cwd||"");
    }
    pollSessionSignals(); loadSidebarData();
  }).catch(function(e){
    alert("Codex action network error: "+(e&&e.message||e));
  }).finally(function(){
    if(btn){ btn.disabled=false; btn.textContent=btn.dataset.oldText||btn.textContent; }
  });
}
function appendCodexRunActions(el, s){
  if(!isCodexBackend(s.backend)) return;
  var actions=document.createElement("div"); actions.className="cactions";
  [
    {label:"Rename", title:"Rename this Codex thread", build:function(){
      var value=prompt("Thread name", s.title||basename(s.dir)||"");
      return value?("/rename "+value):"";
    }},
    {label:"Goal", title:"Set this Codex thread goal", build:function(){
      var value=prompt("Thread goal", "");
      return value?("/goal set "+value):"";
    }},
    {label:"Fork", title:"Fork this Codex thread", command:"/fork"},
    {label:"Rollback", title:"Rollback one Codex turn", command:"/rollback 1"},
    {label:"Compact", title:"Compact this Codex thread context", command:"/compact"},
    {label:"Archive", title:"Archive this Codex thread in history", command:"/archive"}
  ].forEach(function(action){
    var btn=document.createElement("button");
    btn.className="cbtn ghost"; btn.type="button"; btn.textContent=action.label; btn.title=action.title;
    btn.addEventListener("click", function(ev){
      ev.stopPropagation();
      runCodexAction(s.sid, action.build?action.build():action.command, btn, s.dir);
    });
    actions.appendChild(btn);
  });
  el.appendChild(actions);
}
function runCodexHistoryAction(h, action, btn, extra){
  var be=h.backend||"codex";
  if(btn){ btn.disabled=true; btn.dataset.oldText=btn.textContent; btn.textContent="..."; }
  var payload={
    thread_id:h.thread_id||h.session_id,
    session_id:h.session_id,
    backend:be,
    action:action
  };
  Object.keys(extra||{}).forEach(function(key){ payload[key]=extra[key]; });
  postJSON("/api/codex_history_action", payload).then(function(r){
    if(r && r.error){ alert("Codex history action failed: "+r.error); return; }
    if(action==="fork" && r && r.thread_id && typeof openForkedCodexThread==="function"){
      openForkedCodexThread(r.thread_id, "Forked Codex thread", h.cwd||"");
    }
    loadSidebarData();
  }).catch(function(e){
    alert("Codex history action network error: "+(e&&e.message||e));
  }).finally(function(){
    if(btn){ btn.disabled=false; btn.textContent=btn.dataset.oldText||btn.textContent; }
  });
}
function appendCodexHistoryActions(el, h){
  var be=h.backend||"codex";
  if(!isCodexBackend(be)) return;
  var actions=document.createElement("div"); actions.className="cactions";
  [
    {label:"Rename", title:"Rename this Codex history thread", action:"rename", extra:function(){
      var value=prompt("Thread name", h.title||"");
      return value?{name:value}:null;
    }},
    {label:"Goal", title:"Set this Codex history thread goal", action:"goal_set", extra:function(){
      var value=prompt("Thread goal", "");
      return value?{objective:value}:null;
    }},
    {label:"Fork", title:"Fork this Codex history thread", action:"fork"},
    h.archived
      ? {label:"Unarchive", title:"Unarchive this Codex history thread", action:"unarchive"}
      : {label:"Archive", title:"Archive this Codex history thread", action:"archive"}
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
  el.appendChild(actions);
}
