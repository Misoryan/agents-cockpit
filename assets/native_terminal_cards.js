"use strict";

function nPostTerminal(processId, action, input, closeStdin, cols, rows, card){
  var payload={sid:currentSid, process_id:processId, action:action};
  if(input!=null) payload.input=input;
  if(closeStdin) payload.close=true;
  if(cols) payload.cols=cols;
  if(rows) payload.rows=rows;
  postJSON("/api/nterminal", payload).then(function(r){
    if(r && r.error){ alert("终端交互失败: "+r.error); return; }
    if(action==="write" && !closeStdin && card){
      var ta=card.querySelector("textarea"); if(ta) ta.value="";
    }
  }).catch(function(e){ alert("终端交互网络错误: "+(e&&e.message||e)); });
}

function nHandleTerminalInteraction(st, obj){
  var pid=obj.process_id||"", existing=(st.turnCard||st.root).querySelector('.nmsg.terminal[data-pid="'+nEscAttr(pid)+'"]');
  if(existing) existing.remove();
  var term=document.createElement("div");
  term.className="nmsg terminal";
  term.setAttribute("data-pid", pid);
  term.innerHTML='<div class="aq">'+_I('terminal')+' 命令需要终端输入 <span class="tcdesc">'+nEsc(pid)+'</span></div>'+
    (obj.stdin?'<pre>'+nEsc(obj.stdin)+'</pre>':'')+
    '<textarea class="ainp" rows="2" placeholder="输入要发送到 stdin 的内容…"></textarea>'+
    '<div class="abtns"><button class="tsend">发送</button><button class="tclose">发送并关闭 stdin</button><button class="tkill">终止</button></div>';
  var ta=term.querySelector("textarea");
  term.querySelector(".tsend").addEventListener("click", function(){
    var text=ta.value||""; if(text && text.charAt(text.length-1)!=="\n") text+="\n";
    nPostTerminal(pid, "write", text, false, 0, 0, term);
  });
  term.querySelector(".tclose").addEventListener("click", function(){
    var text=ta.value||""; if(text && text.charAt(text.length-1)!=="\n") text+="\n";
    nPostTerminal(pid, "write", text, true, 0, 0, term);
  });
  term.querySelector(".tkill").addEventListener("click", function(){ nPostTerminal(pid, "terminate", "", false, 0, 0, term); });
  (st.turnCard||st.root).appendChild(term);
  nScrollBottom();
}

function nHandleTerminalInputSent(st, obj){
  var sent=(st.turnCard||st.root).querySelector('.nmsg.terminal[data-pid="'+nEscAttr(obj.process_id||"")+'"] textarea');
  if(sent) sent.value="";
}

function nHandleTerminalClosed(st, obj){
  var closed=(st.turnCard||st.root).querySelector('.nmsg.terminal[data-pid="'+nEscAttr(obj.process_id||"")+'"]');
  if(closed) closed.remove();
  nAddRow(st, "sys", _I('terminal')+' 终端交互已'+(obj.terminated?'终止':'关闭'));
}
