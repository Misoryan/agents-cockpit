"use strict";
document.addEventListener("click", function(){
  document.querySelectorAll(".cactions-pop.open").forEach(function(pop){ pop.classList.remove("open"); });
  document.querySelectorAll(".more-actions.active").forEach(function(btn){ btn.classList.remove("active"); });
});
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
  more.className="cbtn ghost more-actions"; more.type="button"; more.textContent="\u00b7\u00b7\u00b7"; more.title="\u5c55\u5f00\u66f4\u591a\u64cd\u4f5c";
  actions.classList.add("cactions-pop");
  actions.addEventListener("click", function(ev){ ev.stopPropagation(); });
  more.addEventListener("click", function(ev){
    ev.stopPropagation();
    document.querySelectorAll(".cactions-pop.open").forEach(function(pop){
      if(pop!==actions) pop.classList.remove("open");
    });
    document.querySelectorAll(".more-actions.active").forEach(function(btn){
      if(btn!==more) btn.classList.remove("active");
    });
    var rect=more.getBoundingClientRect();
    var open=actions.classList.toggle("open");
    more.classList.toggle("active", open);
    if(open){
      var w=actions.offsetWidth||180, h=actions.offsetHeight||160;
      actions.style.left=Math.max(8, Math.min(rect.right-w, window.innerWidth-w-8))+"px";
      actions.style.top=Math.max(8, Math.min(rect.bottom+6, window.innerHeight-h-8))+"px";
    }
  });
  el.appendChild(more);
  document.body.appendChild(actions);
}
function fillCodexRunActions(actions, s){
  if(!isCodexBackend(s.backend)) return;
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
}
function appendCodexRunActions(el, s){
  if(!isCodexBackend(s.backend)) return;
  var actions=document.createElement("div"); actions.className="cactions";
  fillCodexRunActions(actions, s);
  if(actions.children.length) appendCodexActionMenu(el, actions);
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
function fillCodexHistoryActions(actions, h){
  var be=h.backend||"codex";
  if(!isCodexBackend(be)) return;
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
}
function appendCodexHistoryActions(el, h){
  var be=h.backend||"codex";
  if(!isCodexBackend(be)) return;
  var actions=document.createElement("div"); actions.className="cactions";
  fillCodexHistoryActions(actions, h);
  if(actions.children.length) appendCodexActionMenu(el, actions);
}
