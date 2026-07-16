"use strict";
function nAddHumanRow(st, text){
  text=String(text==null?"":text).trim();
  if(!text) return;
  if(st.lastWasHumanUser && st.lastHumanText===text) return;
  nAddRow(st,"user",nEsc(text));
  st.lastWasHumanUser=true; st.lastHumanText=text;
}
function nAskQuestions(obj){
  var qs=Array.isArray(obj.questions)?obj.questions:[];
  return qs.filter(function(q){ return q && (q.question || q.header || q.id); });
}
function nFindAskItem(card, qid){
  var items=card.querySelectorAll('.qitem');
  for(var i=0;i<items.length;i++){ if(items[i].dataset.qid===qid) return items[i]; }
  return null;
}
function nSubmitAsk(sid, obj, card){
  var qs=nAskQuestions(obj), payload={sid:sid,tool_use_id:obj.tool_use_id};
  if(qs.length){
    var answers={}, fallback=[];
    qs.forEach(function(q,idx){
      var qid=q.id||String(idx), wrap=nFindAskItem(card, qid);
      var vals=[], sels=wrap.querySelectorAll('.qopt.selected');
      sels.forEach(function(sel){ if(sel.dataset.value){ vals.push(sel.dataset.value); } });
      var free=wrap&&wrap.querySelector('.ainp');
      if(!vals.length && free && free.value.trim()){ vals.push(free.value.trim()); }
      if(vals.length){ answers[qid]=vals; fallback.push(vals.join(", ")); }
    });
    payload.answers=answers; payload.answer=fallback.join("\n");
  }else{
    var ta=card.querySelector('.ainp');
    payload.answer=ta?ta.value:"";
  }
  postJSON("/api/nanswer",payload);
  card.remove();
}
function nRenderAsk(sid, st, obj){
  var old=(st.turnCard||st.root).querySelector('.nmsg.ask[data-tuid="'+obj.tool_use_id+'"]');
  if(old) old.remove();
  var acard=document.createElement("div"); acard.className="nmsg ask"; acard.dataset.tuid=obj.tool_use_id;
  var qs=nAskQuestions(obj);
  if(qs.length){
    acard.innerHTML='<div class="aq">'+_I('help-circle')+' '+nEsc(obj.question||"需要你选择")+'</div>';
    qs.forEach(function(q,idx){
      var qid=q.id||String(idx), opts=Array.isArray(q.options)?q.options:[];
      var item=document.createElement("div"); item.className="qitem"; item.dataset.qid=qid;
      var html='';
      if(q.header){ html+='<div class="qhead">'+nEsc(q.header)+'</div>'; }
      html+='<div class="qtext">'+nEsc(q.question||q.header||"")+'</div>';
      if(opts.length){
        html+='<div class="qopts">'+opts.map(function(o){
          var lab=(o&&o.label)||String(o||""), desc=(o&&o.description)||"";
          return '<button type="button" class="qopt" data-value="'+nEscAttr(lab)+'"><span class="qlabel">'+nEsc(lab)+'</span>'+(desc?'<span class="qdesc">'+nEsc(desc)+'</span>':'')+'</button>';
        }).join("")+'</div>';
      }
      html+='<textarea class="ainp qfree" rows="2" placeholder="其他 / 补充回答"></textarea>';
      item.innerHTML=html; acard.appendChild(item);
    });
    var btns=document.createElement("div"); btns.className="abtns"; btns.innerHTML='<button class="asend">回答</button>'; acard.appendChild(btns);
    var _qmap={}; qs.forEach(function(q,idx){ _qmap[q.id||String(idx)]=q; });
    acard.querySelectorAll('.qopt').forEach(function(btn){
      btn.addEventListener("click", function(){
        var wrap=btn.closest('.qitem');
        var _q=_qmap[wrap.dataset.qid]||{};
        if(_q.multiSelect){
          btn.classList.toggle("selected");
        }else{
          wrap.querySelectorAll('.qopt').forEach(function(x){ x.classList.toggle("selected", x===btn); });
          var free=wrap.querySelector('.ainp'); if(free) free.value="";
          if(qs.length===1) nSubmitAsk(sid,obj,acard);
        }
      });
    });
    acard.querySelector(".asend").addEventListener("click", function(){ nSubmitAsk(sid,obj,acard); });
  }else{
    acard.innerHTML='<div class="aq">'+_I('help-circle')+' '+nEsc(obj.question)+'</div><textarea class="ainp" rows="2" placeholder="回答…(Ctrl+Enter 发送)"></textarea><div class="abtns"><button class="asend">回答</button></div>';
    acard.querySelector('.asend').addEventListener("click", function(){ nSubmitAsk(sid,obj,acard); });
  }
  var ta=acard.querySelector('.ainp');
  if(ta){ ta.addEventListener("keydown", function(e){ if(e.key==="Enter" && (e.ctrlKey||e.metaKey)){ nSubmitAsk(sid,obj,acard); } }); }
  nTurnCard(st).appendChild(acard); st.curTxt=null; st.lastWasHumanUser=false; nScrollBottom();
  setTimeout(function(){ var first=acard.querySelector('.qopt,.ainp'); if(first) first.focus({preventScroll:true}); }, 50);
}
function nFormFieldHtml(f){
  f=f||{}; var fid=String(f.id||""), typ=String(f.type||"text"), req=!!f.required;
  var def=f.default==null?"":String(f.default), opts=Array.isArray(f.options)?f.options:[];
  var html='<div class="fitem" data-fid="'+nEscAttr(fid)+'" data-ftype="'+nEscAttr(typ)+'" data-required="'+(req?"1":"0")+'">';
  html+='<label>'+nEsc(f.label||fid||"字段")+(req?' <span class="req">*</span>':'')+'</label>';
  if(f.description){ html+='<div class="fdesc">'+nEsc(f.description)+'</div>'; }
  if(typ==="textarea"){
    html+='<textarea class="finp" rows="3">'+nEsc(def)+'</textarea>';
  }else if(typ==="number"){
    html+='<input class="finp" type="number" value="'+nEscAttr(def)+'">';
  }else if(typ==="checkbox"){
    var checked=(f.default===true||String(f.default).toLowerCase()==="true")?' checked':'';
    html+='<label class="fcheck"><input class="finp" type="checkbox"'+checked+'> 是</label>';
  }else if(typ==="select"){
    html+='<select class="finp">'+(req?'':'<option value=""></option>');
    opts.forEach(function(o){
      var val=String((o&&o.value)!=null?o.value:""), lab=String((o&&o.label)!=null?o.label:val);
      html+='<option value="'+nEscAttr(val)+'"'+(val===def?' selected':'')+'>'+nEsc(lab)+'</option>';
    });
    html+='</select>';
  }else if(typ==="multiselect"){
    html+='<div class="fopts">';
    opts.forEach(function(o){
      var val=String((o&&o.value)!=null?o.value:""), lab=String((o&&o.label)!=null?o.label:val);
      html+='<label class="fcheck"><input type="checkbox" value="'+nEscAttr(val)+'"> '+nEsc(lab)+'</label>';
    });
    html+='</div>';
  }else{
    html+='<input class="finp" type="text" value="'+nEscAttr(def)+'">';
  }
  html+='</div>';
  return html;
}
function nSubmitForm(sid, obj, card, action){
  var payload={sid:sid, tool_use_id:obj.tool_use_id, answers:{action:action, content:null}};
  if(action==="accept"){
    var content={}, err="";
    var raw=card.querySelector(".fjson");
    if(raw){
      var txt=raw.value.trim();
      if(txt){ try{ content=JSON.parse(txt); }catch(e){ err="JSON 格式不正确: "+(e&&e.message||e); } }
    }else{
      card.querySelectorAll(".fitem").forEach(function(item){
        if(err) return;
        var fid=item.dataset.fid||"", typ=item.dataset.ftype||"text", req=item.dataset.required==="1";
        var val="";
        if(typ==="checkbox"){
          var cb=item.querySelector('input[type="checkbox"]'); val=!!(cb&&cb.checked);
        }else if(typ==="multiselect"){
          val=[]; item.querySelectorAll('input[type="checkbox"]').forEach(function(cb){ if(cb.checked) val.push(cb.value); });
        }else if(typ==="number"){
          var inp=item.querySelector(".finp"); var rawv=inp?inp.value.trim():"";
          val=rawv===""?"":Number(rawv);
          if(rawv!=="" && !isFinite(val)){ err=(fid||"数字字段")+" 不是有效数字"; }
        }else{
          var el=item.querySelector(".finp"); val=el?el.value.trim():"";
        }
        var missing=(Array.isArray(val)?val.length===0:val===""||val==null);
        if(req && missing){ err=(item.querySelector("label")||{}).textContent+" 必填"; return; }
        if(fid && !missing) content[fid]=val;
      });
    }
    var ferr=card.querySelector(".ferr");
    if(err){ if(ferr) ferr.textContent=err; return; }
    payload.answers.content=content;
  }
  postJSON("/api/nanswer",payload);
  card.remove();
}
function nRenderForm(sid, st, obj){
  var old=(st.turnCard||st.root).querySelector('.nmsg.form[data-tuid="'+obj.tool_use_id+'"]');
  if(old) old.remove();
  var card=document.createElement("div"); card.className="nmsg form"; card.dataset.tuid=obj.tool_use_id;
  var fields=Array.isArray(obj.fields)?obj.fields:[];
  var html='<div class="fhead">'+_I('receipt')+' Codex 表单请求</div><div class="fmsg">'+nEsc(obj.message||"需要填写表单")+'</div>';
  html+='<div class="fmeta">'+nEsc(obj.server_name||"MCP")+' · '+nEsc(obj.mode||"form")+'</div>';
  if(fields.length){ html+=fields.map(nFormFieldHtml).join(""); }
  else{ html+='<div class="fitem"><label>表单 JSON</label><div class="fdesc">当前 openai/form schema 无法自动拆字段,可直接填写 JSON 对象。</div><textarea class="finp fjson" rows="5" placeholder="{&quot;field&quot;:&quot;value&quot;}"></textarea></div>'; }
  if(obj.schema_detail){ html+='<details><summary>schema 详情</summary><pre>'+nEsc(obj.schema_detail)+'</pre></details>'; }
  html+='<div class="ferr"></div><div class="abtns"><button class="allow">提交</button><button class="deny">拒绝</button></div>';
  card.innerHTML=html;
  card.querySelector(".allow").addEventListener("click", function(){ nSubmitForm(sid,obj,card,"accept"); });
  card.querySelector(".deny").addEventListener("click", function(){ nSubmitForm(sid,obj,card,"decline"); });
  nTurnCard(st).appendChild(card); st.curTxt=null; st.lastWasHumanUser=false; nScrollBottom();
  setTimeout(function(){ var first=card.querySelector(".finp"); if(first) first.focus({preventScroll:true}); }, 50);
}
