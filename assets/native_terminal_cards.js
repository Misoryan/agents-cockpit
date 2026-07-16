"use strict";

function nTerminalStatus(card, msg, isError){
  if(!card) return;
  var status=card.querySelector(".terminal-status");
  if(!status) return;
  status.textContent=msg||"";
  status.className="terminal-status"+(isError?" error":"");
}

function nTerminalCardHtml(pid, obj){
  obj=obj||{};
  var prompt=obj.stdin?'<pre class="terminal-prompt">'+nEsc(obj.stdin)+'</pre>':"";
  return '<div class="terminal-head"><div class="terminal-title">'+_I('terminal')+' Command needs terminal input</div><span class="terminal-pid">'+nEsc(pid)+'</span></div>'+prompt+
    '<textarea class="ainp terminal-input" rows="3" placeholder="Type text to send to stdin"></textarea>'+
    '<div class="terminal-size"><label>Cols <input class="tsize-cols" type="number" min="1" value="120"></label><label>Rows <input class="tsize-rows" type="number" min="1" value="40"></label><button class="tresize">Resize</button></div>'+
    '<div class="abtns terminal-actions"><button class="tsend">Send</button><button class="tclose">Send and close stdin</button><button class="tkill">Terminate</button></div>'+
    '<div class="terminal-status" aria-live="polite"></div>';
}

function nPostTerminal(processId, action, input, closeStdin, cols, rows, card){
  var payload={sid:currentSid, process_id:processId, action:action};
  if(input!=null) payload.input=input;
  if(closeStdin) payload.close=true;
  if(cols) payload.cols=cols;
  if(rows) payload.rows=rows;
  nTerminalStatus(card, "Sending " + action + "...", false);
  postJSON("/api/nterminal", payload).then(function(r){
    if(r && r.error){ nTerminalStatus(card, "Terminal interaction failed: "+r.error, true); return; }
    if(action==="write" && !closeStdin && card){
      var ta=card.querySelector("textarea"); if(ta) ta.value="";
      nTerminalStatus(card, "Input sent", false);
    }else if(action==="resize"){
      nTerminalStatus(card, "Resized to "+(r&&r.cols||cols)+"x"+(r&&r.rows||rows), false);
    }else if(action==="terminate"){
      nTerminalStatus(card, "Terminate requested", false);
    }else if(closeStdin){
      nTerminalStatus(card, "stdin close requested", false);
    }
  }).catch(function(e){ nTerminalStatus(card, "Terminal network error: "+(e&&e.message||e), true); });
}

function nHandleTerminalInteraction(st, obj){
  obj=obj||{};
  var pid=obj.process_id||"", existing=(st.turnCard||st.root).querySelector('.nmsg.terminal[data-pid="'+nEscAttr(pid)+'"]');
  if(existing) existing.remove();
  var term=document.createElement("div");
  term.className="nmsg terminal";
  term.setAttribute("data-pid", pid);
  term.innerHTML=nTerminalCardHtml(pid, obj);
  var ta=term.querySelector("textarea");
  term.querySelector(".tsend").addEventListener("click", function(){
    var text=ta.value||""; if(text && text.charAt(text.length-1)!=="\n") text+="\n";
    nPostTerminal(pid, "write", text, false, 0, 0, term);
  });
  term.querySelector(".tclose").addEventListener("click", function(){
    var text=ta.value||""; if(text && text.charAt(text.length-1)!=="\n") text+="\n";
    nPostTerminal(pid, "write", text, true, 0, 0, term);
  });
  term.querySelector(".tresize").addEventListener("click", function(){
    var cols=term.querySelector(".tsize-cols").value||"";
    var rows=term.querySelector(".tsize-rows").value||"";
    nPostTerminal(pid, "resize", null, false, cols, rows, term);
  });
  term.querySelector(".tkill").addEventListener("click", function(){ nPostTerminal(pid, "terminate", null, false, 0, 0, term); });
  (st.turnCard||st.root).appendChild(term);
  nScrollBottom();
}

function nHandleTerminalInputSent(st, obj){
  var card=(st.turnCard||st.root).querySelector('.nmsg.terminal[data-pid="'+nEscAttr(obj.process_id||"")+'"]');
  var sent=card&&card.querySelector("textarea");
  if(sent) sent.value="";
  nTerminalStatus(card, "Input sent", false);
}

function nHandleTerminalClosed(st, obj){
  var closed=(st.turnCard||st.root).querySelector('.nmsg.terminal[data-pid="'+nEscAttr(obj.process_id||"")+'"]');
  if(closed) closed.remove();
  nAddRow(st, "sys", _I('terminal')+' Terminal interaction '+(obj.terminated?'terminated':'closed'));
}
